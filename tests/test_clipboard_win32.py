"""Unit tests for the Win32 clipboard wrapper.

Exercises clipboard_win32.read_text / write_text / write_multi / list_formats
with `win32clipboard`, `pythoncom`, `win32com.server.util`,
`win32com.server.exception`, and `winerror` injected as MagicMocks via
sys.modules so the tests run on Linux CI (where pywin32 is not installed).
Real Windows-clipboard round-trips are covered by
tests/test_clipboard_win32_integration.py on the windows-latest runner.

The wrapper is small enough that the unit tests cover every branch:
- _import_win32clipboard cache hit / miss
- _register_format cache hit / miss
- _open_clipboard_with_retry retry budget exhaustion (read path)
- _format_id_for_mime for all four supported MIMEs + the unsupported case
- read_text for absent format vs str return vs bytes return
- _encode_for_format for CF_UNICODETEXT (UTF-16 LE + NUL) vs custom (UTF-8)
- write_text and write_multi via OleSetClipboard + OleFlushClipboard
- _ClipboardDataObject GetData / QueryGetData / EnumFormatEtc plus E_NOTIMPL stubs
- list_formats including standard-format-name lookup and custom fallback
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_win32clipboard() -> MagicMock:
    """Install MagicMocks for all the pywin32-shaped modules our wrapper
    imports lazily: win32clipboard, win32gui, win32con, pythoncom, winerror,
    win32com.server.util, win32com.server.exception. Each is injected via
    sys.modules so the wrapper's deferred imports resolve to the fake; the
    fakes are removed (or the prior value restored) on test teardown.

    Why so many fakes: writes go through OleSetClipboard + OleFlushClipboard
    via win32com.server.util.wrap on an IDataObject (_ClipboardDataObject)
    that raises COMException with winerror HRESULTs for unsupported
    FORMATETC shapes. None of those modules ship on Linux, where CI runs.
    Reads still use win32clipboard + win32gui + win32con directly."""
    fake = MagicMock(name="win32clipboard")
    # Standard format constants so _format_id_for_mime("text/plain") and
    # _format_name's standard-formats dict work without real pywin32.
    fake.CF_TEXT = 1
    fake.CF_BITMAP = 2
    fake.CF_METAFILEPICT = 3
    fake.CF_SYLK = 4
    fake.CF_DIF = 5
    fake.CF_TIFF = 6
    fake.CF_OEMTEXT = 7
    fake.CF_DIB = 8
    fake.CF_PALETTE = 9
    fake.CF_PENDATA = 10
    fake.CF_RIFF = 11
    fake.CF_WAVE = 12
    fake.CF_UNICODETEXT = 13
    fake.CF_ENHMETAFILE = 14
    fake.CF_HDROP = 15
    fake.CF_LOCALE = 16
    fake.CF_DIBV5 = 17

    prior = sys.modules.get("win32clipboard")
    sys.modules["win32clipboard"] = fake

    # _get_clipboard_hwnd creates a process-owned message-only window via
    # win32gui.CreateWindowEx(class="STATIC", parent=HWND_MESSAGE). Stub
    # win32gui and win32con so the tests can run on Linux without pywin32,
    # and assert that OpenClipboard receives the process-owned HWND (not
    # NULL, not the desktop, not anything system-owned). The HWND value
    # 0x10001 is arbitrary; the invariant is "non-NULL and from CreateWindowEx".
    fake_win32gui = MagicMock(name="win32gui")
    fake_win32gui.CreateWindowEx.return_value = 0x10001
    prior_win32gui = sys.modules.get("win32gui")
    sys.modules["win32gui"] = fake_win32gui

    fake_win32con = MagicMock(name="win32con")
    fake_win32con.HWND_MESSAGE = -3  # the actual Win32 constant, for fidelity
    prior_win32con = sys.modules.get("win32con")
    sys.modules["win32con"] = fake_win32con

    # pythoncom: OLE clipboard ops + COM init + IDataObject IID + FORMATETC
    # / STGMEDIUM / DVASPECT_CONTENT / TYMED_HGLOBAL constants.
    fake_pythoncom = MagicMock(name="pythoncom")
    fake_pythoncom.COINIT_APARTMENTTHREADED = 0x2
    fake_pythoncom.IID_IDataObject = "IID_IDataObject"
    fake_pythoncom.IID_IEnumFORMATETC = "IID_IEnumFORMATETC"
    fake_pythoncom.DVASPECT_CONTENT = 1
    fake_pythoncom.TYMED_HGLOBAL = 1
    fake_pythoncom.DATADIR_GET = 1
    fake_pythoncom.DATADIR_SET = 2
    # STGMEDIUM is constructed empty then .set(tymed, payload). Tests
    # inspect the captured (tymed, payload) pair via the .set call on
    # the returned mock.
    fake_pythoncom.STGMEDIUM = MagicMock(name="STGMEDIUM")
    prior_pythoncom = sys.modules.get("pythoncom")
    sys.modules["pythoncom"] = fake_pythoncom

    # winerror: HRESULT constants the IDataObject methods raise for
    # unsupported FORMATETC shapes / unimplemented methods.
    fake_winerror = MagicMock(name="winerror")
    fake_winerror.DV_E_FORMATETC = -2147221404  # 0x80040064
    fake_winerror.DV_E_TYMED = -2147221399  # 0x80040069
    fake_winerror.DV_E_DVASPECT = -2147221397  # 0x8004006B
    fake_winerror.E_NOTIMPL = -2147467263  # 0x80004001
    fake_winerror.OLE_E_ADVISENOTSUPPORTED = -2147221501  # 0x80040003
    prior_winerror = sys.modules.get("winerror")
    sys.modules["winerror"] = fake_winerror

    # win32com.server.util.wrap and NewEnum: wrap is what bridges a Python
    # object implementing _com_interfaces_ / _public_methods_ into a COM
    # IDispatch. NewEnum builds an IEnumFORMATETC over a Python iterable.
    fake_win32com = MagicMock(name="win32com")
    fake_win32com_server = MagicMock(name="win32com.server")
    fake_win32com_server_util = MagicMock(name="win32com.server.util")
    fake_win32com_server_util.wrap = MagicMock(name="wrap")
    fake_win32com_server_util.NewEnum = MagicMock(name="NewEnum")
    fake_win32com_server_exception = MagicMock(name="win32com.server.exception")

    # COMException stored on the fake module so the wrapper's `from ...
    # import COMException` resolves and so tests can assert raises against
    # the same class. A concrete subclass of Exception is what the wrapper
    # actually catches via try/except, so we use a real class here.
    class _FakeCOMException(Exception):
        def __init__(self, hresult: int | None = None, *args: object, **kwargs: object) -> None:
            super().__init__(f"COMException(hresult={hresult})")
            self.hresult = hresult

    fake_win32com_server_exception.COMException = _FakeCOMException

    prior_win32com = sys.modules.get("win32com")
    prior_win32com_server = sys.modules.get("win32com.server")
    prior_win32com_server_util = sys.modules.get("win32com.server.util")
    prior_win32com_server_exception = sys.modules.get("win32com.server.exception")
    sys.modules["win32com"] = fake_win32com
    sys.modules["win32com.server"] = fake_win32com_server
    sys.modules["win32com.server.util"] = fake_win32com_server_util
    sys.modules["win32com.server.exception"] = fake_win32com_server_exception

    # ctypes.windll only exists on Windows; the wrapper's _ensure_com_init
    # accesses ole32.CoInitializeEx via ctypes.windll.ole32 to bypass
    # pywin32's silently-no-op'ing wrapper. Inject a MagicMock for the
    # tests; teardown restores the prior value.
    import ctypes as _ctypes

    fake_ole32 = MagicMock(name="ole32")
    fake_ole32.OleInitialize.return_value = 0  # S_OK
    fake_windll = MagicMock(name="windll")
    fake_windll.ole32 = fake_ole32
    prior_windll = getattr(_ctypes, "windll", None)
    _ctypes.windll = fake_windll  # type: ignore[attr-defined]

    # The real module caches the HWND and the OLE worker thread for the
    # lifetime of the process. Reset between tests so each test starts
    # fresh and CreateWindowEx / worker-start call counts are deterministic.
    from mcp_clipboard import clipboard_win32 as _mod

    _mod._owner_hwnd = None
    prior_worker = _mod._clipboard_worker
    # Inject a synchronous fake worker so write_text / write_multi tests
    # exercise the OLE write body on the calling thread (no real thread
    # spawn, no actual COM init -- everything is mocked through the
    # fake pythoncom). Tests that exercise the real _ClipboardWorker do
    # so explicitly by clearing _mod._clipboard_worker first.
    from concurrent.futures import Future as _Future

    class _SynchronousWorker:
        def __init__(self) -> None:
            self.submitted: list[tuple[Any, tuple[Any, ...]]] = []

        def submit(self, fn: Any, *args: Any) -> _Future:
            self.submitted.append((fn, args))
            f: _Future = _Future()
            try:
                f.set_result(fn(*args))
            except BaseException as exc:
                f.set_exception(exc)
            return f

    _mod._clipboard_worker = _SynchronousWorker()  # type: ignore[assignment]
    # The class-level _com_interfaces_ is populated lazily on first
    # _make_data_object call; clear so tests see a fresh init.
    _mod._ClipboardDataObject._com_interfaces_ = []

    try:
        yield fake
    finally:
        if prior is None:
            sys.modules.pop("win32clipboard", None)
        else:
            sys.modules["win32clipboard"] = prior
        if prior_win32gui is None:
            sys.modules.pop("win32gui", None)
        else:
            sys.modules["win32gui"] = prior_win32gui
        if prior_win32con is None:
            sys.modules.pop("win32con", None)
        else:
            sys.modules["win32con"] = prior_win32con
        if prior_pythoncom is None:
            sys.modules.pop("pythoncom", None)
        else:
            sys.modules["pythoncom"] = prior_pythoncom
        if prior_winerror is None:
            sys.modules.pop("winerror", None)
        else:
            sys.modules["winerror"] = prior_winerror
        if prior_win32com is None:
            sys.modules.pop("win32com", None)
        else:
            sys.modules["win32com"] = prior_win32com
        if prior_win32com_server is None:
            sys.modules.pop("win32com.server", None)
        else:
            sys.modules["win32com.server"] = prior_win32com_server
        if prior_win32com_server_util is None:
            sys.modules.pop("win32com.server.util", None)
        else:
            sys.modules["win32com.server.util"] = prior_win32com_server_util
        if prior_win32com_server_exception is None:
            sys.modules.pop("win32com.server.exception", None)
        else:
            sys.modules["win32com.server.exception"] = prior_win32com_server_exception
        _mod._owner_hwnd = None
        _mod._clipboard_worker = prior_worker
        _mod._ClipboardDataObject._com_interfaces_ = []
        if prior_windll is None:
            # ctypes.windll didn't exist before -- delete the attr we
            # added rather than leaving a MagicMock dangling.
            import contextlib

            with contextlib.suppress(AttributeError):
                del _ctypes.windll  # type: ignore[attr-defined]
        else:
            _ctypes.windll = prior_windll  # type: ignore[attr-defined]


@pytest.fixture
def clipboard_win32(fake_win32clipboard):
    """Import the wrapper with the fake win32clipboard already in sys.modules,
    and clear the registered-format cache between tests so RegisterClipboardFormat
    call counts are deterministic."""
    from mcp_clipboard import clipboard_win32 as mod

    mod._format_id_cache.clear()
    return mod


# --- _import_win32clipboard ------------------------------------------------


def test_import_win32clipboard_returns_module_when_available(clipboard_win32, fake_win32clipboard):
    """_import_win32clipboard returns the module from sys.modules when
    pywin32 is installed."""
    assert clipboard_win32._import_win32clipboard() is fake_win32clipboard


def test_import_win32clipboard_raises_clear_error_on_non_windows():
    """When pywin32 is not installed (Linux / macOS) the import raises
    ImportError with a message naming the platform constraint."""
    # Temporarily remove the fake from sys.modules and patch the import to
    # simulate the real pywin32-not-installed condition.
    with patch.dict(sys.modules, {"win32clipboard": None}):
        from mcp_clipboard import clipboard_win32 as mod

        with pytest.raises(ImportError, match="pywin32"):
            mod._import_win32clipboard()


# --- _register_format ------------------------------------------------------


def test_register_format_caches_per_name(clipboard_win32, fake_win32clipboard):
    """_register_format caches the result of RegisterClipboardFormat per
    name so we don't pay the Win32 round-trip more than once per session."""
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC123

    fmt_id = clipboard_win32._register_format("HTML Format")
    fmt_id_again = clipboard_win32._register_format("HTML Format")

    assert fmt_id == 0xC123
    assert fmt_id_again == 0xC123
    fake_win32clipboard.RegisterClipboardFormat.assert_called_once_with("HTML Format")


