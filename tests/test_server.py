"""Tests for the MCP server tools and clipboard backend.

All clipboard access is mocked — no actual system clipboard needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp.utilities.types import Image

from clipboard_mcp.clipboard import (
    ClipboardError,
    read_clipboard,
    read_clipboard_image,
    write_clipboard,
    list_clipboard_formats,
    _find_wayland_display,
    _wayland_env,
    _detect_backend,
    _get_backend,
)
from clipboard_mcp.server import (
    clipboard_paste,
    clipboard_copy,
    clipboard_read_raw,
    clipboard_list_formats,
    _load_instruction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<table>
<tr><th>Name</th><th>Age</th><th>City</th></tr>
<tr><td>Alice</td><td>30</td><td>Portland</td></tr>
<tr><td>Bob</td><td>25</td><td>Seattle</td></tr>
</table>
"""

SAMPLE_TSV = "Name\tAge\tCity\nAlice\t30\tPortland\nBob\t25\tSeattle"


def _mock_read(html: str = "", text: str = ""):
    """Create a mock for read_clipboard that returns html or text by mime type."""
    async def _read(mime_type: str = "text/plain") -> str:
        if mime_type == "text/html":
            return html
        return text
    return _read


def _mock_read_error(msg: str = "Command not found: wl-paste"):
    """Create a mock for read_clipboard that raises ClipboardError."""
    async def _read(mime_type: str = "text/plain") -> str:
        raise ClipboardError(msg)
    return _read


# ---------------------------------------------------------------------------
# 1. clipboard_paste: tabular data (HTML)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_table_from_html():
    """clipboard_paste extracts and formats table data from HTML clipboard."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows × 3 columns" in result
    assert "| Name" in result
    assert "| Alice" in result
    assert "| Bob" in result


@pytest.mark.asyncio
async def test_paste_table_json():
    """clipboard_paste returns valid JSON for tables when requested."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="json")

    assert "3 rows × 3 columns" in result
    import json
    json_part = result.split("\n\n", 1)[1]
    data = json.loads(json_part)
    assert len(data) == 2
    assert data[0]["Name"] == "Alice"


@pytest.mark.asyncio
async def test_paste_table_csv():
    """clipboard_paste returns CSV for tables when requested."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="csv")

    assert "3 rows × 3 columns" in result
    assert '"Name","Age","City"' in result
    assert '"Alice","30","Portland"' in result


@pytest.mark.asyncio
async def test_paste_format_case_insensitive():
    """clipboard_paste accepts output_format in any case."""
    for fmt in ("JSON", "Json", "jSoN", " json ", "CSV", "Csv", "MARKDOWN"):
        with patch("clipboard_mcp.server.read_clipboard",
                   side_effect=_mock_read(html=SAMPLE_HTML)):
            result = await clipboard_paste(output_format=fmt)
        assert "3 rows × 3 columns" in result, f"Failed for format {fmt!r}"


@pytest.mark.asyncio
async def test_paste_format_invalid():
    """clipboard_paste returns error message for unknown format."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="xml")
    assert "Unknown output_format" in result


# ---------------------------------------------------------------------------
# 2. clipboard_paste: TSV fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_tsv_fallback():
    """clipboard_paste falls back to TSV when no HTML is available."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text=SAMPLE_TSV)):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows × 3 columns" in result
    assert "| Name" in result
    assert "| Alice" in result


@pytest.mark.asyncio
async def test_paste_tsv_when_html_errors():
    """clipboard_paste falls back to TSV when HTML read raises an error."""
    async def _mixed_read(mime_type: str = "text/plain") -> str:
        if mime_type == "text/html":
            raise ClipboardError("No HTML available")
        return SAMPLE_TSV

    with patch("clipboard_mcp.server.read_clipboard", side_effect=_mixed_read):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows × 3 columns" in result
    assert "| Alice" in result


# ---------------------------------------------------------------------------
# 3. clipboard_paste: non-tabular content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_plain_text():
    """clipboard_paste returns plain text when no table is found."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text="Hello, this is plain text.")):
        result = await clipboard_paste()

    assert "Clipboard content:" in result
    assert "Hello, this is plain text." in result


@pytest.mark.asyncio
async def test_paste_json_content():
    """clipboard_paste detects and pretty-prints JSON."""
    json_text = '{"name": "Alice", "age": 30}'
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text=json_text)):
        result = await clipboard_paste()

    assert "Clipboard contains JSON:" in result
    assert "```json" in result
    assert '"name": "Alice"' in result


