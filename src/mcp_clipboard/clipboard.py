"""Platform-agnostic clipboard access with support for rich (HTML) and plain text formats.

Detection order:
  1. Wayland (wl-paste / wl-copy)
  2. X11 (xclip)
  3. macOS (osascript / pbpaste / pbcopy)
  4. Windows (PowerShell)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import platform
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    """Raised when clipboard access fails."""


def base_mime_type(mime: str) -> str:
    """Strip parameters from a MIME type string.

    MIME types on the clipboard often include parameters after a semicolon
    (e.g., ``text/plain;charset=utf-8``).  This returns just the base type.
    """
    return mime.split(";", 1)[0].strip()


async def _run_subprocess(
    cmd: list[str],
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
    allow_empty_exit: bool = True,
) -> bytes:
    """Run a subprocess and return its stdout as raw bytes.

    When *allow_empty_exit* is ``True``, exit code 1 is treated as "format not
    available" and returns empty bytes.  This is the expected behaviour for
    ``wl-paste`` ("No suitable type of content") and ``xclip`` ("target not
    available").  Set it to ``False`` for macOS and Windows backends where exit
    code 1 indicates a real error (script failure, permission denied, etc.).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError as fnf:
        raise ClipboardError(f"Command not found: {cmd[0]}") from fnf
    except asyncio.TimeoutError as te:
        proc.kill()
        raise ClipboardError(f"Clipboard command timed out: {' '.join(cmd)}") from te

    if proc.returncode != 0:
        if allow_empty_exit and proc.returncode == 1:
            return b""
        err = stderr.decode(errors="replace").strip()
        raise ClipboardError(f"Clipboard command failed (rc={proc.returncode}): {err}")

    return stdout


async def _run(
    cmd: list[str],
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
    allow_empty_exit: bool = True,
) -> str:
    """Run a subprocess and return its stdout as a string."""
    data = await _run_subprocess(
        cmd, timeout=timeout, env=env, allow_empty_exit=allow_empty_exit
    )
    return data.decode(errors="replace")


async def _run_binary(
    cmd: list[str],
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
    allow_empty_exit: bool = True,
) -> bytes:
    """Run a subprocess and return its stdout as raw bytes."""
    return await _run_subprocess(
        cmd, timeout=timeout, env=env, allow_empty_exit=allow_empty_exit
    )


async def _run_with_stdin(
    cmd: list[str],
    input_data: bytes,
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
) -> None:
    """Run a subprocess, piping input_data to its stdin.

    stdout and stderr are sent to /dev/null because clipboard write commands
    (wl-copy, xclip) fork a background child that inherits pipe file
    descriptors.  If those streams are piped, communicate() blocks waiting
    for the child to close them — which only happens when another copy
    replaces the clipboard — causing a spurious timeout.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        await asyncio.wait_for(proc.communicate(input=input_data), timeout=timeout)
    except FileNotFoundError as fnf:
        raise ClipboardError(f"Command not found: {cmd[0]}") from fnf
    except asyncio.TimeoutError as te:
        proc.kill()
        raise ClipboardError(f"Clipboard command timed out: {' '.join(cmd)}") from te

    if proc.returncode != 0:
        raise ClipboardError(f"Clipboard write failed (rc={proc.returncode}): {cmd[0]}")


def _find_wayland_display() -> str | None:
    """Find an available Wayland compositor socket.

    Scans $XDG_RUNTIME_DIR (falling back to /run/user/<uid>) for wayland-*
    Unix domain sockets.  Returns the socket name (e.g. "wayland-0") or None.
    """
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    runtime_dir = Path(xdg_runtime)
    if not runtime_dir.is_dir():
        return None

    try:
        sockets = sorted(
            entry.name
            for entry in runtime_dir.iterdir()
            if entry.name.startswith("wayland-")
            and not entry.name.endswith(".lock")
            and stat.S_ISSOCK(entry.stat().st_mode)
        )
    except OSError:
        return None

    return sockets[0] if sockets else None


def _wayland_env() -> dict[str, str] | None:
    """Build a subprocess env dict that ensures wl-paste can connect.

    wl-paste (via libwayland) needs XDG_RUNTIME_DIR to locate the compositor
    socket, and optionally WAYLAND_DISPLAY to pick which one.  When launched by
    an app launcher like Claude Desktop, both may be stripped from the
    environment.

    Returns None (inherit parent env) when both vars are already set.
    Otherwise returns a copy of os.environ with the missing vars injected.
    """
    has_display = bool(os.environ.get("WAYLAND_DISPLAY"))
    has_runtime = bool(os.environ.get("XDG_RUNTIME_DIR"))

    if has_display and has_runtime:
        return None  # both set — let subprocess inherit normally

    # Determine the runtime dir (needed by wl-paste even if WAYLAND_DISPLAY is set)
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not Path(xdg_runtime).is_dir():
        return None

    env = os.environ.copy()

    if not has_runtime:
        env["XDG_RUNTIME_DIR"] = xdg_runtime

    if not has_display:
        display = _find_wayland_display()
        if display:
            env["WAYLAND_DISPLAY"] = display

    return env


def _detect_backend() -> str:
    """Detect which clipboard backend to use.

    Returns one of: 'wayland', 'x11', 'macos', 'windows'.
    Raises ClipboardError if no supported backend is found.
    """
    system = platform.system()

    if system == "Linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
        has_wl_paste = shutil.which("wl-paste")

        # Prefer Wayland if env vars indicate it, or if a compositor socket exists
        if has_wl_paste and (
            session_type == "wayland"
            or wayland_display
            or _find_wayland_display()
        ):
            return "wayland"
        if shutil.which("xclip"):
            return "x11"
        raise ClipboardError(
            "No clipboard tool found. Install wl-paste (Wayland) or xclip (X11).\n"
            "  Fedora: sudo dnf install wl-clipboard   # or xclip\n"
            "  Ubuntu: sudo apt install wl-clipboard    # or xclip"
        )
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"

    raise ClipboardError(f"Unsupported platform: {system}")


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


async def _wayland_read(mime_type: str) -> str:
    return await _run(["wl-paste", "--type", mime_type], env=_wayland_env())


async def _wayland_list_formats() -> list[str]:
    raw = await _run(["wl-paste", "--list-types"], env=_wayland_env())
    return [line.strip() for line in raw.splitlines() if line.strip()]


async def _x11_read(mime_type: str) -> str:
    # xclip uses -target for MIME, -selection clipboard for the main clipboard
    return await _run(
        ["xclip", "-selection", "clipboard", "-target", mime_type, "-o"]
    )


async def _x11_list_formats() -> list[str]:
    raw = await _run(["xclip", "-selection", "clipboard", "-target", "TARGETS", "-o"])
    return [line.strip() for line in raw.splitlines() if line.strip()]


async def _macos_read(mime_type: str) -> str:
    if mime_type == "text/html":
        # osascript to get HTML from clipboard
        script = (
            'use framework "AppKit"\n'
            "set pb to current application's NSPasteboard's generalPasteboard()\n"
            'set htmlData to pb\'s dataForType:"public.html"\n'
            "if htmlData is missing value then return \"\"\n"
            "set htmlString to (current application's NSString's alloc()'s "
            "initWithData:htmlData encoding:(current application's NSUTF8StringEncoding))\n"
            "return htmlString as text"
        )
        return await _run(["osascript", "-e", script], allow_empty_exit=False)

    if mime_type == "text/plain":
        return await _run(["pbpaste"], allow_empty_exit=False)

    if mime_type == "text/rtf":
        script = (
            'use framework "AppKit"\n'
            "set pb to current application's NSPasteboard's generalPasteboard()\n"
            'set rtfData to pb\'s dataForType:"public.rtf"\n'
            'if rtfData is missing value then return ""\n'
            "set rtfString to (current application's NSString's alloc()'s "
            "initWithData:rtfData encoding:(current application's NSUTF8StringEncoding))\n"
            "return rtfString as text"
        )
        return await _run(["osascript", "-e", script], allow_empty_exit=False)

    # Unsupported MIME type — signal "not available" rather than returning wrong content
    return ""


_UTI_TO_MIME: dict[str, str] = {
    "public.html": "text/html",
    "public.utf8-plain-text": "text/plain",
    "public.plain-text": "text/plain",
    "public.rtf": "text/rtf",
    "public.png": "image/png",
    "public.tiff": "image/tiff",
    "public.jpeg": "image/jpeg",
    "public.url": "text/uri-list",
}


async def _macos_list_formats() -> list[str]:
    script = (
        'use framework "AppKit"\n'
        "set pb to current application's NSPasteboard's generalPasteboard()\n"
        "set theTypes to pb's types() as list\n"
        'set output to ""\n'
        "repeat with t in theTypes\n"
        '  set output to output & (t as text) & linefeed\n'
        "end repeat\n"
        "return output"
    )
    raw = await _run(["osascript", "-e", script], allow_empty_exit=False)
    native = [line.strip() for line in raw.splitlines() if line.strip()]
    return [_UTI_TO_MIME.get(t, t) for t in native]


async def _windows_read(mime_type: str) -> str:
    if mime_type == "text/html":
        # PowerShell: Get HTML format from clipboard
        script = (
            "[System.Windows.Forms.Clipboard]::GetData("
            "[System.Windows.Forms.DataFormats]::Html)"
        )
        return await _run([
            "powershell",
            "-NoProfile",
            "-Command",
            f"Add-Type -AssemblyName System.Windows.Forms; {script}",
        ], allow_empty_exit=False)

    if mime_type == "text/plain":
        return await _run([
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Clipboard",
        ], allow_empty_exit=False)

    if mime_type == "text/rtf":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$data = [System.Windows.Forms.Clipboard]::GetData("
            "[System.Windows.Forms.DataFormats]::Rtf); "
            "if ($data -eq $null) { return }; $data"
        )
        return await _run([
            "powershell",
            "-NoProfile",
            "-Command",
            script,
        ], allow_empty_exit=False)

    # Unsupported MIME type — signal "not available" rather than returning wrong content
    return ""


_WIN_TO_MIME: dict[str, str] = {
    "HTML Format": "text/html",
    "Text": "text/plain",
    "UnicodeText": "text/plain",
    "Rich Text Format": "text/rtf",
    "PNG": "image/png",
    "Bitmap": "image/bmp",
}


async def _windows_list_formats() -> list[str]:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Clipboard]::GetDataObject().GetFormats()"
    )
    raw = await _run(["powershell", "-NoProfile", "-Command", script],
                     allow_empty_exit=False)
    native = [line.strip() for line in raw.splitlines() if line.strip()]
    return [_WIN_TO_MIME.get(f, f) for f in native]


# ---------------------------------------------------------------------------
# Backend image readers (binary)
# ---------------------------------------------------------------------------


async def _wayland_read_image(mime_type: str) -> bytes:
    return await _run_binary(["wl-paste", "--type", mime_type], env=_wayland_env())


async def _x11_read_image(mime_type: str) -> bytes:
    return await _run_binary(
        ["xclip", "-selection", "clipboard", "-target", mime_type, "-o"]
    )


async def _macos_read_image(mime_type: str) -> bytes:
    # Map MIME to UTI for NSPasteboard lookup -- reject unknown types
    # to prevent AppleScript injection via crafted MIME strings (#24)
    mime_to_uti = {v: k for k, v in _UTI_TO_MIME.items() if v.startswith("image/")}
    uti = mime_to_uti.get(mime_type)
    if uti is None:
        raise ClipboardError(f"Unsupported image type: {mime_type}")
    # Return image data as base64 text via osascript, then decode to bytes
    script = (
        'use framework "AppKit"\n'
        'use framework "Foundation"\n'
        "set pb to current application's NSPasteboard's generalPasteboard()\n"
        f'set imgData to pb\'s dataForType:"{uti}"\n'
        'if imgData is missing value then return ""\n'
        "set b64 to (imgData's base64EncodedStringWithOptions:0)\n"
        "return b64 as text"
    )
    b64_text = await _run(["osascript", "-e", script], allow_empty_exit=False)
    if not b64_text.strip():
        return b""
    return base64.b64decode(b64_text.strip())


async def _windows_read_image(mime_type: str) -> bytes:
    # Read clipboard image as base64 via PowerShell
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        "if ($img -eq $null) { return }; "
        "$ms = New-Object System.IO.MemoryStream; "
        "$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); "
        "[Convert]::ToBase64String($ms.ToArray())"
    )
    b64_text = await _run(["powershell", "-NoProfile", "-Command", script],
                          allow_empty_exit=False)
    if not b64_text.strip():
        return b""
    return base64.b64decode(b64_text.strip())


# ---------------------------------------------------------------------------
# Backend writers (text)
# ---------------------------------------------------------------------------


async def _wayland_write(content: str) -> None:
    await _run_with_stdin(["wl-copy"], content.encode(), env=_wayland_env())


async def _x11_write(content: str) -> None:
    await _run_with_stdin(
        ["xclip", "-selection", "clipboard"], content.encode()
    )


async def _macos_write(content: str) -> None:
    await _run_with_stdin(["pbcopy"], content.encode())


async def _windows_write(content: str) -> None:
    await _run_with_stdin(
        [
            "powershell", "-NoProfile", "-Command",
            "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
        ],
        content.encode(),
    )


# ---------------------------------------------------------------------------
# Backend typed writers (MIME-aware)
# ---------------------------------------------------------------------------


async def _wayland_write_typed(content: str, mime_type: str) -> None:
    await _run_with_stdin(
        ["wl-copy", "--type", mime_type], content.encode(), env=_wayland_env()
    )


async def _x11_write_typed(content: str, mime_type: str) -> None:
    await _run_with_stdin(
        ["xclip", "-selection", "clipboard", "-target", mime_type],
        content.encode(),
    )


async def _macos_write_typed(content: str, mime_type: str) -> None:
    if mime_type == "text/plain":
        await _run_with_stdin(["pbcopy"], content.encode())
        return

    if mime_type in ("text/html", "text/rtf"):
        uti = "public.html" if mime_type == "text/html" else "public.rtf"
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        script = (
            'use framework "AppKit"\n'
            'use framework "Foundation"\n'
            f'set b64 to "{b64}"\n'
            "set decoded to (current application's NSData's alloc()'s "
            "initWithBase64EncodedString:b64 options:0)\n"
            "set pb to current application's NSPasteboard's generalPasteboard()\n"
            "pb's clearContents()\n"
            f"pb's setData:decoded forType:\"{uti}\"\n"
        )
        await _run(["osascript", "-e", script], allow_empty_exit=False)
        return

    raise ClipboardError(
        f"macOS clipboard write does not support MIME type {mime_type!r}. "
        "Supported: text/plain, text/html, text/rtf"
    )


def _windows_html_clipboard_wrap(html: str) -> str:
    """Wrap HTML in the Windows CF_HTML clipboard format.

    The CF_HTML format requires a plain-text header containing byte offsets
    to the start/end of the HTML document and the selected fragment within it.
    Byte offsets are calculated after encoding to UTF-8.
    """
    marker_start = "<!--StartFragment-->"
    marker_end = "<!--EndFragment-->"
    body = f"<html><body>{marker_start}{html}{marker_end}</body></html>"

    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:08d}\r\n"
        "EndHTML:{end_html:08d}\r\n"
        "StartFragment:{start_frag:08d}\r\n"
        "EndFragment:{end_frag:08d}\r\n"
    )
    # Measure header length using placeholder values (all same digit count)
    placeholder = header_template.format(
        start_html=0, end_html=0, start_frag=0, end_frag=0
    )
    header_len = len(placeholder.encode("utf-8"))
    body_bytes = body.encode("utf-8")

    start_html = header_len
    start_frag = header_len + len(
        f"<html><body>{marker_start}".encode("utf-8")
    )
    end_frag = header_len + body_bytes.index(marker_end.encode("utf-8"))
    end_html = header_len + len(body_bytes)

    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_frag=start_frag,
        end_frag=end_frag,
    )
    return header + body


async def _windows_write_typed(content: str, mime_type: str) -> None:
    if mime_type == "text/plain":
        await _run_with_stdin(
            [
                "powershell", "-NoProfile", "-Command",
                "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ],
            content.encode(),
        )
        return

    if mime_type == "text/html":
        cf_html = _windows_html_clipboard_wrap(content)
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$content = [Console]::In.ReadToEnd(); "
            "$data = New-Object System.Windows.Forms.DataObject; "
            "$data.SetData([System.Windows.Forms.DataFormats]::Html, $content); "
            "[System.Windows.Forms.Clipboard]::SetDataObject($data, $true)"
        )
        await _run_with_stdin(
            ["powershell", "-NoProfile", "-Command", script],
            cf_html.encode("utf-8"),
        )
        return

    if mime_type == "text/rtf":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$content = [Console]::In.ReadToEnd(); "
            "$data = New-Object System.Windows.Forms.DataObject; "
            "$data.SetData([System.Windows.Forms.DataFormats]::Rtf, $content); "
            "[System.Windows.Forms.Clipboard]::SetDataObject($data, $true)"
        )
        await _run_with_stdin(
            ["powershell", "-NoProfile", "-Command", script],
            content.encode("utf-8"),
        )
        return

    raise ClipboardError(
        f"Windows clipboard write does not support MIME type {mime_type!r}. "
        "Supported: text/plain, text/html, text/rtf"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Cache the detected backend for the process lifetime
_backend: str | None = None


def _get_backend() -> str:
    global _backend  # noqa: PLW0603
    if _backend is None:
        _backend = _detect_backend()
        logger.debug("Clipboard backend: %s", _backend)
    return _backend


_READERS = {
    "wayland": _wayland_read,
    "x11": _x11_read,
    "macos": _macos_read,
    "windows": _windows_read,
}

_FORMAT_LISTERS = {
    "wayland": _wayland_list_formats,
    "x11": _x11_list_formats,
    "macos": _macos_list_formats,
    "windows": _windows_list_formats,
}

_IMAGE_READERS = {
    "wayland": _wayland_read_image,
    "x11": _x11_read_image,
    "macos": _macos_read_image,
    "windows": _windows_read_image,
}

_WRITERS = {
    "wayland": _wayland_write,
    "x11": _x11_write,
    "macos": _macos_write,
    "windows": _windows_write,
}

_TYPED_WRITERS = {
    "wayland": _wayland_write_typed,
    "x11": _x11_write_typed,
    "macos": _macos_write_typed,
    "windows": _windows_write_typed,
}


async def read_clipboard(mime_type: str = "text/plain") -> str:
    """Read the clipboard content in the specified MIME type.

    Returns an empty string if the requested format is not available.

    Clipboard MIME types may include parameters (e.g.,
    ``text/plain;charset=utf-8``).  If the exact requested type is not
    found, this function falls back to listing available formats and
    retrying with a matching suffixed variant.
    """
    backend = _get_backend()
    result = await _READERS[backend](mime_type)

    # Wayland / X11 pass the MIME type verbatim to wl-paste / xclip which
    # may do strict matching.  Resolve via format listing when needed.
    if not result and backend in ("wayland", "x11"):
        base = base_mime_type(mime_type)
        formats = await _FORMAT_LISTERS[backend]()
        for fmt in formats:
            if fmt != mime_type and base_mime_type(fmt) == base:
                result = await _READERS[backend](fmt)
                if result:
                    break

    return result


async def list_clipboard_formats() -> list[str]:
    """Return the list of MIME/format types currently available on the clipboard."""
    backend = _get_backend()
    return await _FORMAT_LISTERS[backend]()


async def read_clipboard_image(mime_type: str = "image/png") -> bytes:
    """Read binary image data from the clipboard.

    Returns raw bytes of the image, or empty bytes if not available.

    Like :func:`read_clipboard`, falls back to a matching suffixed MIME
    type when the exact requested type is not available.
    """
    backend = _get_backend()
    result = await _IMAGE_READERS[backend](mime_type)

    if not result and backend in ("wayland", "x11"):
        base = base_mime_type(mime_type)
        formats = await _FORMAT_LISTERS[backend]()
        for fmt in formats:
            if fmt != mime_type and base_mime_type(fmt) == base:
                result = await _IMAGE_READERS[backend](fmt)
                if result:
                    break

    return result


async def write_clipboard(content: str) -> None:
    """Write plain text to the system clipboard."""
    backend = _get_backend()
    await _WRITERS[backend](content)


async def write_clipboard_typed(content: str, mime_type: str) -> None:
    """Write content to the system clipboard with an explicit MIME type.

    On Wayland and X11, any text MIME type is passed through to the
    underlying tool (``wl-copy --type`` / ``xclip -target``).  On macOS
    and Windows, only ``text/plain``, ``text/html``, and ``text/rtf`` are
    supported; other types raise :exc:`ClipboardError`.

    Note: Wayland and X11 write a single MIME type per call.  Writing
    multiple types atomically (e.g. both ``text/html`` and ``text/plain``)
    requires owning the clipboard selection across calls, which is not
    supported by this implementation.
    """
    backend = _get_backend()
    await _TYPED_WRITERS[backend](content, mime_type)