def test_register_format_separate_names_get_separate_ids(clipboard_win32, fake_win32clipboard):
    """Different format names get different cache entries and separate
    RegisterClipboardFormat calls."""
    ids = iter([0xC100, 0xC101, 0xC102])
    fake_win32clipboard.RegisterClipboardFormat.side_effect = lambda _: next(ids)

    a = clipboard_win32._register_format("HTML Format")
    b = clipboard_win32._register_format("Rich Text Format")
    c = clipboard_win32._register_format("image/svg+xml")

    assert {a, b, c} == {0xC100, 0xC101, 0xC102}
    assert fake_win32clipboard.RegisterClipboardFormat.call_count == 3


# --- _open_clipboard_with_retry --------------------------------------------


def test_open_clipboard_with_retry_succeeds_on_first_attempt(clipboard_win32, fake_win32clipboard):
    fake_win32clipboard.OpenClipboard.return_value = None  # success

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    fake_win32clipboard.OpenClipboard.assert_called_once()


def test_open_clipboard_passes_process_owned_hwnd(clipboard_win32, fake_win32clipboard):
    """Critical regression guard: OpenClipboard must be called with a process-
    owned HWND created via CreateWindowEx, not NULL and not a system-owned
    window like GetDesktopWindow().

    SetClipboardData requires the calling process to be the clipboard owner.
    EmptyClipboard sets ownership to whatever window was passed to OpenClipboard.
    NULL or system-owned windows leave us not-the-owner and SetClipboardData
    silently fails for registered custom formats -- the exact bug class that
    produced the SVG silent-no-op symptoms in mc-005 / mc-009 / mc-020 of the
    PR #146 verification runs before this fix.

    The fixture stubs CreateWindowEx to return 0x10001 (representing a
    message-only "STATIC" window owned by our process); OpenClipboard MUST
    receive that exact value."""
    fake_win32clipboard.OpenClipboard.return_value = None

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    fake_win32clipboard.OpenClipboard.assert_called_once_with(0x10001)