@pytest.mark.asyncio
async def test_paste_url():
    """clipboard_paste detects and returns URLs cleanly."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text="https://example.com/path?q=1")):
        result = await clipboard_paste()

    assert "Clipboard contains URL:" in result
    assert "https://example.com/path?q=1" in result


@pytest.mark.asyncio
async def test_paste_code_snippet():
    """clipboard_paste detects code and wraps it in a code block."""
    code = "def hello():\n    print('hello world')\n\nhello()"
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text=code)):
        result = await clipboard_paste()

    assert "Clipboard contains code:" in result
    assert "```" in result
    assert "def hello():" in result


@pytest.mark.asyncio
async def test_paste_html_without_table():
    """clipboard_paste extracts text from HTML that has no table."""
    html = "<p>This is a <b>rich text</b> paragraph.</p><p>Second paragraph.</p>"
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html=html, text="This is a rich text paragraph. Second paragraph.")):
        result = await clipboard_paste()

    assert "rich text" in result
    assert "Second paragraph" in result


@pytest.mark.asyncio
async def test_paste_empty_clipboard():
    """clipboard_paste returns empty message when clipboard is empty."""
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "Clipboard is empty" in result


@pytest.mark.asyncio
async def test_paste_both_fail():
    """clipboard_paste returns empty message when both reads fail."""
    with patch("clipboard_mcp.server.read_clipboard", side_effect=_mock_read_error()):
        with patch("clipboard_mcp.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "Clipboard is empty" in result


@pytest.mark.asyncio
async def test_paste_large_content_truncated():
    """clipboard_paste truncates content over 50KB."""
    huge = "x" * 100_000
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text=huge)):
        result = await clipboard_paste()

    assert "truncated" in result.lower()



# ---------------------------------------------------------------------------
# 4. clipboard_list_formats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_formats_with_html():
    """clipboard_list_formats highlights HTML availability."""
    mock_formats = ["text/html", "text/plain", "UTF8_STRING", "TARGETS"]

    with patch("clipboard_mcp.server.list_clipboard_formats", return_value=mock_formats):
        result = await clipboard_list_formats()

    assert "4 format(s)" in result
    assert "text/html" in result
    assert "✓ HTML available" in result
    assert "✓ Plain text available" in result


@pytest.mark.asyncio
async def test_list_formats_text_only():
    """clipboard_list_formats works when only plain text is available."""
    mock_formats = ["text/plain", "UTF8_STRING"]

    with patch("clipboard_mcp.server.list_clipboard_formats", return_value=mock_formats):
        result = await clipboard_list_formats()

    assert "2 format(s)" in result
    assert "✓ Plain text available" in result
    # Should NOT have the HTML highlight
    assert "HTML available" not in result


@pytest.mark.asyncio
async def test_list_formats_empty():
    """clipboard_list_formats handles empty clipboard."""
    with patch("clipboard_mcp.server.list_clipboard_formats", return_value=[]):
        result = await clipboard_list_formats()

    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_list_formats_error():
    """clipboard_list_formats handles ClipboardError gracefully."""
    with patch("clipboard_mcp.server.list_clipboard_formats",
               side_effect=ClipboardError("No clipboard tool")):
        result = await clipboard_list_formats()

    assert "Error" in result
    assert "No clipboard tool" in result


# ---------------------------------------------------------------------------
# 5. clipboard backend error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_clipboard_command_not_found():
    """read_clipboard raises ClipboardError when the clipboard tool isn't installed."""
    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch("clipboard_mcp.clipboard._run",
                   side_effect=ClipboardError("Command not found: wl-paste")):
            with pytest.raises(ClipboardError, match="Command not found"):
                await read_clipboard("text/html")


@pytest.mark.asyncio
async def test_read_clipboard_timeout():
    """read_clipboard raises ClipboardError on timeout."""
    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch("clipboard_mcp.clipboard._run",
                   side_effect=ClipboardError("Clipboard command timed out")):
            with pytest.raises(ClipboardError, match="timed out"):
                await read_clipboard("text/html")


@pytest.mark.asyncio
async def test_read_raw_returns_content():
    """clipboard_read_raw returns the raw content for a given MIME type."""
    with patch("clipboard_mcp.server.read_clipboard",
               return_value="<table><tr><td>hi</td></tr></table>"):
        result = await clipboard_read_raw(mime_type="text/html")

    assert "<table>" in result
    assert "chars" in result


@pytest.mark.asyncio
async def test_read_raw_truncates_large_content():
    """clipboard_read_raw truncates very large clipboard content."""
    huge = "x" * 100_000
    with patch("clipboard_mcp.server.read_clipboard", return_value=huge):
        result = await clipboard_read_raw(mime_type="text/plain")

    assert "truncated" in result.lower()
    # Should not return the full 100k
    assert len(result) < 60_000


