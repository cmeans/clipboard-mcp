"""Platform-agnostic clipboard reading with support for rich (HTML) and plain text formats.

Detection order:
  1. Wayland (wl-paste)
  2. X11 (xclip)
  3. macOS (osascript / pbpaste)
  4. Windows (PowerShell)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    """Raised when clipboard access fails."""


async def _run(cmd: list[str], *, timeout: float = 5.0, env: dict[str, str] | None = None) -> str:
    """Run a subprocess and return its stdout as a string."""
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
        err = stderr.decode(errors="replace").strip()
        # wl-paste returns exit 1 with "No suitable type" when format unavailable
        # xclip returns 1 when target not available
        # These are expected "not available" signals, not hard errors.
        if proc.returncode == 1:
            return ""
        raise ClipboardError(f"Clipboard command failed (rc={proc.returncode}): {err}")

    return stdout.decode(errors="replace")


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
        if shutil.which("xsel"):
            return "x11"  # We'll prefer xclip but note xsel as fallback
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
        return await _run(["osascript", "-e", script])

    # pbpaste gives plain text
    return await _run(["pbpaste"])


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
    raw = await _run(["osascript", "-e", script])
    return [line.strip() for line in raw.splitlines() if line.strip()]


async def _windows_read(mime_type: str) -> str:
    if mime_type == "text/html":
        # PowerShell: Get HTML format from clipboard
        script = (
            "[System.Windows.Forms.Clipboard]::GetData("
            "[System.Windows.Forms.DataFormats]::Html)"
        )
        result = await _run([
            "powershell",
            "-NoProfile",
            "-Command",
            f"Add-Type -AssemblyName System.Windows.Forms; {script}",
        ])
        return result

    return await _run([
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Clipboard",
    ])


async def _windows_list_formats() -> list[str]:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Clipboard]::GetDataObject().GetFormats()"
    )
    raw = await _run(["powershell", "-NoProfile", "-Command", script])
    return [line.strip() for line in raw.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Cache the detected backend for the process lifetime
_backend: str | None = None


def _get_backend() -> str:
    # TODO:Put a pylint ignore here.
    global _backend
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


async def read_clipboard(mime_type: str = "text/plain") -> str:
    """Read the clipboard content in the specified MIME type.

    Returns an empty string if the requested format is not available.
    """
    backend = _get_backend()
    return await _READERS[backend](mime_type)


async def list_clipboard_formats() -> list[str]:
    """Return the list of MIME/format types currently available on the clipboard."""
    backend = _get_backend()
    return await _FORMAT_LISTERS[backend]()