def test_open_clipboard_creates_message_only_window(clipboard_win32, fake_win32clipboard):
    """The HWND we pass to OpenClipboard comes from CreateWindowEx with
    class='STATIC' (built-in USER32 class, no registration needed) and
    parent=HWND_MESSAGE (top-level message-only window, never visible).
    This is the same pattern pyperclip uses, and matches what .NET's
    Clipboard.SetDataObject and PowerShell's Set-Clipboard do internally
    via the OLE API."""
    import sys as _sys

    fake_win32clipboard.OpenClipboard.return_value = None

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    fake_win32gui = _sys.modules["win32gui"]
    fake_win32con = _sys.modules["win32con"]
    fake_win32gui.CreateWindowEx.assert_called_once()
    args = fake_win32gui.CreateWindowEx.call_args[0]
    # Positional args: (extStyle, className, windowName, style, x, y, w, h,
    #                   parent, menu, hInstance, lpParam)
    assert args[1] == "STATIC", f"window class must be 'STATIC', got {args[1]!r}"
    assert args[8] == fake_win32con.HWND_MESSAGE, (
        f"parent must be HWND_MESSAGE for a message-only window, got {args[8]!r}"
    )


def test_open_clipboard_caches_owner_window_across_calls(clipboard_win32, fake_win32clipboard):
    """The owner window is created lazily on first call and cached for the
    process lifetime. Subsequent OpenClipboard calls reuse the same HWND
    rather than spawning a new window each time -- otherwise high-frequency
    clipboard ops would leak windows."""
    import sys as _sys

    fake_win32clipboard.OpenClipboard.return_value = None
    fake_win32gui = _sys.modules["win32gui"]

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)
    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)
    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    # CreateWindowEx fires once even though _open_clipboard_with_retry was
    # called three times.
    assert fake_win32gui.CreateWindowEx.call_count == 1
    # OpenClipboard fires three times with the same cached HWND.
    assert fake_win32clipboard.OpenClipboard.call_count == 3
    for call in fake_win32clipboard.OpenClipboard.call_args_list:
        assert call.args == (0x10001,)


def test_get_clipboard_hwnd_inner_lock_returns_cached_hwnd(clipboard_win32, fake_win32clipboard):
    """Double-checked locking has TWO None-checks: one before the lock
    (lock-free fast path) and one inside the lock (handles the race where
    a second caller acquired the lock just as the first finished creating
    the window). Swap the module-level lock for a fake whose __enter__
    pre-populates _owner_hwnd, simulating the race: the inner None-check
    then returns the cached HWND without falling into CreateWindowEx."""
    import sys as _sys

    fake_win32gui = _sys.modules["win32gui"]
    sentinel_hwnd = 0xDEADBEEF

    class _RacingLock:
        """Stand-in for threading.Lock whose __enter__ populates
        _owner_hwnd before yielding -- simulates a parallel thread having
        won the create race while this caller waited on the lock."""

        def __enter__(self) -> _RacingLock:
            clipboard_win32._owner_hwnd = sentinel_hwnd
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    with patch.object(clipboard_win32, "_owner_hwnd_lock", _RacingLock()):
        result = clipboard_win32._get_clipboard_hwnd()

    assert result == sentinel_hwnd
    fake_win32gui.CreateWindowEx.assert_not_called()