@pytest.mark.asyncio
async def test_read_raw_error():
    """clipboard_read_raw handles ClipboardError gracefully."""
    with patch("clipboard_mcp.server.read_clipboard", side_effect=ClipboardError("fail")):
        result = await clipboard_read_raw(mime_type="text/html")

    assert "Error" in result
    assert "fail" in result


@pytest.mark.asyncio
async def test_read_raw_empty():
    """clipboard_read_raw handles empty content for a MIME type."""
    with patch("clipboard_mcp.server.read_clipboard", return_value=""):
        result = await clipboard_read_raw(mime_type="text/html")

    assert "No content available" in result


@pytest.mark.asyncio
async def test_read_raw_rejects_binary_mime():
    """clipboard_read_raw refuses to read binary MIME types like image/png."""
    result = await clipboard_read_raw(mime_type="image/png")

    assert "Cannot read binary" in result
    assert "image/png" in result
    assert "text-based formats" in result


@pytest.mark.asyncio
async def test_read_raw_rejects_audio_mime():
    """clipboard_read_raw refuses audio MIME types."""
    result = await clipboard_read_raw(mime_type="audio/wav")

    assert "Cannot read binary" in result


@pytest.mark.asyncio
async def test_read_raw_rejects_video_mime():
    """clipboard_read_raw refuses video MIME types."""
    result = await clipboard_read_raw(mime_type="video/mp4")

    assert "Cannot read binary" in result


@pytest.mark.asyncio
async def test_read_raw_allows_svg():
    """clipboard_read_raw allows image/svg+xml as text-readable."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="50"/></svg>'
    with patch("clipboard_mcp.server.read_clipboard", new_callable=AsyncMock, return_value=svg):
        result = await clipboard_read_raw(mime_type="image/svg+xml")

    assert "circle" in result
    assert "Cannot read binary" not in result


@pytest.mark.asyncio
async def test_read_raw_allows_application_json():
    """clipboard_read_raw allows application/json as text-readable."""
    json_str = '{"key": "value"}'
    with patch("clipboard_mcp.server.read_clipboard", new_callable=AsyncMock, return_value=json_str):
        result = await clipboard_read_raw(mime_type="application/json")

    assert "key" in result
    assert "Cannot read binary" not in result


# ---------------------------------------------------------------------------
# 6. clipboard_paste with binary clipboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_returns_image():
    """clipboard_paste returns Image when clipboard has image data."""
    fake_png = b"\x89PNG\r\n\x1a\nfakedata"
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/png", "image/tiff"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       return_value=fake_png):
                result = await clipboard_paste()

    assert isinstance(result, Image)
    assert result.data == fake_png


@pytest.mark.asyncio
async def test_paste_empty_clipboard_no_binary():
    """clipboard_paste returns 'empty' when clipboard has no text and no binary."""
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# 7. Wayland auto-detection
# ---------------------------------------------------------------------------


def _fake_runtime_dir(tmp_path, sockets=("wayland-0",)):
    """Create fake Wayland socket files in a temp dir and return the path."""
    import os
    import socket

    for name in sockets:
        sock_path = tmp_path / name
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(sock_path))
        s.close()
        # Also create corresponding .lock file (should be ignored)
        (tmp_path / f"{name}.lock").touch()

    return str(tmp_path)


def test_find_wayland_display_discovers_socket(tmp_path):
    """_find_wayland_display finds wayland-0 in XDG_RUNTIME_DIR."""
    runtime = _fake_runtime_dir(tmp_path)
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": runtime}, clear=False):
        result = _find_wayland_display()
    assert result == "wayland-0"


def test_find_wayland_display_picks_lowest(tmp_path):
    """_find_wayland_display picks the lowest-numbered socket."""
    runtime = _fake_runtime_dir(tmp_path, sockets=("wayland-1", "wayland-0", "wayland-2"))
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": runtime}, clear=False):
        result = _find_wayland_display()
    assert result == "wayland-0"


def test_find_wayland_display_no_sockets(tmp_path):
    """_find_wayland_display returns None when no sockets exist."""
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}, clear=False):
        result = _find_wayland_display()
    assert result is None


def test_find_wayland_display_no_runtime_dir():
    """_find_wayland_display returns None when XDG_RUNTIME_DIR doesn't exist."""
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": "/nonexistent"}, clear=False):
        result = _find_wayland_display()
    assert result is None


