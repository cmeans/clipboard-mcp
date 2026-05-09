"""Unit tests for the Win32 clipboard wrapper.

Exercises clipboard_win32.read_text / write_text / write_multi / list_formats
with `win32clipboard` injected as a MagicMock via sys.modules so the tests
run on Linux CI (where pywin32 is not installed). Real Windows-clipboard
round-trips are covered by tests/test_clipboard_win32_integration.py on the
windows-latest runner.

The wrapper is small enough that the unit tests cover every branch:
- _import_win32clipboard cache hit / miss
- _register_format cache hit / miss
- _open_clipboard_with_retry retry budget exhaustion
- _format_id_for_mime for all four supported MIMEs + the unsupported case
- read_text for absent format vs str return vs bytes return
- write_text for text/plain (CF_UNICODETEXT) vs registered formats
- write_multi atomic transaction, empty input no-op
- list_formats including standard-format-name lookup and custom fallback
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_win32clipboard() -> MagicMock:
    """Install a MagicMock as the `win32clipboard` module for the duration of
    the test, then restore the prior state. The wrapper imports the module
    inside each public function via _import_win32clipboard, so injecting at
    sys.modules is sufficient -- no need to reload clipboard_win32 itself."""
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

    # _open_clipboard_with_retry now also imports win32gui to obtain the
    # desktop HWND. Inject a stub that returns a stable non-zero integer so
    # tests can assert OpenClipboard was called with a non-NULL hwnd (the
    # invariant that fixes the SetClipboardData silent-no-op for custom
    # registered formats; see clipboard_win32._get_clipboard_hwnd).
    fake_win32gui = MagicMock(name="win32gui")
    fake_win32gui.GetDesktopWindow.return_value = 0x10001  # stable non-zero
    prior_win32gui = sys.modules.get("win32gui")
    sys.modules["win32gui"] = fake_win32gui

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


def test_open_clipboard_passes_non_null_desktop_hwnd(clipboard_win32, fake_win32clipboard):
    """Critical regression guard: OpenClipboard must be called with a non-NULL
    hwnd (the desktop window handle from win32gui.GetDesktopWindow). MSDN
    explicitly warns that NULL hwnd causes EmptyClipboard to set ownership to
    NULL and SetClipboardData to fail silently for registered custom formats
    -- the exact bug class that produced the SVG silent-no-op symptoms in
    mc-005 / mc-009 / mc-020 of the PR #146 verification run before this fix.
    The desktop window handle is the simplest stable HWND that gives
    EmptyClipboard a non-NULL owner so SetClipboardData works for any format."""
    fake_win32clipboard.OpenClipboard.return_value = None

    clipboard_win32._open_clipboard_with_retry(fake_win32clipboard, retries=3, delay_ms=0)

    # The fixture stub returns 0x10001 from win32gui.GetDesktopWindow;
    # OpenClipboard MUST receive that, never 0/None.
    fake_win32clipboard.OpenClipboard.assert_called_once_with(0x10001)


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


# --- write_text ------------------------------------------------------------


def test_write_text_plain_passes_str_to_setclipboarddata(clipboard_win32, fake_win32clipboard):
    """text/plain hands the Python str to SetClipboardData under
    CF_UNICODETEXT -- pywin32 handles UTF-16 encoding + NUL termination
    internally."""
    clipboard_win32.write_text("hello", "text/plain")

    fake_win32clipboard.EmptyClipboard.assert_called_once()
    fake_win32clipboard.SetClipboardData.assert_called_once_with(
        fake_win32clipboard.CF_UNICODETEXT, "hello"
    )
    fake_win32clipboard.CloseClipboard.assert_called_once()


def test_write_text_registered_format_passes_utf8_bytes(clipboard_win32, fake_win32clipboard):
    """text/html / text/rtf / image/svg+xml encode their content to UTF-8
    bytes before SetClipboardData under the registered format ID."""
    fake_win32clipboard.RegisterClipboardFormat.return_value = 0xC400

    clipboard_win32.write_text("<svg>—</svg>", "image/svg+xml")

    fake_win32clipboard.SetClipboardData.assert_called_once_with(0xC400, "<svg>—</svg>".encode())


def test_write_text_closes_clipboard_on_exception(clipboard_win32, fake_win32clipboard):
    """If SetClipboardData raises, CloseClipboard still runs."""
    fake_win32clipboard.SetClipboardData.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        clipboard_win32.write_text("hi", "text/plain")

    fake_win32clipboard.CloseClipboard.assert_called_once()


# --- write_multi -----------------------------------------------------------


def test_write_multi_empty_input_is_noop(clipboard_win32, fake_win32clipboard):
    """If the input dict has no recognized MIMEs, OpenClipboard is never
    called -- avoids holding the clipboard for a no-op transaction."""
    clipboard_win32.write_multi({})

    fake_win32clipboard.OpenClipboard.assert_not_called()


def test_write_multi_writes_all_formats_in_one_transaction(clipboard_win32, fake_win32clipboard):
    """Multi-format atomic write: one OpenClipboard / EmptyClipboard,
    SetClipboardData per format, one CloseClipboard. No window during which
    the clipboard holds half the formats."""
    ids = iter([0xC500, 0xC501])
    fake_win32clipboard.RegisterClipboardFormat.side_effect = lambda _: next(ids)

    clipboard_win32.write_multi(
        {
            "text/plain": "Heading",
            "text/html": "<h1>Heading</h1>",
        }
    )

    fake_win32clipboard.OpenClipboard.assert_called_once()
    fake_win32clipboard.EmptyClipboard.assert_called_once()
    assert fake_win32clipboard.SetClipboardData.call_count == 2
    fake_win32clipboard.CloseClipboard.assert_called_once()

    set_calls = {call.args for call in fake_win32clipboard.SetClipboardData.call_args_list}
    assert (fake_win32clipboard.CF_UNICODETEXT, "Heading") in set_calls
    assert (0xC500, b"<h1>Heading</h1>") in set_calls


def test_write_multi_encodes_before_opening_clipboard(clipboard_win32, fake_win32clipboard):
    """Encoding errors must surface OUTSIDE the OpenClipboard / CloseClipboard
    bracket so the clipboard is never held in a partially-open state. We
    can't easily induce an encoding error on str.encode('utf-8') so this
    assertion is structural: RegisterClipboardFormat (called inside the
    pre-open resolution loop) precedes OpenClipboard."""
    call_order: list[str] = []
    fake_win32clipboard.RegisterClipboardFormat.side_effect = lambda _: (
        call_order.append("register") or 0xC600
    )
    fake_win32clipboard.OpenClipboard.side_effect = lambda _hwnd: call_order.append("open")

    clipboard_win32.write_multi({"text/html": "<p>hi</p>"})

    # register happens before open.
    assert call_order.index("register") < call_order.index("open")


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