def test_get_clipboard_hwnd_is_thread_safe(clipboard_win32, fake_win32clipboard):
    """Concurrent first-callers must not leak HWNDs. clipboard.py dispatches
    the synchronous Win32 path through asyncio.to_thread, so a burst of
    concurrent first-calls into _get_clipboard_hwnd is reachable. Without
    the double-checked lock both callers would race past the None-check and
    each invoke CreateWindowEx, stranding one window per burst.
    """
    import sys as _sys
    import threading as _threading

    fake_win32gui = _sys.modules["win32gui"]

    n_threads = 32
    barrier = _threading.Barrier(n_threads)
    hwnds: list[int] = []
    hwnds_lock = _threading.Lock()

    def race():
        barrier.wait()
        h = clipboard_win32._get_clipboard_hwnd()
        with hwnds_lock:
            hwnds.append(h)

    threads = [_threading.Thread(target=race) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake_win32gui.CreateWindowEx.call_count == 1, (
        f"CreateWindowEx must be called exactly once across {n_threads} concurrent "
        f"first-callers; got {fake_win32gui.CreateWindowEx.call_count}"
    )
    assert len(hwnds) == n_threads
    assert set(hwnds) == {0x10001}, f"all callers must see the same cached HWND; got {set(hwnds)}"


def test_open_clipboard_with_retry_succeeds_after_transient_failure(
    clipboard_win32, fake_win32clipboard
):
    """Two failures, then success -- the retry budget covers transient
    contention from clipboard inspectors / antivirus."""
    attempts = iter([RuntimeError("locked"), RuntimeError("locked"), None])

    def open_side_effect(_hwnd):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    fake_win32clipboard.OpenClipboard.side_effect = open_side_effect

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=5, delay_ms=0)

    assert fake_win32clipboard.OpenClipboard.call_count == 3


def test_open_clipboard_with_retry_raises_after_budget_exhausted(
    clipboard_win32, fake_win32clipboard
):
    """If every retry fails, RuntimeError surfaces with the last underlying
    error included so the caller knows what went wrong."""
    fake_win32clipboard.OpenClipboard.side_effect = RuntimeError("locked")

    with pytest.raises(RuntimeError, match="OpenClipboard failed after 3 retries"):
        clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    assert fake_win32clipboard.OpenClipboard.call_count == 3


# --- _format_id_for_mime ---------------------------------------------------


def test_format_id_for_mime_text_plain_uses_cf_unicodetext(clipboard_win32, fake_win32clipboard):
    """text/plain maps to CF_UNICODETEXT directly -- no RegisterClipboardFormat
    call, so non-ASCII codepoints round-trip natively in UTF-16."""
    fmt_id = clipboard_win32._format_id_for_mime(fake_win32clipboard, "text/plain")
    assert fmt_id == fake_win32clipboard.CF_UNICODETEXT
    fake_win32clipboard.RegisterClipboardFormat.assert_not_called()


@pytest.mark.parametrize(
    "mime_type,expected_name",
    [
        ("text/html", "HTML Format"),
        ("text/rtf", "Rich Text Format"),
        ("image/svg+xml", "image/svg+xml"),
    ],
)
def test_format_id_for_mime_registered_formats(
    clipboard_win32, fake_win32clipboard, mime_type, expected_name
):
    """Each registered MIME asks RegisterClipboardFormat for its conventional
    Win32 string name (HTML Format, Rich Text Format, image/svg+xml)."""
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC200

    clipboard_win32._format_id_for_mime(fake_win32clipboard, mime_type)

    fake_win32clipboard.RegisterClipboardFormat.assert_called_once_with(expected_name)


def test_format_id_for_mime_unsupported_raises(clipboard_win32, fake_win32clipboard):
    with pytest.raises(ValueError, match="Unsupported MIME type"):
        clipboard_win32._format_id_for_mime(fake_win32clipboard, "application/octet-stream")


# --- read_text -------------------------------------------------------------


def test_read_text_returns_empty_string_when_format_absent(clipboard_win32, fake_win32clipboard):
    """If IsClipboardFormatAvailable returns falsy, read_text returns "" --
    the absence-of-format path read_clipboard_raw relies on."""
    fake_win32clipboard.IsClipboardFormatAvailable.return_value = False

    result = clipboard_win32.read_text("text/plain")

    assert result == ""
    # Clipboard still opens / closes even on absent-format reads.
    fake_win32clipboard.OpenClipboard.assert_called_once()
    fake_win32clipboard.CloseClipboard.assert_called_once()
    fake_win32clipboard.GetClipboardData.assert_not_called()


def test_read_text_returns_str_for_unicodetext(clipboard_win32, fake_win32clipboard):
    """CF_UNICODETEXT comes back as a Python str directly via pywin32's
    Unicode-aware GetClipboardData wrapper."""
    fake_win32clipboard.IsClipboardFormatAvailable.return_value = True
    fake_win32clipboard.GetClipboardData.return_value = "hello — world"

    result = clipboard_win32.read_text("text/plain")

    assert result == "hello — world"


def test_read_text_decodes_utf8_bytes_for_registered_formats(clipboard_win32, fake_win32clipboard):
    """Registered custom formats (HTML Format, image/svg+xml, etc.) come
    back as bytes; read_text decodes UTF-8 with errors='replace'."""
    fake_win32clipboard.IsClipboardFormatAvailable.return_value = True
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC300
    fake_win32clipboard.GetClipboardData.return_value = b"<svg>\xe2\x80\x94</svg>"

    result = clipboard_win32.read_text("image/svg+xml")

    assert result == "<svg>—</svg>"


def test_read_text_closes_clipboard_on_exception(clipboard_win32, fake_win32clipboard):
    """If GetClipboardData raises, the clipboard is still released so the
    next caller is not blocked by a stuck OpenClipboard."""
    fake_win32clipboard.IsClipboardFormatAvailable.return_value = True
    fake_win32clipboard.GetClipboardData.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        clipboard_win32.read_text("text/plain")

    fake_win32clipboard.CloseClipboard.assert_called_once()