def test_find_wayland_display_ignores_lock_files(tmp_path):
    """_find_wayland_display ignores .lock files."""
    (tmp_path / "wayland-0.lock").touch()
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}, clear=False):
        result = _find_wayland_display()
    assert result is None


def test_wayland_env_returns_none_when_both_set():
    """_wayland_env returns None when both WAYLAND_DISPLAY and XDG_RUNTIME_DIR are set."""
    with patch.dict("os.environ", {
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }, clear=False):
        assert _wayland_env() is None


def test_wayland_env_injects_display(tmp_path):
    """_wayland_env injects WAYLAND_DISPLAY when not set but socket exists."""
    runtime = _fake_runtime_dir(tmp_path)
    env_patch = {"XDG_RUNTIME_DIR": runtime}
    with patch.dict("os.environ", env_patch, clear=False):
        import os
        os.environ.pop("WAYLAND_DISPLAY", None)
        env = _wayland_env()

    assert env is not None
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["XDG_RUNTIME_DIR"] == runtime


def test_wayland_env_injects_runtime_dir(tmp_path):
    """_wayland_env injects XDG_RUNTIME_DIR when not set."""
    runtime = _fake_runtime_dir(tmp_path)
    with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
        import os
        os.environ.pop("XDG_RUNTIME_DIR", None)
        with patch("clipboard_mcp.clipboard.os.getuid", return_value=1000):
            # Point the fallback path at our tmp_path with real sockets
            with patch("clipboard_mcp.clipboard.Path") as mock_path:
                mock_path.return_value.is_dir.return_value = True
                # Use the real tmp_path for the env value
                env = _wayland_env()

    assert env is not None
    assert "XDG_RUNTIME_DIR" in env


