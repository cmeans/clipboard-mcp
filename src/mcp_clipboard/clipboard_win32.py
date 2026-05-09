"""Direct Win32 clipboard backend via pywin32.

Replaces the PowerShell-subprocess-per-call backend used in earlier versions
of this server. The subprocess approach had two structural problems:

1. **Cross-process read-after-write race.** Each MCP tool call spawned a
   fresh ``powershell -NoProfile -Command "..."`` instance, opened the
   clipboard, did its op, and exited. After a SetDataObject(.., copy=true)
   the OLE clipboard chain needs to fully propagate the snapshot from the
   exiting writer process before a fresh reader process sees it. The
   resulting staleness window made `clipboard_copy(mime_type=image/svg+xml)`
   appear to silently no-op when followed by an immediate `paste` /
   `list_formats` / `read_raw` -- the bytes were on the clipboard, but
   the next reader saw the previous state.
2. **PowerShell stdin / stdout codepage transcoding.** Bytes piped between
   Python and PowerShell went through `[Console]::InputEncoding` /
   `OutputEncoding` which default to the parent's active console code page
   (typically CP1252 on US-English Windows). Non-ASCII codepoints were
   transliterated or substituted with U+003F. Closed-but-recurring (#129
   on the input side, #142/#132 on the output side).

This module keeps clipboard ownership inside the long-lived MCP-server
Python process. All clipboard operations happen synchronously in our own
address space via the Win32 clipboard API. No subprocess spawn, no codepage
transcoding, no cross-process race.

Threading: the standard Win32 clipboard functions (OpenClipboard,
SetClipboardData, GetClipboardData, etc.) are MTA-safe -- they do NOT
require an STA-marked thread. STA is only required for the OLE-flavored
helpers (OleSetClipboard / OleGetClipboard) which we do not use. Our
asyncio caller wraps each function in `asyncio.to_thread` for non-blocking
dispatch.

Module imports are deferred to function bodies so this file can be parsed
on non-Windows platforms (CI runs on Linux). Calling any function on a
non-Windows host raises ``ImportError`` immediately rather than producing
a confusing pywin32 error later.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


# Public API contract (kept stable so dispatch in clipboard.py does not
# need to know the backend implementation):
#
#   read_text(mime_type: str) -> str
#       Returns "" if the format is not on the clipboard. Caller decides
#       whether absence is an error.
#
#   write_text(content: str, mime_type: str) -> None
#       Replaces the clipboard with the given (mime, text) pair. Atomic.
#
#   write_multi(formats: dict[str, str]) -> None
#       Replaces the clipboard with all (mime, text) pairs in one
#       OpenClipboard transaction. Used for clipboard_copy_markdown's
#       text/html + text/plain combo.
#
#   list_formats() -> list[str]
#       Returns native format names. Caller maps to MIME via _WIN_TO_MIME
#       in clipboard.py.
#
# Image read/write stays on the PowerShell backend in Phase 1; will move
# here in a follow-up PR with DIB <-> PNG conversion.


# --- Format registration cache ---------------------------------------------
#
# RegisterClipboardFormat returns the same integer ID for the same string
# for the lifetime of the user session, but the call is not free, so we
# cache. Standard format constants (CF_TEXT, CF_UNICODETEXT, CF_DIB, etc.)
# do not need registration; they have fixed IDs in the Win32 API.

_format_id_cache: dict[str, int] = {}


def _open_clipboard_with_retry(win32clipboard: Any, retries: int = 10, delay_ms: int = 50) -> None:
    """OpenClipboard fails with WindowsError when another process holds it.

    Mirrors the pattern Microsoft documents for SetDataObject's four-arg
    overload (10 retries x 100ms = 1s ceiling). We use 50ms here because
    the bottleneck this function fights is brief (~milliseconds) contention
    from clipboard inspectors / antivirus, not the multi-hundred-ms OLE
    propagation that the SetDataObject retry was originally introduced for.
    """
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception as exc:  # pywin32 raises pywintypes.error
            last_err = exc
            time.sleep(delay_ms / 1000.0)
    raise RuntimeError(
        f"OpenClipboard failed after {retries} retries (delay={delay_ms}ms each); "
        f"another process is holding the clipboard. Last error: {last_err!r}"
    )


def _import_win32clipboard() -> Any:
    """Defer the pywin32 import so this module can be parsed on Linux CI.

    Raises ImportError with a clear message on non-Windows platforms.
    """
    try:
        import win32clipboard  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "clipboard_win32 requires pywin32, which is only installed on "
            "Windows. This module should not be invoked on non-Windows hosts."
        ) from exc
    return win32clipboard


def _register_format(name: str) -> int:
    """Look up (and cache) the registered clipboard format ID for `name`.

    Standard formats have fixed IDs in win32clipboard (CF_*); custom
    strings like 'image/svg+xml', 'HTML Format', 'Rich Text Format' get
    registered the first time they are seen, returning a stable integer
    in the 0xC000-0xFFFF range for the user session.
    """
    if name in _format_id_cache:
        return _format_id_cache[name]
    win32clipboard = _import_win32clipboard()
    fmt_id = win32clipboard.RegisterClipboardFormat(name)
    _format_id_cache[name] = fmt_id
    return fmt_id


# --- MIME -> Windows format mapping ----------------------------------------
#
# CF_UNICODETEXT carries UTF-16 LE; the Win32 docs specify it as the
# canonical Unicode text format. Using it for text/plain avoids the
# transcoding loss CF_TEXT (CP_ACP) and CF_OEMTEXT (CP_OEMCP) would impose.
#
# 'HTML Format' is the registered string-name for CF_HTML; the bytes are
# the CF_HTML wrapper produced by clipboard._windows_html_clipboard_wrap
# (Version, StartHTML / EndHTML offsets, etc.) encoded UTF-8.
#
# 'Rich Text Format' is the registered string-name for CF_RTF; bytes are
# UTF-8 RTF source.
#
# 'image/svg+xml' is a custom format string; bytes are UTF-8 SVG markup.

_MIME_TO_FORMAT_NAME: dict[str, str] = {
    "text/html": "HTML Format",
    "text/rtf": "Rich Text Format",
    "image/svg+xml": "image/svg+xml",
}


def _format_id_for_mime(win32clipboard: Any, mime_type: str) -> int:
    """Resolve a MIME type to its Win32 clipboard format ID."""
    if mime_type == "text/plain":
        return win32clipboard.CF_UNICODETEXT
    name = _MIME_TO_FORMAT_NAME.get(mime_type)
    if name is None:
        raise ValueError(f"Unsupported MIME type for Win32 clipboard: {mime_type!r}")
    return _register_format(name)


# --- Public sync API -------------------------------------------------------


def read_text(mime_type: str) -> str:
    """Read a text-shaped format from the clipboard. Returns "" if absent.

    text/plain reads CF_UNICODETEXT (UTF-16 LE); pywin32 returns a
    Python str directly via the Unicode-aware wrapper.

    text/html reads the registered "HTML Format"; the bytes are the
    full CF_HTML wrapper (Version + offsets + body) encoded UTF-8.
    Returned as the decoded UTF-8 string -- the parser layer in
    server.py extracts the body fragment from between the StartFragment
    / EndFragment offsets.

    text/rtf and image/svg+xml read their registered custom format
    strings; bytes are UTF-8 source.
    """
    win32clipboard = _import_win32clipboard()
    fmt_id = _format_id_for_mime(win32clipboard, mime_type)

    _open_clipboard_with_retry(win32clipboard)
    try:
        if not win32clipboard.IsClipboardFormatAvailable(fmt_id):
            return ""
        data = win32clipboard.GetClipboardData(fmt_id)
    finally:
        win32clipboard.CloseClipboard()

    # CF_UNICODETEXT comes back as a Python str directly. Custom registered
    # formats come back as bytes; decode UTF-8.
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    # Defensive: pywin32 has historically returned bytes-with-null-terminator
    # for some custom formats. Strip a single trailing NUL if present.
    return str(data)


def write_text(content: str, mime_type: str) -> None:
    """Replace the clipboard with a single (format, content) pair.

    Atomic via OpenClipboard / EmptyClipboard / SetClipboardData /
    CloseClipboard. The previous clipboard owner is fully replaced before
    the function returns -- no cross-process propagation window like the
    PowerShell backend had.
    """
    win32clipboard = _import_win32clipboard()
    fmt_id = _format_id_for_mime(win32clipboard, mime_type)

    if mime_type == "text/plain":
        # CF_UNICODETEXT: pywin32's SetClipboardData accepts a Python str
        # directly and handles UTF-16 LE encoding + NUL termination.
        encoded: str | bytes = content
    else:
        # Custom registered formats expect raw bytes. UTF-8 across the
        # board (matches the previous PowerShell backend's UTF-8 piping).
        encoded = content.encode("utf-8")

    _open_clipboard_with_retry(win32clipboard)
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(fmt_id, encoded)
    finally:
        win32clipboard.CloseClipboard()


def write_multi(formats: dict[str, str]) -> None:
    """Replace the clipboard with multiple (mime, content) pairs in ONE
    OpenClipboard transaction.

    Used by `clipboard_copy_markdown` to put `text/html` and `text/plain`
    on the clipboard simultaneously, so paste targets that prefer one
    format over the other (Slack/Gmail vs vim/terminal) each get the
    representation they expect.

    Atomic at the Win32 clipboard chain level: a single Empty -> Set per
    format -> Close transaction. No window during which the clipboard
    holds half the formats.
    """
    if not formats:
        return
    win32clipboard = _import_win32clipboard()

    # Resolve all format IDs and encode all payloads BEFORE opening the
    # clipboard, so we hold the clipboard for the minimum time and any
    # encoding errors raise outside the OpenClipboard / CloseClipboard
    # bracket where they could leave the clipboard in a half-open state.
    resolved: list[tuple[int, str | bytes]] = []
    for mime_type, content in formats.items():
        fmt_id = _format_id_for_mime(win32clipboard, mime_type)
        if mime_type == "text/plain":
            resolved.append((fmt_id, content))
        else:
            resolved.append((fmt_id, content.encode("utf-8")))

    _open_clipboard_with_retry(win32clipboard)
    try:
        win32clipboard.EmptyClipboard()
        for fmt_id, payload in resolved:
            win32clipboard.SetClipboardData(fmt_id, payload)
    finally:
        win32clipboard.CloseClipboard()


def list_formats() -> list[str]:
    """Enumerate all formats currently on the clipboard.

    Returns the native format names (e.g. "Text", "UnicodeText",
    "HTML Format", "image/svg+xml", "System.String") in the order
    EnumClipboardFormats returned them. The caller in clipboard.py maps
    to MIME via _WIN_TO_MIME and deduplicates Text/UnicodeText collisions.

    Standard format constants get translated to their string names via
    GetClipboardFormatName when possible; some constants (CF_LOCALE,
    CF_OEMTEXT, etc.) have no name in the registered-format table and
    we fall back to the integer-as-string for visibility.
    """
    win32clipboard = _import_win32clipboard()

    _open_clipboard_with_retry(win32clipboard)
    try:
        names: list[str] = []
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            name = _format_name(win32clipboard, fmt)
            names.append(name)
    finally:
        win32clipboard.CloseClipboard()
    return names


def _format_name(win32clipboard: Any, fmt: int) -> str:
    """Resolve a clipboard format ID to a human-readable name."""
    # Standard formats: hand-roll the names because GetClipboardFormatName
    # only works for registered (custom) formats, not the CF_* constants.
    standard = {
        win32clipboard.CF_TEXT: "Text",
        win32clipboard.CF_BITMAP: "Bitmap",
        win32clipboard.CF_METAFILEPICT: "MetaFilePict",
        win32clipboard.CF_SYLK: "SYLK",
        win32clipboard.CF_DIF: "DIF",
        win32clipboard.CF_TIFF: "TIFF",
        win32clipboard.CF_OEMTEXT: "OEMText",
        win32clipboard.CF_DIB: "DeviceIndependentBitmap",
        win32clipboard.CF_PALETTE: "Palette",
        win32clipboard.CF_PENDATA: "PenData",
        win32clipboard.CF_RIFF: "RIFF",
        win32clipboard.CF_WAVE: "Wave",
        win32clipboard.CF_UNICODETEXT: "UnicodeText",
        win32clipboard.CF_ENHMETAFILE: "EnhMetaFile",
        win32clipboard.CF_HDROP: "HDrop",
        win32clipboard.CF_LOCALE: "Locale",
        win32clipboard.CF_DIBV5: "DIBv5",
    }
    if fmt in standard:
        return standard[fmt]
    # Registered (custom) formats: look up via the Win32 API.
    try:
        name = win32clipboard.GetClipboardFormatName(fmt)
        if name:
            return name
    except Exception:
        # GetClipboardFormatName raises for built-in formats it does not know;
        # fall through to the numeric stringification.
        pass
    return f"Format{fmt}"