def test_read_text_str_fallback_for_unexpected_return_type(clipboard_win32, fake_win32clipboard):
    """Defensive: pywin32 historically returned non-str / non-bytes values
    for some custom formats (memoryview, ints). read_text str()-coerces
    so the caller always gets a string back. Covers the final fallback
    branch in read_text after the str / bytes type checks."""
    fake_win32clipboard.IsClipboardFormatAvailable.return_value = True
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC700
    # Return a memoryview -- not str, not bytes, not bytearray -- so the
    # str / bytes type checks both miss and the fallback runs.
    fake_win32clipboard.GetClipboardData.return_value = memoryview(b"raw")

    result = clipboard_win32.read_text("image/svg+xml")

    # str(memoryview(b"raw")) renders as "<memory at 0x...>", which is
    # what the fallback produces -- the test's intent is to prove the
    # fallback executes, not to assert on the rendered representation.
    assert isinstance(result, str)
    assert "memory" in result


# --- _ole32_initialize -----------------------------------------------


def test_ole32_initialize_calls_ctypes_ole32_oleinitialize(clipboard_win32):
    """ole32.OleInitialize -- not bare CoInitializeEx -- is what
    OleSetClipboard requires per MSDN: 'Before calling this function,
    you must initialize the OLE library by calling OleInitialize.'
    Bare CoInitializeEx sets up the COM apartment but does NOT enable
    OLE clipboard support, which is why integration-windows CI on
    commits d3d7372 / 3904fef / 0a0f933 / 0966ef7 all failed with
    OleSetClipboard raising CO_E_NOTINITIALIZED."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = 0  # S_OK

    clipboard_win32._ole32_initialize()

    # OleInitialize takes a single LPVOID reserved param (always NULL).
    fake_ole32.OleInitialize.assert_called_once_with(None)


def test_ole32_initialize_accepts_s_false_and_rpc_e_changed_mode(clipboard_win32):
    """S_FALSE (1, same-mode re-init) and RPC_E_CHANGED_MODE
    (-2147417850, different model already active) are both accepted
    without raising."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]

    # S_FALSE (1): same-mode re-init, no-op success.
    fake_ole32.OleInitialize.return_value = 1
    clipboard_win32._ole32_initialize()

    # RPC_E_CHANGED_MODE: previously inited to different model, accept.
    fake_ole32.OleInitialize.return_value = -2147417850
    clipboard_win32._ole32_initialize()


def test_ole32_initialize_raises_on_other_failed_hresults(clipboard_win32):
    """Any negative HRESULT other than RPC_E_CHANGED_MODE raises OSError
    so genuine init failures aren't masked."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = -2147221015  # CO_E_INITONLYONCE

    with pytest.raises(OSError, match="OleInitialize"):
        clipboard_win32._ole32_initialize()


# --- _ClipboardWorker ------------------------------------------------------


def test_clipboard_worker_inits_com_then_runs_submitted_callable(clipboard_win32):
    """The worker thread inits ole32 once on start, then services
    queued callables. Tests run a real thread but mock ole32 + pythoncom."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = 0  # S_OK

    worker = clipboard_win32._ClipboardWorker()
    worker.start()
    try:
        future = worker.submit(lambda x: x * 2, 21)
        assert future.result(timeout=2.0) == 42
        # ole32.OleInitialize fired once on the worker's start (the full
        # OLE setup, not just bare CoInitializeEx). Subsequent submits
        # don't re-init.
        assert fake_ole32.OleInitialize.call_count == 1
        assert fake_ole32.OleInitialize.call_args.args == (None,)
    finally:
        worker._queue.put(None)  # sentinel shutdown
        worker.join(timeout=2.0)


def test_clipboard_worker_propagates_exceptions_from_submitted_callable(clipboard_win32):
    """An exception inside a worker-thread callable surfaces through the
    Future to the caller."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = 0

    worker = clipboard_win32._ClipboardWorker()
    worker.start()
    try:

        def boom():
            raise RuntimeError("boom")

        future = worker.submit(boom)
        with pytest.raises(RuntimeError, match="boom"):
            future.result(timeout=2.0)
    finally:
        worker._queue.put(None)
        worker.join(timeout=2.0)


def test_clipboard_worker_init_failure_surfaces_on_submit(clipboard_win32):
    """If OleInitialize fails at worker start, submit() returns a
    pre-resolved Future carrying the init error -- callers see the real
    failure rather than hanging on a dead worker."""
    import ctypes as _ctypes

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = -2147221015  # CO_E_INITONLYONCE

    worker = clipboard_win32._ClipboardWorker()
    worker.start()
    try:
        future = worker.submit(lambda: None)
        with pytest.raises(OSError, match="OleInitialize"):
            future.result(timeout=2.0)
    finally:
        worker.join(timeout=2.0)  # thread already exited from init failure


# --- _get_clipboard_worker -------------------------------------------------


def test_get_clipboard_worker_starts_once_and_caches(clipboard_win32):
    """The worker is lazy-started on first call and cached. Double-checked
    locking guards against concurrent first-callers via asyncio.to_thread
    spawning multiple workers."""
    import ctypes as _ctypes
    import threading as _threading

    fake_ole32 = _ctypes.windll.ole32  # type: ignore[attr-defined]
    fake_ole32.OleInitialize.return_value = 0

    # Clear the cached worker the fixture installed; we want to exercise
    # the real lazy-start path.
    clipboard_win32._clipboard_worker = None

    n_threads = 16
    barrier = _threading.Barrier(n_threads)
    workers: list[Any] = []
    workers_lock = _threading.Lock()

    def race():
        barrier.wait()
        w = clipboard_win32._get_clipboard_worker()
        with workers_lock:
            workers.append(w)

    threads = [_threading.Thread(target=race) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        # All threads see the same worker instance.
        assert all(w is workers[0] for w in workers)
        assert workers[0] is clipboard_win32._clipboard_worker
    finally:
        clipboard_win32._clipboard_worker._queue.put(None)
        clipboard_win32._clipboard_worker.join(timeout=2.0)
        clipboard_win32._clipboard_worker = None


# --- _encode_for_format ----------------------------------------------------


def test_encode_for_format_cf_unicodetext_is_utf16le_null_terminated(
    clipboard_win32, fake_win32clipboard
):
    """CF_UNICODETEXT requires null-terminated UTF-16 LE per MSDN. Under
    raw SetClipboardData pywin32's str overload added the NUL for us;
    under OleSetClipboard we go through STGMEDIUM HGLOBAL which copies
    bytes verbatim, so we must encode + terminate ourselves."""
    encoded = clipboard_win32._encode_for_format(
        fake_win32clipboard.CF_UNICODETEXT, "hi —", fake_win32clipboard
    )

    assert encoded == "hi —".encode("utf-16-le") + b"\x00\x00"


def test_encode_for_format_custom_format_is_utf8(clipboard_win32, fake_win32clipboard):
    """Registered custom formats (HTML Format, Rich Text Format,
    image/svg+xml) take raw UTF-8 bytes. No null terminator: their
    end-of-data conventions are format-internal."""
    encoded = clipboard_win32._encode_for_format(0xC100, "<svg>—</svg>", fake_win32clipboard)

    assert encoded == "<svg>—</svg>".encode()


# --- _ClipboardDataObject --------------------------------------------------


def _make_fe(cf: int, aspect: int = 1, tymed: int = 1):
    """Build a FORMATETC tuple in the shape (cf, ptd, aspect, lindex, tymed)
    that OleFlushClipboard / OleGetClipboard pass to our IDataObject."""
    return (cf, None, aspect, -1, tymed)


def test_clipboard_data_object_getdata_returns_stgmedium_for_known_format(
    clipboard_win32, fake_win32clipboard
):
    """GetData for a (cf, DVASPECT_CONTENT, TYMED_HGLOBAL) shape we
    advertise returns an STGMEDIUM with our payload bytes."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    stg_instance = MagicMock(name="STGMEDIUM_instance")
    fake_pythoncom.STGMEDIUM.return_value = stg_instance

    do = clipboard_win32._ClipboardDataObject({0xC700: b"<svg/>"})
    result = do.GetData(_make_fe(0xC700))

    assert result is stg_instance
    stg_instance.set.assert_called_once_with(fake_pythoncom.TYMED_HGLOBAL, b"<svg/>")