def test_wayland_env_injects_both_when_neither_set(tmp_path):
    """_wayland_env injects both vars when neither is set (Claude Desktop scenario)."""
    runtime = _fake_runtime_dir(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_RUNTIME_DIR", None)
        with patch("clipboard_mcp.clipboard.os.getuid", return_value=1000):
            with patch("clipboard_mcp.clipboard.Path") as mock_path:
                # Make Path(xdg_runtime).is_dir() return True
                mock_path.return_value.is_dir.return_value = True
                # But use real _find_wayland_display with the actual tmp_path
                with patch("clipboard_mcp.clipboard._find_wayland_display", return_value="wayland-0"):
                    env = _wayland_env()

    assert env is not None
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["WAYLAND_DISPLAY"] == "wayland-0"


def test_wayland_env_no_socket_still_passes_runtime_dir(tmp_path):
    """_wayland_env still provides XDG_RUNTIME_DIR even when no socket is found."""
    env_patch = {"XDG_RUNTIME_DIR": str(tmp_path)}
    with patch.dict("os.environ", env_patch, clear=False):
        import os
        os.environ.pop("WAYLAND_DISPLAY", None)
        env = _wayland_env()

    # env returned so XDG_RUNTIME_DIR is inherited; no WAYLAND_DISPLAY added
    assert env is not None
    assert "WAYLAND_DISPLAY" not in env


def test_detect_backend_wayland_via_socket(tmp_path):
    """_detect_backend selects wayland when socket exists but env vars are unset."""
    runtime = _fake_runtime_dir(tmp_path)
    env_patch = {"XDG_RUNTIME_DIR": runtime}
    with patch.dict("os.environ", env_patch, clear=False):
        import os
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
        with patch("clipboard_mcp.clipboard.platform.system", return_value="Linux"):
            with patch("clipboard_mcp.clipboard.shutil.which", return_value="/usr/bin/wl-paste"):
                # Clear cached backend
                import clipboard_mcp.clipboard as cb
                cb._backend = None
                result = _detect_backend()

    assert result == "wayland"


def test_detect_backend_prefers_env_var_over_socket():
    """_detect_backend uses WAYLAND_DISPLAY env var without needing socket scan."""
    with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
        with patch("clipboard_mcp.clipboard.platform.system", return_value="Linux"):
            with patch("clipboard_mcp.clipboard.shutil.which", return_value="/usr/bin/wl-paste"):
                import clipboard_mcp.clipboard as cb
                cb._backend = None
                result = _detect_backend()

    assert result == "wayland"


# ---------------------------------------------------------------------------
# 8. macOS backend
# ---------------------------------------------------------------------------

from clipboard_mcp.clipboard import (
    _x11_read,
    _x11_list_formats,
    _macos_read,
    _macos_list_formats,
    _UTI_TO_MIME,
    _windows_read,
    _windows_list_formats,
    _WIN_TO_MIME,
)


@pytest.mark.asyncio
async def test_macos_read_html():
    """_macos_read uses osascript for text/html."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>") as mock_run:
        result = await _macos_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "osascript"


@pytest.mark.asyncio
async def test_macos_read_plain():
    """_macos_read uses pbpaste for text/plain."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="hello") as mock_run:
        result = await _macos_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["pbpaste"]


@pytest.mark.asyncio
async def test_macos_read_unsupported_returns_empty():
    """_macos_read returns empty string for unsupported MIME types."""
    result = await _macos_read("text/rtf")
    assert result == ""


@pytest.mark.asyncio
async def test_macos_list_formats_maps_uti_to_mime():
    """_macos_list_formats maps known UTIs to MIME types."""
    raw_output = "public.html\npublic.utf8-plain-text\npublic.png\n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _macos_list_formats()

    assert result == ["text/html", "text/plain", "image/png"]


@pytest.mark.asyncio
async def test_macos_list_formats_passthrough_unknown():
    """_macos_list_formats passes through unknown UTIs as-is."""
    raw_output = "public.html\ncom.apple.something-custom\n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _macos_list_formats()

    assert result == ["text/html", "com.apple.something-custom"]


# ---------------------------------------------------------------------------
# 9. Windows backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_windows_read_html():
    """_windows_read uses PowerShell HTML clipboard for text/html."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>") as mock_run:
        result = await _windows_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "powershell"
    assert "Html" in cmd[-1]


@pytest.mark.asyncio
async def test_windows_read_plain():
    """_windows_read uses Get-Clipboard for text/plain."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="hello") as mock_run:
        result = await _windows_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert "Get-Clipboard" in cmd[-1]


@pytest.mark.asyncio
async def test_windows_read_unsupported_returns_empty():
    """_windows_read returns empty string for unsupported MIME types."""
    result = await _windows_read("text/rtf")
    assert result == ""


@pytest.mark.asyncio
async def test_windows_list_formats_maps_names_to_mime():
    """_windows_list_formats maps known Windows format names to MIME types."""
    raw_output = "HTML Format\nText\nUnicodeText\nPNG\n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _windows_list_formats()

    assert result == ["text/html", "text/plain", "text/plain", "image/png"]


@pytest.mark.asyncio
async def test_windows_list_formats_passthrough_unknown():
    """_windows_list_formats passes through unknown format names as-is."""
    raw_output = "HTML Format\nSystem.String\n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _windows_list_formats()

    assert result == ["text/html", "System.String"]


# ---------------------------------------------------------------------------
# 10. X11 backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_x11_read_html():
    """_x11_read calls xclip with correct target for text/html."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>") as mock_run:
        result = await _x11_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "text/html", "-o"]


@pytest.mark.asyncio
async def test_x11_read_plain():
    """_x11_read calls xclip with correct target for text/plain."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value="hello") as mock_run:
        result = await _x11_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "text/plain", "-o"]


@pytest.mark.asyncio
async def test_x11_list_formats():
    """_x11_list_formats calls xclip with TARGETS and parses output."""
    raw_output = "text/html\ntext/plain\nimage/png\n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output) as mock_run:
        result = await _x11_list_formats()

    assert result == ["text/html", "text/plain", "image/png"]
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "TARGETS", "-o"]


@pytest.mark.asyncio
async def test_x11_list_formats_strips_whitespace():
    """_x11_list_formats strips whitespace and skips blank lines."""
    raw_output = "  text/html  \n\n  text/plain  \n"
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _x11_list_formats()

    assert result == ["text/html", "text/plain"]


# ---------------------------------------------------------------------------
# 11. _load_instruction()
# ---------------------------------------------------------------------------


def test_load_instruction_returns_content():
    """_load_instruction loads and strips instruction file content."""
    result = _load_instruction("server")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should not have leading/trailing whitespace
    assert result == result.strip()


def test_load_instruction_missing_file():
    """_load_instruction raises RuntimeError for missing files."""
    with pytest.raises(RuntimeError, match="Missing instruction file"):
        _load_instruction("nonexistent_file")


# ---------------------------------------------------------------------------
# 12. _detect_backend() platform coverage
# ---------------------------------------------------------------------------


def test_detect_backend_darwin():
    """_detect_backend returns 'macos' on Darwin."""
    with patch("clipboard_mcp.clipboard.platform.system", return_value="Darwin"):
        import clipboard_mcp.clipboard as cb
        cb._backend = None
        result = _detect_backend()

    assert result == "macos"


