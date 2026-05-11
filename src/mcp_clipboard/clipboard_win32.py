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
address space. No subprocess spawn, no codepage transcoding, no
cross-process race.

**Write path: OleSetClipboard + OleFlushClipboard.** MSDN is explicit that
"sharing non-standard clipboard data formats between processes requires
using the OleSetClipboard API, as SetClipboardData alone is not enough."
Raw SetClipboardData with registered custom formats (image/svg+xml, HTML
Format, Rich Text Format) was observed to silently no-op when the prior
clipboard owner was a foreign process -- the call returned success but
list_formats afterward showed the prior state surviving. OleSetClipboard
hands the clipboard to an OLE-managed internal window handle (the same
path .NET's Clipboard.SetDataObject and PowerShell's Set-Clipboard take),
which handles ownership transitions correctly. OleFlushClipboard is
called immediately after to render the data into HGLOBAL handles and
release our IDataObject pointer; the data then persists without our
process needing to pump messages.

**Read path: OpenClipboard + GetClipboardData.** Reads still use the
direct Win32 API; OLE is only required for the cross-process write race.
The message-only window from _get_clipboard_hwnd is retained for reads.

Threading: OLE clipboard ops require an STA-initialized thread.
asyncio.to_thread uses a worker pool; each worker calls _ensure_com_init
on first use which sets up COINIT_APARTMENTTHREADED via CoInitializeEx.
The apartment lives for the worker's lifetime; we don't CoUninitialize
because Python's interpreter shutdown handles thread teardown.

Module imports are deferred to function bodies so this file can be parsed
on non-Windows platforms (CI runs on Linux). Calling any function on a
non-Windows host raises ``ImportError`` immediately rather than producing
a confusing pywin32 error later.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# Public API contract (kept stable so dispatch in clipboard.py does not
# need to know the backend implementation):
#
#   read_text(mime_type: str) -> str
#       Returns "" if the format is not on the clipboard. Caller decides
#       whether absence is an error.
#
#   write_text(content: str, mime_type: str) -> None
#       Replaces the clipboard with the given (mime, text) pair via
#       OleSetClipboard + OleFlushClipboard.
#
#   write_multi(formats: dict[str, str]) -> None
#       Replaces the clipboard with all (mime, text) pairs in one
#       OleSetClipboard transaction (atomic by construction). Used for
#       clipboard_copy_markdown's text/html + text/plain combo.
#
#   list_formats() -> list[str]
#       Returns native format names. Caller maps to MIME via _WIN_TO_MIME
#       in clipboard.py.
#
# Image read/write stays on the PowerShell backend in Phase 1; will move
# here in a follow-up PR with DIB <-> PNG conversion.


# --- COM apartment management ----------------------------------------------
#
# OleSetClipboard requires the calling thread to have the FULL OLE
# library initialized -- per MSDN: "Before calling this function, you
# must initialize the OLE library by calling OleInitialize." CoInitializeEx
# alone is NOT sufficient: it sets up the COM apartment but does not
# enable the OLE-specific subsystems (clipboard, drag-and-drop,
# marshaling tables) that OleSetClipboard / OleFlushClipboard need. This
# is why the integration-windows CI on commits d3d7372 (cached
# pythoncom.CoInitializeEx), 3904fef (uncached pythoncom.CoInitializeEx),
# 0a0f933 (ctypes-direct ole32.CoInitializeEx), and 0966ef7 (dedicated
# worker thread + ctypes ole32.CoInitializeEx) all failed identically
# with OleSetClipboard raising CO_E_NOTINITIALIZED -- OLE was reporting
# its OLE-specific state as uninitialized even though the COM apartment
# was fine.
#
# Resolution: call ole32.OleInitialize (which internally calls
# CoInitializeEx with COINIT_APARTMENTTHREADED plus the OLE library
# setup) on the dedicated worker thread at start. The worker owns one
# OLE-initialized STA apartment for the process's lifetime; asyncio
# dispatchers submit work via a queue.
#
# Reads stay on the existing OpenClipboard + GetClipboardData path; OLE
# is only required for the cross-process write race, not for reads.

# Magic numbers from Win32 headers, kept here so non-Windows imports don't
# need to touch ctypes / ole32 at module load.
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106 as signed 32-bit