def test_clipboard_data_object_getdata_unknown_format_raises_dv_e_formatetc(
    clipboard_win32, fake_win32clipboard
):
    """A FORMATETC we don't advertise -> DV_E_FORMATETC, the documented
    HRESULT for "this object cannot provide that format."""
    import sys as _sys

    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC700: b"<svg/>"})
    with pytest.raises(COMException) as excinfo:
        do.GetData(_make_fe(0xC701))
    assert excinfo.value.hresult == fake_winerror.DV_E_FORMATETC


def test_clipboard_data_object_getdata_wrong_tymed_raises_dv_e_tymed(
    clipboard_win32, fake_win32clipboard
):
    """We only offer TYMED_HGLOBAL; any other tymed -> DV_E_TYMED."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC700: b"<svg/>"})
    with pytest.raises(COMException) as excinfo:
        # Wrong tymed (e.g. TYMED_ISTREAM=4) -> DV_E_TYMED.
        do.GetData(_make_fe(0xC700, aspect=fake_pythoncom.DVASPECT_CONTENT, tymed=4))
    assert excinfo.value.hresult == fake_winerror.DV_E_TYMED


def test_clipboard_data_object_querygetdata_known_format_returns_none(
    clipboard_win32, fake_win32clipboard
):
    """QueryGetData returns None for a supported FORMATETC -- the COM
    convention for "yes, we can render this" without producing the data."""
    do = clipboard_win32._ClipboardDataObject({0xC800: b"x"})

    # Should not raise.
    do.QueryGetData(_make_fe(0xC800))


def test_clipboard_data_object_querygetdata_unknown_format_raises(
    clipboard_win32, fake_win32clipboard
):
    import sys as _sys

    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC800: b"x"})
    with pytest.raises(COMException) as excinfo:
        do.QueryGetData(_make_fe(0xC801))
    assert excinfo.value.hresult == fake_winerror.DV_E_FORMATETC


def test_clipboard_data_object_querygetdata_wrong_aspect_raises_dv_e_dvaspect(
    clipboard_win32, fake_win32clipboard
):
    """QueryGetData with aspect=0 (no DVASPECT_CONTENT bit) -> DV_E_DVASPECT,
    the documented HRESULT for 'wrong aspect for this data source'."""
    import sys as _sys

    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC800: b"x"})
    with pytest.raises(COMException) as excinfo:
        # aspect=0 -> aspect & DVASPECT_CONTENT == 0 -> DV_E_DVASPECT branch.
        do.QueryGetData(_make_fe(0xC800, aspect=0))
    assert excinfo.value.hresult == fake_winerror.DV_E_DVASPECT


def test_clipboard_data_object_querygetdata_wrong_tymed_raises_dv_e_tymed(
    clipboard_win32, fake_win32clipboard
):
    """QueryGetData with tymed != TYMED_HGLOBAL -> DV_E_TYMED. Distinct
    from GetData's DV_E_TYMED check because QueryGetData also checks
    aspect first; assert the tymed-specific branch when aspect is OK."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC800: b"x"})
    with pytest.raises(COMException) as excinfo:
        # aspect=DVASPECT_CONTENT (passes), tymed=4 (TYMED_ISTREAM, wrong).
        do.QueryGetData(_make_fe(0xC800, aspect=fake_pythoncom.DVASPECT_CONTENT, tymed=4))
    assert excinfo.value.hresult == fake_winerror.DV_E_TYMED