def test_detect_backend_windows():
    """_detect_backend returns 'windows' on Windows."""
    with patch("clipboard_mcp.clipboard.platform.system", return_value="Windows"):
        import clipboard_mcp.clipboard as cb
        cb._backend = None
        result = _detect_backend()

    assert result == "windows"


def test_detect_backend_unsupported():
    """_detect_backend raises ClipboardError on unsupported platforms."""
    with patch("clipboard_mcp.clipboard.platform.system", return_value="FreeBSD"):
        import clipboard_mcp.clipboard as cb
        cb._backend = None
        with pytest.raises(ClipboardError, match="Unsupported platform: FreeBSD"):
            _detect_backend()


def test_detect_backend_linux_no_tools():
    """_detect_backend raises ClipboardError when no clipboard tools are installed."""
    with patch("clipboard_mcp.clipboard.platform.system", return_value="Linux"):
        with patch("clipboard_mcp.clipboard.shutil.which", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                import clipboard_mcp.clipboard as cb
                cb._backend = None
                with pytest.raises(ClipboardError, match="No clipboard tool found"):
                    _detect_backend()


# ---------------------------------------------------------------------------
# 13. Backend dispatch (read_clipboard / list_clipboard_formats)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_wayland():
    """read_clipboard calls the wayland reader when backend is wayland."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"wayland": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_x11():
    """read_clipboard calls the x11 reader when backend is x11."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("clipboard_mcp.clipboard._get_backend", return_value="x11"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"x11": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_macos():
    """read_clipboard calls the macos reader when backend is macos."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("clipboard_mcp.clipboard._get_backend", return_value="macos"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"macos": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_windows():
    """read_clipboard calls the windows reader when backend is windows."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("clipboard_mcp.clipboard._get_backend", return_value="windows"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"windows": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_list_clipboard_formats_dispatches_to_backend():
    """list_clipboard_formats calls the correct backend lister."""
    mock_lister = AsyncMock(return_value=["text/plain"])
    with patch("clipboard_mcp.clipboard._get_backend", return_value="x11"):
        with patch.dict("clipboard_mcp.clipboard._FORMAT_LISTERS", {"x11": mock_lister}):
            result = await list_clipboard_formats()

    assert result == ["text/plain"]
    mock_lister.assert_called_once()


# ---------------------------------------------------------------------------
# 14. Image passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_image_prefers_png():
    """clipboard_paste prefers image/png when multiple image formats available."""
    fake_png = b"\x89PNG\r\n\x1a\n"
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/tiff", "image/png"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       return_value=fake_png) as mock_img:
                result = await clipboard_paste()

    mock_img.assert_called_once_with("image/png")
    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_image_falls_back_to_first():
    """clipboard_paste uses first image format when PNG not available."""
    fake_tiff = b"TIFF_DATA"
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/tiff", "image/jpeg"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       return_value=fake_tiff) as mock_img:
                result = await clipboard_paste()

    mock_img.assert_called_once_with("image/tiff")
    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_audio_still_reports_text():
    """clipboard_paste returns text message for audio/video (not image)."""
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["audio/mpeg"]):
            result = await clipboard_paste()

    assert isinstance(result, str)
    assert "binary data" in result
    assert "audio/mpeg" in result


@pytest.mark.asyncio
async def test_paste_image_read_failure_graceful():
    """clipboard_paste handles image read failure gracefully."""
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/png"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       side_effect=ClipboardError("read failed")):
                result = await clipboard_paste()

    # Should fall through to empty clipboard message
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_paste_image_empty_data():
    """clipboard_paste handles empty image data (format listed but no data)."""
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/png"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       return_value=b""):
                result = await clipboard_paste()

    # Empty data should fall through
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 15. Image read backends
# ---------------------------------------------------------------------------

from clipboard_mcp.clipboard import (
    _wayland_read_image,
    _x11_read_image,
    _macos_read_image,
    _windows_read_image,
)


@pytest.mark.asyncio
async def test_wayland_read_image():
    """_wayland_read_image calls wl-paste with correct type flag."""
    fake_data = b"\x89PNG\r\n\x1a\n"
    with patch("clipboard_mcp.clipboard._run_binary", new_callable=AsyncMock, return_value=fake_data) as mock:
        result = await _wayland_read_image("image/png")

    assert result == fake_data
    cmd = mock.call_args[0][0]
    assert cmd == ["wl-paste", "--type", "image/png"]