def _ole32_initialize() -> None:
    """Call ole32.OleInitialize(NULL) via ctypes.

    OleInitialize is the canonical setup call for any thread that will
    use OleSetClipboard / OleGetClipboard / OleFlushClipboard / drag-and-
    drop. Internally it does CoInitializeEx(NULL, COINIT_APARTMENTTHREADED)
    plus the additional OLE subsystem setup that the bare CoInitializeEx
    doesn't perform -- which is why earlier attempts that initialized
    only the COM apartment failed at OleSetClipboard with
    CO_E_NOTINITIALIZED despite the apartment being live.

    Accepts S_OK (0, newly inited), S_FALSE (1, same-thread re-init),
    and RPC_E_CHANGED_MODE (different threading model already active).
    Any other negative HRESULT raises OSError.
    """
    import ctypes

    ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]  # Windows-only
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.OleInitialize.restype = ctypes.c_long  # HRESULT (signed 32-bit)
    hr = ole32.OleInitialize(None)
    if hr < 0 and hr != _RPC_E_CHANGED_MODE:
        raise OSError(
            f"OleInitialize (via ctypes / ole32.dll) failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}"
        )


class _ClipboardWorker(threading.Thread):
    """Dedicated daemon thread that owns the OLE clipboard apartment.

    All OLE writes (OleSetClipboard / OleFlushClipboard) run on this
    thread to keep the apartment state stable across calls. The thread:

      1. CoInitializeEx's itself to STA on start (via ole32 + ctypes).
      2. Imports pythoncom on the same thread (so any pywin32-internal
         per-thread state is set up alongside the Win32 TLS init).
      3. Loops on a queue, executing submitted callables and reporting
         results / exceptions back through Futures.

    daemon=True so the worker dies on process exit without needing
    explicit shutdown signaling from the MCP server lifecycle. The
    apartment is implicitly torn down by interpreter shutdown.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True, name="mcp-clipboard-ole")
        self._queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], Future[Any]] | None] = (
            queue.Queue()
        )
        self._started = threading.Event()
        self._init_error: BaseException | None = None

    def run(self) -> None:
        try:
            _ole32_initialize()
            # Import pythoncom on this thread so any pywin32-internal
            # per-thread setup runs here rather than on a caller's thread.
            import pythoncom  # type: ignore[import-not-found,import-untyped]  # noqa: F401
        except BaseException as exc:
            self._init_error = exc
            self._started.set()
            return
        self._started.set()

        while True:
            item = self._queue.get()
            if item is None:  # sentinel for shutdown (tests only)
                return
            fn, args, future = item
            try:
                future.set_result(fn(*args))
            except BaseException as exc:
                future.set_exception(exc)

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        """Queue ``fn(*args)`` for execution on the worker thread and
        return a Future. Raises immediately if the worker failed to init."""
        self._started.wait()
        if self._init_error is not None:
            f: Future[Any] = Future()
            f.set_exception(self._init_error)
            return f
        future: Future[Any] = Future()
        self._queue.put((fn, args, future))
        return future


_clipboard_worker: _ClipboardWorker | None = None
_clipboard_worker_lock = threading.Lock()


def _get_clipboard_worker() -> _ClipboardWorker:
    """Lazy-start the OLE worker thread on first use.

    Double-checked locking: clipboard.py dispatches the synchronous Win32
    path through asyncio.to_thread, so a burst of concurrent first-callers
    is possible. The check-outside / check-inside-lock pattern means at
    most one worker is ever created and the steady-state read is lock-free.
    """
    global _clipboard_worker
    if _clipboard_worker is not None:
        return _clipboard_worker
    with _clipboard_worker_lock:
        if _clipboard_worker is None:
            _clipboard_worker = _ClipboardWorker()
            _clipboard_worker.start()
        return _clipboard_worker


# --- Format registration cache ---------------------------------------------
#
# RegisterClipboardFormat returns the same integer ID for the same string
# for the lifetime of the user session, but the call is not free, so we
# cache. Standard format constants (CF_TEXT, CF_UNICODETEXT, CF_DIB, etc.)
# do not need registration; they have fixed IDs in the Win32 API.

_format_id_cache: dict[str, int] = {}


_owner_hwnd: int | None = None
_owner_hwnd_lock = threading.Lock()


def _get_clipboard_hwnd() -> int:
    """Return a process-owned HWND to associate with OpenClipboard.

    Critical: Per MSDN -- "If the application specifies a NULL window handle
    when opening the clipboard, EmptyClipboard succeeds but sets the
    clipboard owner to NULL. Note that this causes SetClipboardData to
    fail." But it goes deeper than that. SetClipboardData requires the
    *calling process* to be the clipboard owner. EmptyClipboard sets
    ownership to the window passed to OpenClipboard. So:

      - OpenClipboard(NULL) -> EmptyClipboard sets owner to NULL ->
        SetClipboardData fails for registered custom formats.
      - OpenClipboard(GetDesktopWindow()) -> EmptyClipboard sets owner to
        the desktop window (system-owned) -> our process is still NOT the
        owner -> SetClipboardData still fails.
      - OpenClipboard(<window-our-process-created>) -> EmptyClipboard sets
        owner to our window -> we ARE the owner -> SetClipboardData works
        for any format.

    Built-in formats (CF_UNICODETEXT) appear to survive both broken cases
    because their synthesis path (Windows auto-generates CF_TEXT,
    CF_OEMTEXT, CF_LOCALE from CF_UNICODETEXT regardless of caller
    ownership), bootstrapping the appearance of a successful write. The
    custom-format path has no synthesis fallback so silent failure is
    fully visible.

    Empirical chain that pinpointed this:

      - PR #146 verification (run-id mcp-clipboard-windows-e2e-pr146-
        verify-claude-code-2026-05-09T22:09:11Z): mc-005/mc-020
        (write_text image/svg+xml) silently no-op, mc-008 (write_multi
        with text/plain bootstrap) succeeds, mc-103 (direct PowerShell
        GetDataObject read after the same write_text) sees the SVG.
        PowerShell's Set-Clipboard / .NET Clipboard.SetDataObject use
        the OLE clipboard API (OleSetClipboard) which creates its own
        process-owned window internally.
      - First-pass fix attempt: pass GetDesktopWindow() to OpenClipboard.
        Verified on 2026-05-09 to NOT resolve the silent-no-op (same
        FAIL signature on mc-005/mc-009/mc-020). The desktop window is
        owned by the system, so we still aren't the clipboard owner.
      - Correct fix: create a message-only window owned by our process,
        use that HWND for OpenClipboard. Same pattern pyperclip uses for
        the equivalent reason. The "STATIC" window class is built-in
        (USER32) so no registration is needed. HWND_MESSAGE makes the
        window invisible and message-only -- never appears on screen,
        no message-loop responsibility for us.

    The window is created lazily on first call and reused for the lifetime
    of the process (cached in module-level `_owner_hwnd`). DestroyWindow on
    process exit is implicit -- Windows tears down windows owned by the
    exiting process automatically. The data we put on the clipboard before
    process exit persists because SetClipboardData(format, handle) takes
    ownership of the global memory handle; the clipboard owner being torn
    down doesn't invalidate the data.
    """
    global _owner_hwnd
    if _owner_hwnd is not None:
        return _owner_hwnd

    # Double-checked locking: clipboard.py dispatches the synchronous Win32
    # path through asyncio.to_thread, so two concurrent first-calls could
    # otherwise each race past the None-check and create two windows
    # (leaking one HWND per burst). Re-check inside the lock so only one
    # caller does the CreateWindowEx; the rest see the cached value.
    with _owner_hwnd_lock:
        if _owner_hwnd is not None:
            return _owner_hwnd

        import win32con  # type: ignore[import-not-found,import-untyped]
        import win32gui  # type: ignore[import-not-found,import-untyped]

        # CreateWindowEx with class="STATIC" (built-in USER32 class, no
        # registration needed) and parent=HWND_MESSAGE creates a message-only
        # window: invisible, top-level, and unable to receive UI input. The
        # other zero parameters mean default extended style, no menu, no
        # creation params. The handle returned is the HWND we use as the
        # clipboard owner for the rest of the process's lifetime.
        _owner_hwnd = int(
            win32gui.CreateWindowEx(
                0,  # extended style
                "STATIC",  # built-in class
                None,  # window name
                0,  # style
                0,  # x
                0,  # y
                0,  # width
                0,  # height
                win32con.HWND_MESSAGE,  # parent: message-only top-level
                0,  # menu
                0,  # hInstance
                None,  # creation params
            )
        )
        return _owner_hwnd


def _open_clipboard_with_retry(win32clipboard: Any, retries: int = 10, delay_ms: int = 50) -> None:
    """OpenClipboard fails with WindowsError when another process holds it.

    Mirrors the pattern Microsoft documents for SetDataObject's four-arg
    overload (10 retries x 100ms = 1s ceiling). We use 50ms here because
    the bottleneck this function fights is brief (~milliseconds) contention
    from clipboard inspectors / antivirus, not the multi-hundred-ms OLE
    propagation that the SetDataObject retry was originally introduced for.

    Always passes a real HWND (a process-owned message-only window from
    _get_clipboard_hwnd) to OpenClipboard so our process is the clipboard
    owner; SetClipboardData then succeeds for registered custom formats.
    See _get_clipboard_hwnd for the detailed MSDN background.
    """
    hwnd = _get_clipboard_hwnd()

    last_err: Exception | None = None
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard(hwnd)
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
        # On Linux / macOS pywin32 is not installed (the sys_platform marker
        # in pyproject.toml constrains it to Windows), so the module is
        # missing -> ImportError. On Windows pywin32 ships without type
        # stubs -- types-pywin32 exists on PyPI but adds an extra dep
        # purely for static analysis. Suppress both error codes here so
        # mypy is happy on Linux CI (import-not-found) and Windows CI
        # (import-untyped) without taking on the stub package.
        import win32clipboard  # type: ignore[import-not-found,import-untyped]
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
    # pywin32 has no type stubs in the configured set; cast to int so mypy
    # knows the cached value matches the declared return type.
    fmt_id: int = int(win32clipboard.RegisterClipboardFormat(name))
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
        # pywin32 has no type stubs in the configured set; cast to int.
        return int(win32clipboard.CF_UNICODETEXT)
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
    # Defensive last-resort: pywin32 has historically returned other shapes
    # (memoryview, int) for unusual custom formats on some Windows versions.
    # Coerce to str so the caller never sees a non-str return; log so a
    # future debugging session can spot the unexpected pywin32 shape rather
    # than the str() rendering masking it.
    logger.debug(
        "GetClipboardData returned unexpected type %s for format -- coercing via str()",
        type(data).__name__,
    )
    return str(data)


def _encode_for_format(fmt_id: int, content: str, win32clipboard: Any) -> bytes:
    """Encode a Python str into the byte representation Windows expects for
    the given clipboard format ID.

    CF_UNICODETEXT requires null-terminated UTF-16 LE; the trailing wchar
    NUL is part of the format contract per MSDN. Custom registered formats
    (HTML Format, Rich Text Format, image/svg+xml) take raw UTF-8 bytes;
    their internal end-of-data conventions are format-specific (CF_HTML
    has Version + offset headers; SVG/RTF terminate at the closing tag).
    """
    if fmt_id == win32clipboard.CF_UNICODETEXT:
        return content.encode("utf-16-le") + b"\x00\x00"
    return content.encode("utf-8")


# --- IDataObject implementation -------------------------------------------
#
# OleSetClipboard takes an IDataObject pointer. The MSDN-canonical pattern
# (mirrored by the pywin32 test suite in com/win32com/test/testClipboard.py)
# is to implement a small Python class declaring _com_interfaces_ /
# _public_methods_ and wrap it with win32com.server.util.wrap before passing
# to OleSetClipboard. OleFlushClipboard then walks the supported FORMATETC
# list, calls GetData for each, and renders the resulting HGLOBAL bytes
# onto the clipboard via SetClipboardData internally -- but going through
# OLE's internal window handle so cross-process ownership transitions work.


# IDataObject's full method set per MIDL. We implement the three methods
# OleFlushClipboard exercises (GetData, QueryGetData, EnumFormatEtc) and
# stub the rest as E_NOTIMPL -- read-side methods only matter if someone
# calls OleGetClipboard against us, which only happens during the brief
# OleSetClipboard..OleFlushClipboard window (and even then only for the
# format-enumeration path that goes through our EnumFormatEtc).
_IDATA_OBJECT_METHODS = (
    "GetData",
    "GetDataHere",
    "QueryGetData",
    "GetCanonicalFormatEtc",
    "SetData",
    "EnumFormatEtc",
    "DAdvise",
    "DUnadvise",
    "EnumDAdvise",
)


class _ClipboardDataObject:
    """Minimal IDataObject offering one or more (format_id, bytes) pairs.

    pywin32 introspects the class via _com_interfaces_ (the COM IID we
    implement) and _public_methods_ (the method names exposed through the
    COM vtable). Only GetData / QueryGetData / EnumFormatEtc carry real
    behavior; the other six raise E_NOTIMPL.
    """

    _com_interfaces_: ClassVar[list[Any]] = []  # filled in by _make_data_object()
    _public_methods_: ClassVar[tuple[str, ...]] = _IDATA_OBJECT_METHODS

    def __init__(self, payloads: dict[int, bytes]) -> None:
        import pythoncom  # type: ignore[import-not-found,import-untyped]

        self.payloads = payloads
        # FORMATETC tuple shape: (cfFormat, ptd, dwAspect, lindex, tymed).
        # We offer DVASPECT_CONTENT (the data itself, not an icon or
        # thumbnail) on TYMED_HGLOBAL (heap-allocated global memory --
        # what SetClipboardData uses under the hood). lindex=-1 means
        # "single-page" (no multi-page docs); ptd=None means no target
        # device.
        self.supported_fe = [
            (fmt_id, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)
            for fmt_id in payloads
        ]

    def GetData(self, fe: tuple[int, Any, int, int, int]) -> Any:
        import pythoncom  # type: ignore[import-not-found,import-untyped]
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        cf, _ptd, aspect, _lindex, tymed = fe
        if not (aspect & pythoncom.DVASPECT_CONTENT) or tymed != pythoncom.TYMED_HGLOBAL:
            raise COMException(hresult=winerror.DV_E_TYMED)
        if cf not in self.payloads:
            raise COMException(hresult=winerror.DV_E_FORMATETC)
        stg = pythoncom.STGMEDIUM()
        stg.set(pythoncom.TYMED_HGLOBAL, self.payloads[cf])
        return stg

    def QueryGetData(self, fe: tuple[int, Any, int, int, int]) -> None:
        import pythoncom  # type: ignore[import-not-found,import-untyped]
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        cf, _ptd, aspect, _lindex, tymed = fe
        if not (aspect & pythoncom.DVASPECT_CONTENT):
            raise COMException(hresult=winerror.DV_E_DVASPECT)
        if tymed != pythoncom.TYMED_HGLOBAL:
            raise COMException(hresult=winerror.DV_E_TYMED)
        if cf not in self.payloads:
            raise COMException(hresult=winerror.DV_E_FORMATETC)

    def EnumFormatEtc(self, direction: int) -> Any:
        import pythoncom  # type: ignore[import-not-found,import-untyped]
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )
        from win32com.server.util import (  # type: ignore[import-not-found,import-untyped]
            NewEnum,
        )

        if direction != pythoncom.DATADIR_GET:
            raise COMException(hresult=winerror.E_NOTIMPL)
        return NewEnum(self.supported_fe, iid=pythoncom.IID_IEnumFORMATETC)

    def GetDataHere(self, _fe: Any) -> Any:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.E_NOTIMPL)

    def GetCanonicalFormatEtc(self, _fe: Any) -> Any:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.E_NOTIMPL)

    def SetData(self, _fe: Any, _stg: Any, _release: int) -> None:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.E_NOTIMPL)

    def DAdvise(self, _fe: Any, _flags: int, _sink: Any) -> int:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.OLE_E_ADVISENOTSUPPORTED)

    def DUnadvise(self, _connection: int) -> None:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.OLE_E_ADVISENOTSUPPORTED)

    def EnumDAdvise(self) -> Any:
        import winerror  # type: ignore[import-not-found,import-untyped]
        from win32com.server.exception import (  # type: ignore[import-not-found,import-untyped]
            COMException,
        )

        raise COMException(hresult=winerror.OLE_E_ADVISENOTSUPPORTED)


def _make_data_object(payloads: dict[int, bytes]) -> Any:
    """Wrap a _ClipboardDataObject in a COM dispatcher and return the
    wrapped object ready for OleSetClipboard."""
    import pythoncom  # type: ignore[import-not-found,import-untyped]
    from win32com.server.util import wrap  # type: ignore[import-not-found,import-untyped]

    # Late-bind the interface IID on the class itself so the type-stub-free
    # pythoncom constants don't need to be available at import time.
    if not _ClipboardDataObject._com_interfaces_:
        _ClipboardDataObject._com_interfaces_ = [pythoncom.IID_IDataObject]
    return wrap(_ClipboardDataObject(payloads), iid=pythoncom.IID_IDataObject)


def _ole_set_clipboard_with_retry(
    pythoncom: Any, data_object: Any, retries: int = 10, delay_ms: int = 50
) -> None:
    """OleSetClipboard fails with CLIPBRD_E_CANT_OPEN under the same
    contention conditions raw OpenClipboard does (a clipboard inspector
    or antivirus briefly held the clipboard). Same retry budget as
    _open_clipboard_with_retry: 10 attempts x 50ms = 500ms ceiling.
    """
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            pythoncom.OleSetClipboard(data_object)
            return
        except Exception as exc:  # pywintypes.com_error on real Windows
            last_err = exc
            time.sleep(delay_ms / 1000.0)
    raise RuntimeError(
        f"OleSetClipboard failed after {retries} retries (delay={delay_ms}ms each); "
        f"another process is holding the clipboard. Last error: {last_err!r}"
    )


def _ole_write_on_worker(payloads: dict[int, bytes]) -> None:
    """The OLE write body that runs ON the dedicated worker thread.

    Lives here (rather than inline in _write_via_ole) so the worker can
    call it directly and unit tests can call it on a synthetic worker
    without invoking the thread-dispatch path.
    """
    import pythoncom  # type: ignore[import-not-found,import-untyped]

    data_object = _make_data_object(payloads)
    _ole_set_clipboard_with_retry(pythoncom, data_object)
    pythoncom.OleFlushClipboard()


def _write_via_ole(payloads: dict[int, bytes]) -> None:
    """Place all (format_id, bytes) pairs on the clipboard via the
    dedicated OLE worker thread.

    The worker owns one STA-initialized COM apartment for the process's
    lifetime; all OLE writes run there. This sidesteps the
    main-thread apartment instability observed on integration-windows CI
    (where pythoncom.CoInitializeEx and ctypes-direct CoInitializeEx
    both reported success but OleSetClipboard still raised
    CO_E_NOTINITIALIZED on the next line).
    """
    if not payloads:
        return
    worker = _get_clipboard_worker()
    future = worker.submit(_ole_write_on_worker, payloads)
    # Block on the worker's result. Exceptions from the worker thread
    # surface here via future.result().
    future.result()


def write_text(content: str, mime_type: str) -> None:
    """Replace the clipboard with a single (format, content) pair via
    OleSetClipboard + OleFlushClipboard.

    Atomic by construction. The OLE clipboard chain handles cross-process
    ownership transitions correctly -- a precondition for registered
    custom formats (image/svg+xml, HTML Format, Rich Text Format) per
    MSDN, where raw SetClipboardData was observed to silently no-op when
    the prior owner was a foreign process.
    """
    win32clipboard = _import_win32clipboard()
    fmt_id = _format_id_for_mime(win32clipboard, mime_type)
    encoded = _encode_for_format(fmt_id, content, win32clipboard)
    _write_via_ole({fmt_id: encoded})


def write_multi(formats: dict[str, str]) -> None:
    """Replace the clipboard with multiple (mime, content) pairs in ONE
    OleSetClipboard transaction.

    Used by `clipboard_copy_markdown` to put `text/html` and `text/plain`
    on the clipboard simultaneously, so paste targets that prefer one
    format over the other (Slack/Gmail vs vim/terminal) each get the
    representation they expect.

    Atomic by construction: the IDataObject we publish offers all formats
    at once, and OleFlushClipboard renders them in a single Win32
    transaction. No window during which the clipboard holds half the
    formats.
    """
    if not formats:
        return
    win32clipboard = _import_win32clipboard()

    # Resolve all format IDs and encode all payloads BEFORE handing off to
    # OLE, so encoding errors surface here rather than mid-transaction.
    payloads: dict[int, bytes] = {}
    for mime_type, content in formats.items():
        fmt_id = _format_id_for_mime(win32clipboard, mime_type)
        payloads[fmt_id] = _encode_for_format(fmt_id, content, win32clipboard)

    _write_via_ole(payloads)


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
        # pywin32 has no type stubs in the configured set; coerce to str.
        name = str(win32clipboard.GetClipboardFormatName(fmt))
        if name:
            return name
    except Exception as exc:
        # GetClipboardFormatName raises for built-in formats it does not
        # know about (CF_LOCALE, CF_OEMTEXT in some pywin32 versions, etc.).
        # Fall through to the numeric stringification but log so a future
        # debugging session can find why a particular format ID didn't
        # resolve to a name.
        logger.debug("GetClipboardFormatName(%d) failed: %s", fmt, exc)
    return f"Format{fmt}"