def test_clipboard_data_object_enumformatetc_get_direction_returns_enum(
    clipboard_win32, fake_win32clipboard
):
    """EnumFormatEtc with DATADIR_GET delegates to NewEnum and returns the
    enumerator over our supported FORMATETC list."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    new_enum_result = MagicMock(name="enum")
    fake_new_enum = _sys.modules["win32com.server.util"].NewEnum
    fake_new_enum.return_value = new_enum_result

    do = clipboard_win32._ClipboardDataObject({0xC900: b"a", 0xC901: b"b"})
    result = do.EnumFormatEtc(fake_pythoncom.DATADIR_GET)

    assert result is new_enum_result
    fake_new_enum.assert_called_once()
    call_args = fake_new_enum.call_args
    # First positional arg: the list of FORMATETC tuples; iid kwarg: enum IID.
    assert call_args.args[0] == do.supported_fe
    assert call_args.kwargs["iid"] == fake_pythoncom.IID_IEnumFORMATETC


def test_clipboard_data_object_enumformatetc_set_direction_raises_not_impl(
    clipboard_win32, fake_win32clipboard
):
    """We're a read-only data source; DATADIR_SET is not supported."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_winerror = _sys.modules["winerror"]
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xC900: b"a"})
    with pytest.raises(COMException) as excinfo:
        do.EnumFormatEtc(fake_pythoncom.DATADIR_SET)
    assert excinfo.value.hresult == fake_winerror.E_NOTIMPL


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("GetDataHere", (None,)),
        ("GetCanonicalFormatEtc", (None,)),
        ("SetData", (None, None, 0)),
        ("DAdvise", (None, 0, None)),
        ("DUnadvise", (0,)),
        ("EnumDAdvise", ()),
    ],
)
def test_clipboard_data_object_unimplemented_methods_raise(
    clipboard_win32, fake_win32clipboard, method_name, args
):
    """All read-side / advise-side methods we don't implement raise
    COMException with E_NOTIMPL or OLE_E_ADVISENOTSUPPORTED, so OLE
    receives a proper HRESULT instead of a TypeError surfacing from Python."""
    from win32com.server.exception import COMException

    do = clipboard_win32._ClipboardDataObject({0xCA00: b"x"})
    method = getattr(do, method_name)

    with pytest.raises(COMException):
        method(*args)


# --- _make_data_object -----------------------------------------------------


def test_make_data_object_wraps_and_returns_wrapped(clipboard_win32, fake_win32clipboard):
    """_make_data_object calls win32com.server.util.wrap with our
    _ClipboardDataObject + IID_IDataObject and returns the wrapper."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_wrap = _sys.modules["win32com.server.util"].wrap
    wrapped = MagicMock(name="wrapped_data_object")
    fake_wrap.return_value = wrapped

    result = clipboard_win32._make_data_object({0xCB00: b"hello"})

    assert result is wrapped
    fake_wrap.assert_called_once()
    args = fake_wrap.call_args
    # First positional is the _ClipboardDataObject instance.
    assert isinstance(args.args[0], clipboard_win32._ClipboardDataObject)
    assert args.args[0].payloads == {0xCB00: b"hello"}
    assert args.kwargs["iid"] == fake_pythoncom.IID_IDataObject


def test_make_data_object_sets_com_interfaces_lazily(clipboard_win32, fake_win32clipboard):
    """_ClipboardDataObject._com_interfaces_ is empty at module load (it
    references pythoncom.IID_IDataObject which is unavailable on Linux);
    _make_data_object populates it on first call so wrap() sees the
    correct IID list."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]

    assert clipboard_win32._ClipboardDataObject._com_interfaces_ == []

    clipboard_win32._make_data_object({0xCC00: b"a"})

    assert clipboard_win32._ClipboardDataObject._com_interfaces_ == [fake_pythoncom.IID_IDataObject]


# --- _ole_set_clipboard_with_retry -----------------------------------------


def test_ole_set_clipboard_succeeds_on_first_attempt(clipboard_win32, fake_win32clipboard):
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_pythoncom.OleSetClipboard.return_value = None

    clipboard_win32._ole_set_clipboard_with_retry(
        fake_pythoncom, MagicMock(name="do"), retries=3, delay_ms=0
    )

    fake_pythoncom.OleSetClipboard.assert_called_once()


def test_ole_set_clipboard_retries_on_transient_failure(clipboard_win32, fake_win32clipboard):
    """CLIPBRD_E_CANT_OPEN (clipboard inspector briefly holds the lock)
    surfaces as an exception from OleSetClipboard; the retry budget covers
    transient contention, same shape as _open_clipboard_with_retry."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    attempts = iter([RuntimeError("cant open"), RuntimeError("cant open"), None])

    def side_effect(_do):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    fake_pythoncom.OleSetClipboard.side_effect = side_effect

    clipboard_win32._ole_set_clipboard_with_retry(
        fake_pythoncom, MagicMock(name="do"), retries=5, delay_ms=0
    )

    assert fake_pythoncom.OleSetClipboard.call_count == 3


def test_ole_set_clipboard_raises_after_budget_exhausted(clipboard_win32, fake_win32clipboard):
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_pythoncom.OleSetClipboard.side_effect = RuntimeError("cant open")

    with pytest.raises(RuntimeError, match="OleSetClipboard failed after 3 retries"):
        clipboard_win32._ole_set_clipboard_with_retry(
            fake_pythoncom, MagicMock(name="do"), retries=3, delay_ms=0
        )

    assert fake_pythoncom.OleSetClipboard.call_count == 3


# --- _write_via_ole --------------------------------------------------------


def test_write_via_ole_empty_payloads_is_noop(clipboard_win32, fake_win32clipboard):
    """Direct call: an empty payloads dict short-circuits before any
    worker dispatch -- avoids constructing an empty IDataObject and
    publishing it. (write_multi({}) has its own early return upstream
    that doesn't reach _write_via_ole, so this test covers the
    _write_via_ole-internal guard directly.)"""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]

    clipboard_win32._write_via_ole({})

    fake_pythoncom.OleSetClipboard.assert_not_called()
    fake_pythoncom.OleFlushClipboard.assert_not_called()


# --- write_text ------------------------------------------------------------


def test_write_text_plain_uses_ole_with_utf16_le_null_terminated(
    clipboard_win32, fake_win32clipboard
):
    """text/plain encodes to UTF-16 LE + NUL (CF_UNICODETEXT format
    contract) and gets handed to OleSetClipboard via an IDataObject whose
    payload dict maps CF_UNICODETEXT to those bytes."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_wrap = _sys.modules["win32com.server.util"].wrap
    fake_wrap.side_effect = lambda obj, iid: obj  # passthrough so we can inspect

    clipboard_win32.write_text("hello", "text/plain")

    fake_pythoncom.OleSetClipboard.assert_called_once()
    fake_pythoncom.OleFlushClipboard.assert_called_once()
    do_arg = fake_pythoncom.OleSetClipboard.call_args.args[0]
    assert do_arg.payloads == {
        fake_win32clipboard.CF_UNICODETEXT: "hello".encode("utf-16-le") + b"\x00\x00"
    }