@pytest.mark.asyncio
async def test_x11_read_image():
    """_x11_read_image calls xclip with correct target for binary."""
    fake_data = b"\x89PNG\r\n\x1a\n"
    with patch("clipboard_mcp.clipboard._run_binary", new_callable=AsyncMock, return_value=fake_data) as mock:
        result = await _x11_read_image("image/png")

    assert result == fake_data
    cmd = mock.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "image/png", "-o"]


@pytest.mark.asyncio
async def test_macos_read_image():
    """_macos_read_image reads base64 from osascript and decodes."""
    import base64
    fake_data = b"\x89PNG\r\n\x1a\n"
    b64_text = base64.b64encode(fake_data).decode()
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=b64_text):
        result = await _macos_read_image("image/png")

    assert result == fake_data


@pytest.mark.asyncio
async def test_macos_read_image_empty():
    """_macos_read_image returns empty bytes when no image available."""
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=""):
        result = await _macos_read_image("image/png")

    assert result == b""


@pytest.mark.asyncio
async def test_windows_read_image():
    """_windows_read_image reads base64 from PowerShell and decodes."""
    import base64
    fake_data = b"\x89PNG\r\n\x1a\n"
    b64_text = base64.b64encode(fake_data).decode()
    with patch("clipboard_mcp.clipboard._run", new_callable=AsyncMock, return_value=b64_text):
        result = await _windows_read_image("image/png")

    assert result == fake_data


@pytest.mark.asyncio
async def test_read_clipboard_image_dispatches():
    """read_clipboard_image dispatches to the correct backend."""
    mock_reader = AsyncMock(return_value=b"IMG")
    with patch("clipboard_mcp.clipboard._get_backend", return_value="x11"):
        with patch.dict("clipboard_mcp.clipboard._IMAGE_READERS", {"x11": mock_reader}):
            result = await read_clipboard_image("image/png")

    assert result == b"IMG"
    mock_reader.assert_called_once_with("image/png")


# ---------------------------------------------------------------------------
# 16. Clipboard copy
# ---------------------------------------------------------------------------

from clipboard_mcp.clipboard import (
    _wayland_write,
    _x11_write,
    _macos_write,
    _windows_write,
)


@pytest.mark.asyncio
async def test_clipboard_copy_success():
    """clipboard_copy writes content and returns confirmation."""
    with patch("clipboard_mcp.server.write_clipboard", new_callable=AsyncMock):
        result = await clipboard_copy("hello world")

    assert "11 characters" in result


@pytest.mark.asyncio
async def test_clipboard_copy_error():
    """clipboard_copy returns error message on failure."""
    with patch("clipboard_mcp.server.write_clipboard",
               side_effect=ClipboardError("write failed")):
        result = await clipboard_copy("hello")

    assert "Error" in result
    assert "write failed" in result


