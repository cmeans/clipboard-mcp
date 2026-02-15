"""Tests for the MCP server tools and clipboard backend.

All clipboard access is mocked — no actual system clipboard needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from clipboard_mcp.clipboard import (
    ClipboardError,
    read_clipboard,
    list_clipboard_formats,
    _find_wayland_display,
    _wayland_env,
    _detect_backend,
)
from clipboard_mcp.server import clipboard_paste, clipboard_read_raw, clipboard_list_formats


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
        result = await clipboard_paste()

    assert "Clipboard is empty" in result


@pytest.mark.asyncio
async def test_paste_both_fail():
    """clipboard_paste returns empty message when both reads fail."""
    with patch("clipboard_mcp.server.read_clipboard", side_effect=_mock_read_error()):
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
    assert "not currently supported" in result


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


# ---------------------------------------------------------------------------
# 6. clipboard_paste with binary clipboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_detects_image_clipboard():
    """clipboard_paste reports image formats when clipboard has no text."""
    with patch("clipboard_mcp.server.read_clipboard", _mock_read(html="", text="")):
        with patch("clipboard_mcp.server.list_clipboard_formats",
                   return_value=["image/png", "image/tiff"]):
            result = await clipboard_paste()

    assert "binary data" in result
    assert "image/png" in result
    assert "not currently supported" in result


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