def test_write_text_registered_format_uses_ole_with_utf8(clipboard_win32, fake_win32clipboard):
    """text/html / text/rtf / image/svg+xml encode to UTF-8 and land as
    bytes under the registered format ID inside the IDataObject."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC400
    fake_wrap = _sys.modules["win32com.server.util"].wrap
    fake_wrap.side_effect = lambda obj, iid: obj

    clipboard_win32.write_text("<svg>—</svg>", "image/svg+xml")

    do_arg = fake_pythoncom.OleSetClipboard.call_args.args[0]
    assert do_arg.payloads == {0xC400: "<svg>—</svg>".encode()}
    fake_pythoncom.OleFlushClipboard.assert_called_once()


def test_write_text_calls_ole_flush_after_ole_set(clipboard_win32, fake_win32clipboard):
    """OleFlushClipboard must run AFTER OleSetClipboard so the IDataObject
    pointer is released into HGLOBAL handles. If OleFlushClipboard runs
    before (or doesn't run), paste targets reach back into our IDataObject
    and our process must pump messages to satisfy them -- which we don't.
    """
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    call_order: list[str] = []
    fake_pythoncom.OleSetClipboard.side_effect = lambda _do: call_order.append("set")
    fake_pythoncom.OleFlushClipboard.side_effect = lambda: call_order.append("flush")

    clipboard_win32.write_text("hi", "text/plain")

    assert call_order == ["set", "flush"]


# --- write_multi -----------------------------------------------------------


def test_write_multi_empty_input_is_noop(clipboard_win32, fake_win32clipboard):
    """If the input dict is empty, OleSetClipboard is never called --
    avoids constructing an empty IDataObject and emptying the clipboard
    for nothing."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]

    clipboard_win32.write_multi({})

    fake_pythoncom.OleSetClipboard.assert_not_called()
    fake_pythoncom.OleFlushClipboard.assert_not_called()


def test_write_multi_publishes_all_formats_in_one_idataobject(clipboard_win32, fake_win32clipboard):
    """Multi-format atomic publish: a single IDataObject offering all
    payloads, ONE OleSetClipboard call, ONE OleFlushClipboard call. The
    flush renders every format inside one Win32 transaction."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    ids = iter([0xC500, 0xC501])
    fake_win32clipboard.RegisterClipboardFormat.side_effect = lambda _: next(ids)
    fake_wrap = _sys.modules["win32com.server.util"].wrap
    fake_wrap.side_effect = lambda obj, iid: obj

    clipboard_win32.write_multi(
        {
            "text/plain": "Heading",
            "text/html": "<h1>Heading</h1>",
        }
    )

    fake_pythoncom.OleSetClipboard.assert_called_once()
    fake_pythoncom.OleFlushClipboard.assert_called_once()
    do_arg = fake_pythoncom.OleSetClipboard.call_args.args[0]
    assert do_arg.payloads == {
        fake_win32clipboard.CF_UNICODETEXT: "Heading".encode("utf-16-le") + b"\x00\x00",
        0xC500: b"<h1>Heading</h1>",
    }


def test_write_multi_resolves_formats_before_ole_set(clipboard_win32, fake_win32clipboard):
    """Format resolution (RegisterClipboardFormat) and encoding happen
    BEFORE OleSetClipboard so any error surfaces outside the
    transaction. Structural assertion via call order."""
    import sys as _sys

    fake_pythoncom = _sys.modules["pythoncom"]
    call_order: list[str] = []
    fake_win32clipboard.RegisterClipboardFormat.side_effect = lambda _: (
        call_order.append("register") or 0xC600
    )
    fake_pythoncom.OleSetClipboard.side_effect = lambda _do: call_order.append("ole_set")

    clipboard_win32.write_multi({"text/html": "<p>hi</p>"})

    assert call_order.index("register") < call_order.index("ole_set")


# --- list_formats ----------------------------------------------------------


def test_list_formats_iterates_via_enumclipboardformats(clipboard_win32, fake_win32clipboard):
    """list_formats walks EnumClipboardFormats -- pywin32 returns 0 when
    the chain ends -- and resolves each ID to a human-readable name."""
    # Sequence: standard CF_UNICODETEXT (13) -> registered 0xC700 -> end (0).
    enum_returns = iter([13, 0xC700, 0])
    fake_win32clipboard.EnumClipboardFormats.side_effect = lambda _prev: next(enum_returns)
    fake_win32clipboard.GetClipboardFormatName.return_value = "image/svg+xml"

    result = clipboard_win32.list_formats()

    assert result == ["UnicodeText", "image/svg+xml"]
    fake_win32clipboard.OpenClipboard.assert_called_once()
    fake_win32clipboard.CloseClipboard.assert_called_once()


def test_list_formats_falls_back_to_numeric_for_unknown_constant(
    clipboard_win32, fake_win32clipboard
):
    """If GetClipboardFormatName fails for an unknown built-in constant,
    list_formats falls back to 'Format<n>' so the UI still shows something."""
    enum_returns = iter([0x9999, 0])
    fake_win32clipboard.EnumClipboardFormats.side_effect = lambda _prev: next(enum_returns)
    fake_win32clipboard.GetClipboardFormatName.side_effect = RuntimeError("no name")

    result = clipboard_win32.list_formats()

    assert result == [f"Format{0x9999}"]


def test_list_formats_closes_clipboard_on_exception(clipboard_win32, fake_win32clipboard):
    """If EnumClipboardFormats raises mid-walk, the clipboard still closes."""
    fake_win32clipboard.EnumClipboardFormats.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        clipboard_win32.list_formats()

    fake_win32clipboard.CloseClipboard.assert_called_once()