@pytest.mark.asyncio
async def test_wayland_write():
    """_wayland_write pipes content to wl-copy."""
    with patch("clipboard_mcp.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _wayland_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["wl-copy"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_x11_write():
    """_x11_write pipes content to xclip."""
    with patch("clipboard_mcp.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _x11_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["xclip", "-selection", "clipboard"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_macos_write():
    """_macos_write pipes content to pbcopy."""
    with patch("clipboard_mcp.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _macos_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["pbcopy"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_windows_write():
    """_windows_write pipes content to PowerShell Set-Clipboard."""
    with patch("clipboard_mcp.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _windows_write("hello")

    cmd = mock.call_args[0][0]
    assert cmd[0] == "powershell"
    data = mock.call_args[0][1]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_write_clipboard_dispatches():
    """write_clipboard dispatches to the correct backend."""
    mock_writer = AsyncMock()
    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch.dict("clipboard_mcp.clipboard._WRITERS", {"wayland": mock_writer}):
            await write_clipboard("hello")

    mock_writer.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# MIME type parameter handling
# ---------------------------------------------------------------------------

from clipboard_mcp.clipboard import _base_mime_type


def test_base_mime_type_strips_params():
    """_base_mime_type strips everything after the semicolon."""
    assert _base_mime_type("text/plain;charset=utf-8") == "text/plain"
    assert _base_mime_type("image/svg+xml;windows_formatname=\"image/svg+xml\"") == "image/svg+xml"
    assert _base_mime_type("text/plain") == "text/plain"
    assert _base_mime_type("application/json") == "application/json"


@pytest.mark.asyncio
async def test_read_clipboard_falls_back_to_suffixed_mime():
    """read_clipboard retries with the suffixed MIME type when exact match fails."""
    call_log = []

    async def mock_reader(mime_type):
        call_log.append(mime_type)
        if mime_type == "text/plain":
            return ""  # exact match fails
        if mime_type == "text/plain;charset=utf-8":
            return "hello from charset"
        return ""

    async def mock_list():
        return ["text/plain;charset=utf-8", "text/html"]

    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"wayland": mock_reader}):
            with patch.dict("clipboard_mcp.clipboard._FORMAT_LISTERS", {"wayland": mock_list}):
                result = await read_clipboard("text/plain")

    assert result == "hello from charset"
    assert "text/plain" in call_log
    assert "text/plain;charset=utf-8" in call_log


@pytest.mark.asyncio
async def test_read_clipboard_no_fallback_when_exact_match_works():
    """read_clipboard does not list formats when the exact MIME type succeeds."""
    list_called = False

    async def mock_reader(mime_type):
        return "direct content"

    async def mock_list():
        nonlocal list_called
        list_called = True
        return []

    with patch("clipboard_mcp.clipboard._get_backend", return_value="wayland"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"wayland": mock_reader}):
            with patch.dict("clipboard_mcp.clipboard._FORMAT_LISTERS", {"wayland": mock_list}):
                result = await read_clipboard("text/plain")

    assert result == "direct content"
    assert not list_called


@pytest.mark.asyncio
async def test_read_clipboard_no_fallback_on_macos():
    """read_clipboard skips MIME fallback on macOS (not applicable)."""
    async def mock_reader(mime_type):
        return ""

    list_called = False

    async def mock_list():
        nonlocal list_called
        list_called = True
        return ["text/plain;charset=utf-8"]

    with patch("clipboard_mcp.clipboard._get_backend", return_value="macos"):
        with patch.dict("clipboard_mcp.clipboard._READERS", {"macos": mock_reader}):
            with patch.dict("clipboard_mcp.clipboard._FORMAT_LISTERS", {"macos": mock_list}):
                result = await read_clipboard("text/plain")

    assert result == ""
    assert not list_called


@pytest.mark.asyncio
async def test_read_clipboard_image_falls_back_to_suffixed_mime():
    """read_clipboard_image retries with suffixed MIME type on fallback."""
    async def mock_reader(mime_type):
        if mime_type == "image/png":
            return b""
        if mime_type == "image/png;charset=binary":
            return b"\x89PNG"
        return b""

    async def mock_list():
        return ["image/png;charset=binary"]

    with patch("clipboard_mcp.clipboard._get_backend", return_value="x11"):
        with patch.dict("clipboard_mcp.clipboard._IMAGE_READERS", {"x11": mock_reader}):
            with patch.dict("clipboard_mcp.clipboard._FORMAT_LISTERS", {"x11": mock_list}):
                result = await read_clipboard_image("image/png")

    assert result == b"\x89PNG"


@pytest.mark.asyncio
async def test_read_raw_allows_svg_with_params():
    """clipboard_read_raw allows image/svg+xml with parameter suffix."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="50"/></svg>'
    with patch("clipboard_mcp.server.read_clipboard", new_callable=AsyncMock, return_value=svg):
        result = await clipboard_read_raw(
            mime_type='image/svg+xml;windows_formatname="image/svg+xml"'
        )

    assert "circle" in result
    assert "Cannot read binary" not in result


@pytest.mark.asyncio
async def test_read_raw_rejects_binary_with_params():
    """clipboard_read_raw still rejects binary MIME types that have parameter suffixes."""
    result = await clipboard_read_raw(mime_type="image/png;charset=binary")

    assert "Cannot read binary" in result


@pytest.mark.asyncio
async def test_paste_image_prefers_png_with_params():
    """clipboard_paste prefers PNG even when format has parameter suffix."""
    fake_png = b"\x89PNG\r\n\x1a\n"
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/tiff", "image/png;charset=binary"]):
            with patch("clipboard_mcp.server.read_clipboard_image",
                       return_value=fake_png) as mock_img:
                result = await clipboard_paste()

    # Should use the suffixed PNG format, not fall back to tiff
    mock_img.assert_called_once_with("image/png;charset=binary")
    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_text_with_suffixed_mime():
    """clipboard_paste returns text content when clipboard has text/plain;charset=utf-8.

    This is the core bug scenario: Claude Desktop puts text on the clipboard with
    MIME type text/plain;charset=utf-8, and clipboard_paste should still read it.
    """
    # read_clipboard already handles fallback resolution in clipboard.py,
    # so from server.py's perspective, the mock just returns the content.
    with patch("clipboard_mcp.server.read_clipboard",
               side_effect=_mock_read(html="", text="Hello from Claude")):
        result = await clipboard_paste()

    assert "Hello from Claude" in result
