"""Tests for the MCP server tools and clipboard backend.

All clipboard access is mocked — no actual system clipboard needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp.utilities.types import Image

from mcp_clipboard.clipboard import (
    ClipboardError,
    _detect_backend,
    _find_wayland_display,
    _macos_write_typed,
    _wayland_env,
    _wayland_write_typed,
    _windows_html_clipboard_wrap,
    _windows_write_typed,
    _x11_write_typed,
    list_clipboard_formats,
    read_clipboard,
    read_clipboard_image,
    write_clipboard,
    write_clipboard_typed,
)
from mcp_clipboard.server import (
    _load_icons,
    _load_instruction,
    clipboard_copy,
    clipboard_list_formats,
    clipboard_paste,
    clipboard_read_raw,
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
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows \u00d7 3 columns" in result
    assert "| Name" in result
    assert "| Alice" in result
    assert "| Bob" in result


@pytest.mark.asyncio
async def test_paste_table_json():
    """clipboard_paste returns valid JSON for tables when requested."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="json")

    assert "3 rows \u00d7 3 columns" in result
    import json

    json_part = result.split("\n\n", 1)[1]
    data = json.loads(json_part)
    assert len(data) == 2
    assert data[0]["Name"] == "Alice"


@pytest.mark.asyncio
async def test_paste_table_csv():
    """clipboard_paste returns CSV for tables when requested."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="csv")

    assert "3 rows \u00d7 3 columns" in result
    assert '"Name","Age","City"' in result
    assert '"Alice","30","Portland"' in result


@pytest.mark.asyncio
async def test_paste_format_case_insensitive():
    """clipboard_paste accepts output_format in any case."""
    for fmt in ("JSON", "Json", "jSoN", " json ", "CSV", "Csv", "MARKDOWN"):
        with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
            result = await clipboard_paste(output_format=fmt)
        assert "3 rows \u00d7 3 columns" in result, f"Failed for format {fmt!r}"


@pytest.mark.asyncio
async def test_paste_format_invalid():
    """clipboard_paste returns error message for unknown format."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="xml")
    assert "Unknown output_format" in result


@pytest.mark.asyncio
async def test_paste_with_schema():
    """clipboard_paste appends column-type schema when include_schema=True."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="markdown", include_schema=True)

    assert "3 rows \u00d7 3 columns" in result
    assert "Column types" in result
    assert "| Name" in result
    assert "| Age" in result
    # Age column should be integer
    assert "integer" in result


@pytest.mark.asyncio
async def test_paste_without_schema_default():
    """clipboard_paste does not include schema by default."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="markdown")

    assert "Column types" not in result


@pytest.mark.asyncio
async def test_paste_schema_not_appended_for_non_table():
    """include_schema is ignored when clipboard has no table."""
    with patch(
        "mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text="hello world")
    ):
        result = await clipboard_paste(output_format="markdown", include_schema=True)

    assert "Column types" not in result
    assert "hello world" in result


@pytest.mark.asyncio
async def test_paste_slack_format():
    """clipboard_paste returns Slack-formatted table."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="slack")

    assert result.startswith("Found table:")
    assert "```" in result
    assert "|" not in result  # no pipe characters anywhere
    assert "Name" in result


@pytest.mark.asyncio
async def test_paste_jira_format():
    """clipboard_paste returns Jira wiki markup."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="jira")

    assert "||Name||" in result
    assert "|Alice|" in result


@pytest.mark.asyncio
async def test_paste_confluence_format():
    """clipboard_paste returns Confluence wiki markup (same as Jira)."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result_jira = await clipboard_paste(output_format="jira")
        result_confluence = await clipboard_paste(output_format="confluence")

    # Strip the "Found table: N rows \u00d7 N columns" prefix — it's identical
    assert result_jira == result_confluence


@pytest.mark.asyncio
async def test_paste_html_format():
    """clipboard_paste returns HTML table markup."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="html")

    assert "<table>" in result
    assert "<th>Name</th>" in result
    assert "<td>Alice</td>" in result


@pytest.mark.asyncio
async def test_paste_notion_format():
    """clipboard_paste returns GFM pipe table for Notion."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result_notion = await clipboard_paste(output_format="notion")
        result_markdown = await clipboard_paste(output_format="markdown")

    assert result_notion == result_markdown


@pytest.mark.asyncio
async def test_paste_format_invalid_unknown():
    """clipboard_paste rejects formats not in the valid set."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html=SAMPLE_HTML)):
        result = await clipboard_paste(output_format="xml")

    assert "Unknown output_format" in result
    assert "slack" in result  # error message lists valid options


# ---------------------------------------------------------------------------
# 2. clipboard_paste: TSV fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_tsv_fallback():
    """clipboard_paste falls back to TSV when no HTML is available."""
    with patch(
        "mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text=SAMPLE_TSV)
    ):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows \u00d7 3 columns" in result
    assert "| Name" in result
    assert "| Alice" in result


@pytest.mark.asyncio
async def test_paste_tsv_when_html_errors():
    """clipboard_paste falls back to TSV when HTML read raises an error."""

    async def _mixed_read(mime_type: str = "text/plain") -> str:
        if mime_type == "text/html":
            raise ClipboardError("No HTML available")
        return SAMPLE_TSV

    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mixed_read):
        result = await clipboard_paste(output_format="markdown")

    assert "3 rows \u00d7 3 columns" in result
    assert "| Alice" in result


# ---------------------------------------------------------------------------
# 3. clipboard_paste: non-tabular content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_plain_text():
    """clipboard_paste returns plain text when no table is found."""
    with patch(
        "mcp_clipboard.server.read_clipboard",
        side_effect=_mock_read(html="", text="Hello, this is plain text."),
    ):
        result = await clipboard_paste()

    assert "Clipboard content:" in result
    assert "Hello, this is plain text." in result


@pytest.mark.asyncio
async def test_paste_json_content():
    """clipboard_paste detects and pretty-prints JSON."""
    json_text = '{"name": "Alice", "age": 30}'
    with patch(
        "mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text=json_text)
    ):
        result = await clipboard_paste()

    assert "Clipboard contains JSON:" in result
    assert "```json" in result
    assert '"name": "Alice"' in result


@pytest.mark.asyncio
async def test_paste_url():
    """clipboard_paste detects and returns URLs cleanly."""
    with patch(
        "mcp_clipboard.server.read_clipboard",
        side_effect=_mock_read(html="", text="https://example.com/path?q=1"),
    ):
        result = await clipboard_paste()

    assert "Clipboard contains URL:" in result
    assert "https://example.com/path?q=1" in result


@pytest.mark.asyncio
async def test_paste_code_snippet():
    """clipboard_paste detects code and wraps it in a code block."""
    code = "def hello():\n    print('hello world')\n\nhello()"
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text=code)):
        result = await clipboard_paste()

    assert "Clipboard contains code:" in result
    assert "```" in result
    assert "def hello():" in result


@pytest.mark.asyncio
async def test_paste_html_without_table():
    """clipboard_paste extracts text from HTML that has no table."""
    html = "<p>This is a <b>rich text</b> paragraph.</p><p>Second paragraph.</p>"
    with patch(
        "mcp_clipboard.server.read_clipboard",
        side_effect=_mock_read(html=html, text="This is a rich text paragraph. Second paragraph."),
    ):
        result = await clipboard_paste()

    assert "rich text" in result
    assert "Second paragraph" in result


@pytest.mark.asyncio
async def test_paste_empty_clipboard():
    """clipboard_paste returns empty message when clipboard is empty."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "Clipboard is empty" in result


@pytest.mark.asyncio
async def test_paste_both_fail():
    """clipboard_paste returns empty message when both reads fail."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read_error()):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "Clipboard is empty" in result


@pytest.mark.asyncio
async def test_paste_large_content_truncated():
    """clipboard_paste truncates content over 50KB and enforces the size bound."""
    huge = "x" * 100_000
    with patch("mcp_clipboard.server.read_clipboard", side_effect=_mock_read(html="", text=huge)):
        result = await clipboard_paste()

    assert "truncated" in result.lower()
    # The truncation message adds a small suffix; bound must stay well below input size.
    assert len(result) < 60_000, f"expected bounded output, got {len(result):,} chars"


# ---------------------------------------------------------------------------
# 4. clipboard_list_formats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_formats_with_html():
    """clipboard_list_formats highlights HTML availability."""
    mock_formats = ["text/html", "text/plain", "UTF8_STRING", "TARGETS"]

    with patch("mcp_clipboard.server.list_clipboard_formats", return_value=mock_formats):
        result = await clipboard_list_formats()

    assert "4 format(s)" in result
    assert "text/html" in result
    assert "✓ HTML available" in result
    assert "✓ Plain text available" in result


@pytest.mark.asyncio
async def test_list_formats_text_only():
    """clipboard_list_formats works when only plain text is available."""
    mock_formats = ["text/plain", "UTF8_STRING"]

    with patch("mcp_clipboard.server.list_clipboard_formats", return_value=mock_formats):
        result = await clipboard_list_formats()

    assert "2 format(s)" in result
    assert "✓ Plain text available" in result
    # Should NOT have the HTML highlight
    assert "HTML available" not in result


@pytest.mark.asyncio
async def test_list_formats_empty():
    """clipboard_list_formats handles empty clipboard."""
    with patch("mcp_clipboard.server.list_clipboard_formats", return_value=[]):
        result = await clipboard_list_formats()

    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_list_formats_error():
    """clipboard_list_formats handles ClipboardError gracefully."""
    with patch(
        "mcp_clipboard.server.list_clipboard_formats",
        side_effect=ClipboardError("No clipboard tool"),
    ):
        result = await clipboard_list_formats()

    assert "Error" in result
    assert "No clipboard tool" in result


# ---------------------------------------------------------------------------
# 5. clipboard backend error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_clipboard_command_not_found():
    """read_clipboard raises ClipboardError when the clipboard tool isn't installed."""
    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch(
            "mcp_clipboard.clipboard._run",
            side_effect=ClipboardError("Command not found: wl-paste"),
        ):
            with pytest.raises(ClipboardError, match="Command not found"):
                await read_clipboard("text/html")


@pytest.mark.asyncio
async def test_read_clipboard_timeout():
    """read_clipboard raises ClipboardError on timeout."""
    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch(
            "mcp_clipboard.clipboard._run",
            side_effect=ClipboardError("Clipboard command timed out"),
        ):
            with pytest.raises(ClipboardError, match="timed out"):
                await read_clipboard("text/html")


@pytest.mark.asyncio
async def test_read_raw_returns_content():
    """clipboard_read_raw returns the raw content for a given MIME type."""
    with patch(
        "mcp_clipboard.server.read_clipboard", return_value="<table><tr><td>hi</td></tr></table>"
    ):
        result = await clipboard_read_raw(mime_type="text/html")

    assert "<table>" in result
    assert "chars" in result


@pytest.mark.asyncio
async def test_read_raw_truncates_large_content():
    """clipboard_read_raw truncates very large clipboard content."""
    huge = "x" * 100_000
    with patch("mcp_clipboard.server.read_clipboard", return_value=huge):
        result = await clipboard_read_raw(mime_type="text/plain")

    assert "truncated" in result.lower()
    # Should not return the full 100k
    assert len(result) < 60_000


@pytest.mark.asyncio
async def test_read_raw_error():
    """clipboard_read_raw handles ClipboardError gracefully."""
    with patch("mcp_clipboard.server.read_clipboard", side_effect=ClipboardError("fail")):
        result = await clipboard_read_raw(mime_type="text/html")

    assert "Error" in result
    assert "fail" in result


@pytest.mark.asyncio
async def test_read_raw_empty():
    """clipboard_read_raw handles empty content for a MIME type."""
    with patch("mcp_clipboard.server.read_clipboard", return_value=""):
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
    with patch("mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=svg):
        result = await clipboard_read_raw(mime_type="image/svg+xml")

    assert "circle" in result
    assert "Cannot read binary" not in result


@pytest.mark.asyncio
async def test_read_raw_allows_application_json():
    """clipboard_read_raw allows application/json as text-readable."""
    json_str = '{"key": "value"}'
    with patch(
        "mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=json_str
    ):
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
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats", return_value=["image/png", "image/tiff"]
        ):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=fake_png):
                result = await clipboard_paste()

    assert isinstance(result, Image)
    assert result.data == fake_png


@pytest.mark.asyncio
async def test_paste_empty_clipboard_no_binary():
    """clipboard_paste returns 'empty' when clipboard has no text and no binary."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# 7. Wayland auto-detection
# ---------------------------------------------------------------------------


def _fake_runtime_dir(tmp_path, sockets=("wayland-0",)):
    """Create fake Wayland socket files in a temp dir and return the path."""
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
    with patch.dict(
        "os.environ",
        {
            "WAYLAND_DISPLAY": "wayland-0",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        },
        clear=False,
    ):
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
    _fake_runtime_dir(tmp_path)
    with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
        import os

        os.environ.pop("XDG_RUNTIME_DIR", None)
        with patch("mcp_clipboard.clipboard.os.getuid", return_value=1000):
            # Point the fallback path at our tmp_path with real sockets
            with patch("mcp_clipboard.clipboard.Path") as mock_path:
                mock_path.return_value.is_dir.return_value = True
                # Use the real tmp_path for the env value
                env = _wayland_env()

    assert env is not None
    assert "XDG_RUNTIME_DIR" in env


def test_wayland_env_injects_both_when_neither_set(tmp_path):
    """_wayland_env injects both vars when neither is set (Claude Desktop scenario)."""
    _fake_runtime_dir(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_RUNTIME_DIR", None)
        with patch("mcp_clipboard.clipboard.os.getuid", return_value=1000):
            with patch("mcp_clipboard.clipboard.Path") as mock_path:
                # Make Path(xdg_runtime).is_dir() return True
                mock_path.return_value.is_dir.return_value = True
                # But use real _find_wayland_display with the actual tmp_path
                with patch(
                    "mcp_clipboard.clipboard._find_wayland_display", return_value="wayland-0"
                ):
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
        with patch("mcp_clipboard.clipboard.platform.system", return_value="Linux"):
            with patch("mcp_clipboard.clipboard.shutil.which", return_value="/usr/bin/wl-paste"):
                # Clear cached backend
                import mcp_clipboard.clipboard as cb

                cb._backend = None
                result = _detect_backend()

    assert result == "wayland"


def test_detect_backend_prefers_env_var_over_socket():
    """_detect_backend uses WAYLAND_DISPLAY env var without needing socket scan."""
    with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
        with patch("mcp_clipboard.clipboard.platform.system", return_value="Linux"):
            with patch("mcp_clipboard.clipboard.shutil.which", return_value="/usr/bin/wl-paste"):
                import mcp_clipboard.clipboard as cb

                cb._backend = None
                result = _detect_backend()

    assert result == "wayland"


# ---------------------------------------------------------------------------
# 8. macOS backend
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import (
    _macos_list_formats,
    _macos_read,
    _windows_list_formats,
    _windows_read,
    _x11_list_formats,
    _x11_read,
)


@pytest.mark.asyncio
async def test_macos_read_html():
    """_macos_read uses osascript for text/html."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>"
    ) as mock_run:
        result = await _macos_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "osascript"


@pytest.mark.asyncio
async def test_macos_read_plain():
    """_macos_read uses pbpaste for text/plain."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="hello"
    ) as mock_run:
        result = await _macos_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["pbpaste"]


@pytest.mark.asyncio
async def test_macos_read_unsupported_returns_empty():
    """_macos_read returns empty string for unsupported MIME types."""
    result = await _macos_read("text/xml")
    assert result == ""


@pytest.mark.asyncio
async def test_macos_read_rtf():
    """_macos_read uses osascript for text/rtf."""
    rtf_content = r"{\rtf1\ansi Hello, {\b world}!}"
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=rtf_content
    ) as mock_run:
        result = await _macos_read("text/rtf")

    assert result == rtf_content
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "osascript"
    assert "public.rtf" in mock_run.call_args[0][0][-1]


@pytest.mark.asyncio
async def test_macos_list_formats_maps_uti_to_mime():
    """_macos_list_formats maps known UTIs to MIME types."""
    raw_output = "public.html\npublic.utf8-plain-text\npublic.png\n"
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _macos_list_formats()

    assert result == ["text/html", "text/plain", "image/png"]


@pytest.mark.asyncio
async def test_macos_list_formats_passthrough_unknown():
    """_macos_list_formats passes through unknown UTIs as-is."""
    raw_output = "public.html\ncom.apple.something-custom\n"
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _macos_list_formats()

    assert result == ["text/html", "com.apple.something-custom"]


# ---------------------------------------------------------------------------
# 9. Windows backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_windows_read_html():
    """_windows_read uses PowerShell HTML clipboard for text/html."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>"
    ) as mock_run:
        result = await _windows_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "powershell"
    assert "Html" in cmd[-1]


@pytest.mark.asyncio
async def test_windows_read_plain():
    """_windows_read uses Get-Clipboard for text/plain."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="hello"
    ) as mock_run:
        result = await _windows_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert "Get-Clipboard" in cmd[-1]


@pytest.mark.asyncio
async def test_windows_read_unsupported_returns_empty():
    """_windows_read returns empty string for unsupported MIME types."""
    result = await _windows_read("text/xml")
    assert result == ""


@pytest.mark.asyncio
async def test_windows_read_rtf():
    """_windows_read uses PowerShell RTF clipboard for text/rtf."""
    rtf_content = r"{\rtf1\ansi Hello, {\b world}!}"
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=rtf_content
    ) as mock_run:
        result = await _windows_read("text/rtf")

    assert result == rtf_content
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "powershell"
    assert "Rtf" in cmd[-1]


@pytest.mark.asyncio
async def test_windows_list_formats_maps_names_to_mime():
    """_windows_list_formats maps known Windows format names to MIME types."""
    raw_output = "HTML Format\nText\nUnicodeText\nPNG\n"
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _windows_list_formats()

    assert result == ["text/html", "text/plain", "text/plain", "image/png"]


@pytest.mark.asyncio
async def test_windows_list_formats_passthrough_unknown():
    """_windows_list_formats passes through unknown format names as-is."""
    raw_output = "HTML Format\nSystem.String\n"
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
        result = await _windows_list_formats()

    assert result == ["text/html", "System.String"]


# ---------------------------------------------------------------------------
# 10. X11 backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_x11_read_html():
    """_x11_read calls xclip with correct target for text/html."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="<b>hi</b>"
    ) as mock_run:
        result = await _x11_read("text/html")

    assert result == "<b>hi</b>"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "text/html", "-o"]


@pytest.mark.asyncio
async def test_x11_read_plain():
    """_x11_read calls xclip with correct target for text/plain."""
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value="hello"
    ) as mock_run:
        result = await _x11_read("text/plain")

    assert result == "hello"
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "text/plain", "-o"]


@pytest.mark.asyncio
async def test_x11_list_formats():
    """_x11_list_formats calls xclip with TARGETS and parses output."""
    raw_output = "text/html\ntext/plain\nimage/png\n"
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output
    ) as mock_run:
        result = await _x11_list_formats()

    assert result == ["text/html", "text/plain", "image/png"]
    cmd = mock_run.call_args[0][0]
    assert cmd == ["xclip", "-selection", "clipboard", "-target", "TARGETS", "-o"]


@pytest.mark.asyncio
async def test_x11_list_formats_strips_whitespace():
    """_x11_list_formats strips whitespace and skips blank lines."""
    raw_output = "  text/html  \n\n  text/plain  \n"
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=raw_output):
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
# 11b. _load_icons()
# ---------------------------------------------------------------------------


def test_load_icons_returns_icons():
    """_load_icons returns Icon objects with GitHub URLs for light and dark themes."""
    icons = _load_icons()
    assert len(icons) == 2
    themes = {icon.theme for icon in icons}
    assert themes == {"light", "dark"}
    for icon in icons:
        assert icon.src.startswith("https://raw.githubusercontent.com/")
        assert icon.src.endswith(".svg")
        assert icon.mimeType == "image/svg+xml"


# ---------------------------------------------------------------------------
# 12. _detect_backend() platform coverage
# ---------------------------------------------------------------------------


def test_detect_backend_darwin():
    """_detect_backend returns 'macos' on Darwin."""
    with patch("mcp_clipboard.clipboard.platform.system", return_value="Darwin"):
        import mcp_clipboard.clipboard as cb

        cb._backend = None
        result = _detect_backend()

    assert result == "macos"


def test_detect_backend_windows():
    """_detect_backend returns 'windows' on Windows."""
    with patch("mcp_clipboard.clipboard.platform.system", return_value="Windows"):
        import mcp_clipboard.clipboard as cb

        cb._backend = None
        result = _detect_backend()

    assert result == "windows"


def test_detect_backend_unsupported():
    """_detect_backend raises ClipboardError on unsupported platforms."""
    with patch("mcp_clipboard.clipboard.platform.system", return_value="FreeBSD"):
        import mcp_clipboard.clipboard as cb

        cb._backend = None
        with pytest.raises(ClipboardError, match="Unsupported platform: FreeBSD"):
            _detect_backend()


def test_detect_backend_linux_no_tools():
    """_detect_backend raises ClipboardError when no clipboard tools are installed."""
    with patch("mcp_clipboard.clipboard.platform.system", return_value="Linux"):
        with patch("mcp_clipboard.clipboard.shutil.which", return_value=None):
            with patch.dict("os.environ", {}, clear=True):
                import mcp_clipboard.clipboard as cb

                cb._backend = None
                with pytest.raises(ClipboardError, match="No clipboard tool found"):
                    _detect_backend()


def test_get_backend_env_override():
    """MCP_CLIPBOARD_BACKEND env var overrides auto-detection."""
    import mcp_clipboard.clipboard as cb

    cb._backend = None
    with patch.dict("os.environ", {"MCP_CLIPBOARD_BACKEND": "x11"}):
        result = cb._get_backend()
    assert result == "x11"
    cb._backend = None  # reset


def test_get_backend_env_override_invalid():
    """MCP_CLIPBOARD_BACKEND with invalid value raises ClipboardError."""
    import mcp_clipboard.clipboard as cb

    cb._backend = None
    with patch.dict("os.environ", {"MCP_CLIPBOARD_BACKEND": "invalid"}):
        with pytest.raises(ClipboardError, match="Invalid MCP_CLIPBOARD_BACKEND"):
            cb._get_backend()
    cb._backend = None  # reset


def test_get_backend_auto_detect_when_no_override():
    """Without MCP_CLIPBOARD_BACKEND, _get_backend uses auto-detection."""
    import mcp_clipboard.clipboard as cb

    cb._backend = None
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("MCP_CLIPBOARD_BACKEND", None)
        with patch("mcp_clipboard.clipboard._detect_backend", return_value="wayland"):
            result = cb._get_backend()
    assert result == "wayland"
    cb._backend = None  # reset


# ---------------------------------------------------------------------------
# 13. Backend dispatch (read_clipboard / list_clipboard_formats)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_wayland():
    """read_clipboard calls the wayland reader when backend is wayland."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"wayland": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_x11():
    """read_clipboard calls the x11 reader when backend is x11."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("mcp_clipboard.clipboard._get_backend", return_value="x11"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"x11": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_macos():
    """read_clipboard calls the macos reader when backend is macos."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("mcp_clipboard.clipboard._get_backend", return_value="macos"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"macos": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_read_clipboard_dispatches_to_windows():
    """read_clipboard calls the windows reader when backend is windows."""
    mock_reader = AsyncMock(return_value="hello")
    with patch("mcp_clipboard.clipboard._get_backend", return_value="windows"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"windows": mock_reader}):
            result = await read_clipboard("text/plain")

    assert result == "hello"
    mock_reader.assert_called_once_with("text/plain")


@pytest.mark.asyncio
async def test_list_clipboard_formats_dispatches_to_backend():
    """list_clipboard_formats calls the correct backend lister."""
    mock_lister = AsyncMock(return_value=["text/plain"])
    with patch("mcp_clipboard.clipboard._get_backend", return_value="x11"):
        with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"x11": mock_lister}):
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
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats", return_value=["image/tiff", "image/png"]
        ):
            with patch(
                "mcp_clipboard.server.read_clipboard_image", return_value=fake_png
            ) as mock_img:
                result = await clipboard_paste()

    mock_img.assert_called_once_with("image/png")
    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_image_falls_back_to_first():
    """clipboard_paste uses first image format when PNG not available."""
    fake_tiff = b"TIFF_DATA"
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats", return_value=["image/tiff", "image/jpeg"]
        ):
            with patch(
                "mcp_clipboard.server.read_clipboard_image", return_value=fake_tiff
            ) as mock_img:
                result = await clipboard_paste()

    mock_img.assert_called_once_with("image/tiff")
    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_audio_still_reports_text():
    """clipboard_paste returns text message for audio/video (not image)."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["audio/mpeg"]):
            result = await clipboard_paste()

    assert isinstance(result, str)
    assert "binary data" in result
    assert "audio/mpeg" in result


@pytest.mark.asyncio
async def test_paste_image_read_failure_graceful():
    """clipboard_paste handles image read failure gracefully."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["image/png"]):
            with patch(
                "mcp_clipboard.server.read_clipboard_image",
                side_effect=ClipboardError("read failed"),
            ):
                result = await clipboard_paste()

    # Should fall through to empty clipboard message
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_paste_image_empty_data():
    """clipboard_paste handles empty image data (format listed but no data)."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["image/png"]):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=b""):
                result = await clipboard_paste()

    # Empty data should fall through
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 15. Image read backends
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import (
    _macos_read_image,
    _wayland_read_image,
    _windows_read_image,
    _x11_read_image,
)


@pytest.mark.asyncio
async def test_wayland_read_image():
    """_wayland_read_image calls wl-paste with correct type flag."""
    fake_data = b"\x89PNG\r\n\x1a\n"
    with patch(
        "mcp_clipboard.clipboard._run_binary", new_callable=AsyncMock, return_value=fake_data
    ) as mock:
        result = await _wayland_read_image("image/png")

    assert result == fake_data
    cmd = mock.call_args[0][0]
    assert cmd == ["wl-paste", "--type", "image/png"]


@pytest.mark.asyncio
async def test_x11_read_image():
    """_x11_read_image calls xclip with correct target for binary."""
    fake_data = b"\x89PNG\r\n\x1a\n"
    with patch(
        "mcp_clipboard.clipboard._run_binary", new_callable=AsyncMock, return_value=fake_data
    ) as mock:
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
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=b64_text):
        result = await _macos_read_image("image/png")

    assert result == fake_data


@pytest.mark.asyncio
async def test_macos_read_image_empty():
    """_macos_read_image returns empty bytes when no image available."""
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=""):
        result = await _macos_read_image("image/png")

    assert result == b""


@pytest.mark.asyncio
async def test_windows_read_image():
    """_windows_read_image reads base64 from PowerShell and decodes."""
    import base64

    fake_data = b"\x89PNG\r\n\x1a\n"
    b64_text = base64.b64encode(fake_data).decode()
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=b64_text):
        result = await _windows_read_image("image/png")

    assert result == fake_data


@pytest.mark.asyncio
async def test_read_clipboard_image_dispatches():
    """read_clipboard_image dispatches to the correct backend."""
    mock_reader = AsyncMock(return_value=b"IMG")
    with patch("mcp_clipboard.clipboard._get_backend", return_value="x11"):
        with patch.dict("mcp_clipboard.clipboard._IMAGE_READERS", {"x11": mock_reader}):
            result = await read_clipboard_image("image/png")

    assert result == b"IMG"
    mock_reader.assert_called_once_with("image/png")


# ---------------------------------------------------------------------------
# 16. Clipboard copy
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import (
    _macos_write,
    _wayland_write,
    _windows_write,
    _x11_write,
)


@pytest.mark.asyncio
async def test_clipboard_copy_success():
    """clipboard_copy writes content and returns confirmation."""
    with patch("mcp_clipboard.server.write_clipboard", new_callable=AsyncMock):
        result = await clipboard_copy("hello world")

    assert "11 characters" in result


@pytest.mark.asyncio
async def test_clipboard_copy_error():
    """clipboard_copy returns error message on failure."""
    with patch("mcp_clipboard.server.write_clipboard", side_effect=ClipboardError("write failed")):
        result = await clipboard_copy("hello")

    assert "Error" in result
    assert "write failed" in result


@pytest.mark.asyncio
async def test_wayland_write():
    """_wayland_write pipes content to wl-copy."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _wayland_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["wl-copy"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_x11_write():
    """_x11_write pipes content to xclip."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _x11_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["xclip", "-selection", "clipboard"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_macos_write():
    """_macos_write pipes content to pbcopy."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _macos_write("hello")

    cmd = mock.call_args[0][0]
    data = mock.call_args[0][1]
    assert cmd == ["pbcopy"]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_windows_write():
    """_windows_write pipes content to PowerShell Set-Clipboard."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _windows_write("hello")

    cmd = mock.call_args[0][0]
    assert cmd[0] == "powershell"
    data = mock.call_args[0][1]
    assert data == b"hello"


@pytest.mark.asyncio
async def test_write_clipboard_dispatches():
    """write_clipboard dispatches to the correct backend."""
    mock_writer = AsyncMock()
    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._WRITERS", {"wayland": mock_writer}):
            await write_clipboard("hello")

    mock_writer.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# MIME type parameter handling
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import base_mime_type


def test_base_mime_type_strips_params():
    """base_mime_type strips everything after the semicolon."""
    assert base_mime_type("text/plain;charset=utf-8") == "text/plain"
    assert base_mime_type('image/svg+xml;windows_formatname="image/svg+xml"') == "image/svg+xml"
    assert base_mime_type("text/plain") == "text/plain"
    assert base_mime_type("application/json") == "application/json"


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

    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"wayland": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"wayland": mock_list}):
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

    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"wayland": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"wayland": mock_list}):
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

    with patch("mcp_clipboard.clipboard._get_backend", return_value="macos"):
        with patch.dict("mcp_clipboard.clipboard._READERS", {"macos": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"macos": mock_list}):
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

    with patch("mcp_clipboard.clipboard._get_backend", return_value="x11"):
        with patch.dict("mcp_clipboard.clipboard._IMAGE_READERS", {"x11": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"x11": mock_list}):
                result = await read_clipboard_image("image/png")

    assert result == b"\x89PNG"


@pytest.mark.asyncio
async def test_read_raw_allows_svg_with_params():
    """clipboard_read_raw allows image/svg+xml with parameter suffix."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="50"/></svg>'
    with patch("mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=svg):
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
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats",
            return_value=["image/tiff", "image/png;charset=binary"],
        ):
            with patch(
                "mcp_clipboard.server.read_clipboard_image", return_value=fake_png
            ) as mock_img:
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
    with patch(
        "mcp_clipboard.server.read_clipboard",
        side_effect=_mock_read(html="", text="Hello from Claude"),
    ):
        result = await clipboard_paste()

    assert "Hello from Claude" in result


# ---------------------------------------------------------------------------
# 18. _run_binary() error handling
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import _run_binary


@pytest.mark.asyncio
async def test_run_binary_file_not_found():
    """_run_binary raises ClipboardError when the command is not found."""
    with pytest.raises(ClipboardError, match="Command not found: nonexistent_cmd"):
        await _run_binary(["nonexistent_cmd"])


@pytest.mark.asyncio
async def test_run_binary_timeout():
    """_run_binary raises ClipboardError on timeout."""
    with pytest.raises(ClipboardError, match="timed out"):
        await _run_binary(["sleep", "10"], timeout=0.1)


@pytest.mark.asyncio
async def test_run_binary_exit_code_1_returns_empty():
    """_run_binary returns empty bytes for exit code 1 (format not available)."""
    result = await _run_binary(["sh", "-c", "exit 1"])
    assert result == b""


@pytest.mark.asyncio
async def test_run_binary_exit_code_2_raises():
    """_run_binary raises ClipboardError for exit codes > 1."""
    with pytest.raises(ClipboardError, match="rc=2"):
        await _run_binary(["sh", "-c", "echo err >&2; exit 2"])


@pytest.mark.asyncio
async def test_run_binary_returns_raw_bytes():
    """_run_binary returns raw bytes from stdout."""
    result = await _run_binary(["printf", "\\x89PNG"])
    assert result == b"\x89PNG"


# ---------------------------------------------------------------------------
# 19. _run_with_stdin() error handling
# ---------------------------------------------------------------------------

from mcp_clipboard.clipboard import _run_with_stdin


@pytest.mark.asyncio
async def test_run_with_stdin_file_not_found():
    """_run_with_stdin raises ClipboardError when the command is not found."""
    with pytest.raises(ClipboardError, match="Command not found: nonexistent_cmd"):
        await _run_with_stdin(["nonexistent_cmd"], b"data")


@pytest.mark.asyncio
async def test_run_with_stdin_timeout():
    """_run_with_stdin raises ClipboardError on timeout."""
    with pytest.raises(ClipboardError, match="timed out"):
        await _run_with_stdin(["sleep", "10"], b"data", timeout=0.1)


@pytest.mark.asyncio
async def test_run_with_stdin_nonzero_exit_raises():
    """_run_with_stdin raises ClipboardError on any non-zero exit code (including 1)."""
    with pytest.raises(ClipboardError, match="Clipboard write failed"):
        await _run_with_stdin(["sh", "-c", "exit 1"], b"data")


@pytest.mark.asyncio
async def test_run_with_stdin_success():
    """_run_with_stdin succeeds when command exits 0."""
    # cat reads stdin and writes to stdout (which is DEVNULL), exits 0
    await _run_with_stdin(["cat"], b"hello")


@pytest.mark.asyncio
async def test_run_with_stdin_includes_stderr_in_debug():
    """_run_with_stdin includes stderr in error message when debug is on."""
    with patch.dict("os.environ", {"MCP_CLIPBOARD_DEBUG": "1"}):
        with pytest.raises(ClipboardError, match=r"stderr:.*error output"):
            await _run_with_stdin(["sh", "-c", "echo 'error output' >&2; exit 1"], b"data")


@pytest.mark.asyncio
async def test_run_with_stdin_no_stderr_without_debug():
    """_run_with_stdin omits stderr from error message when debug is off."""
    with patch.dict("os.environ", {"MCP_CLIPBOARD_DEBUG": "0"}):
        with pytest.raises(ClipboardError, match="Clipboard write failed") as exc_info:
            await _run_with_stdin(["sh", "-c", "echo 'error output' >&2; exit 1"], b"data")
        assert "stderr:" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# 20. clipboard_paste() image format and error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paste_image_format_field_png():
    """clipboard_paste sets Image.format to 'png' for image/png."""
    fake_png = b"\x89PNG\r\n\x1a\n"
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["image/png"]):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=fake_png):
                result = await clipboard_paste()

    assert isinstance(result, Image)
    assert result._format == "png"


@pytest.mark.asyncio
async def test_paste_image_format_field_jpeg():
    """clipboard_paste sets Image.format to 'jpeg' for image/jpeg."""
    fake_jpeg = b"\xff\xd8\xff"
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["image/jpeg"]):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=fake_jpeg):
                result = await clipboard_paste()

    assert isinstance(result, Image)
    assert result._format == "jpeg"


@pytest.mark.asyncio
async def test_paste_image_format_field_with_params():
    """clipboard_paste strips MIME params before extracting format."""
    fake_png = b"\x89PNG"
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats", return_value=["image/png;charset=binary"]
        ):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=fake_png):
                result = await clipboard_paste()

    assert isinstance(result, Image)
    assert result._format == "png"


@pytest.mark.asyncio
async def test_paste_list_formats_error_falls_through():
    """clipboard_paste handles ClipboardError from list_clipboard_formats gracefully."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats",
            side_effect=ClipboardError("no clipboard"),
        ):
            result = await clipboard_paste()

    assert isinstance(result, str)
    assert "empty" in result.lower() or "Clipboard" in result


@pytest.mark.asyncio
async def test_paste_mixed_image_and_audio():
    """clipboard_paste returns image when both image and audio formats are present."""
    fake_png = b"\x89PNG"
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch(
            "mcp_clipboard.server.list_clipboard_formats", return_value=["audio/mpeg", "image/png"]
        ):
            with patch("mcp_clipboard.server.read_clipboard_image", return_value=fake_png):
                result = await clipboard_paste()

    assert isinstance(result, Image)


@pytest.mark.asyncio
async def test_paste_video_reports_binary():
    """clipboard_paste reports video MIME types as unsupported binary."""
    with patch("mcp_clipboard.server.read_clipboard", _mock_read(html="", text="")):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["video/mp4"]):
            result = await clipboard_paste()

    assert isinstance(result, str)
    assert "video/mp4" in result
    assert "binary data" in result


@pytest.mark.asyncio
async def test_paste_rtf_fallback():
    """clipboard_paste returns RTF content when HTML and plain text are empty."""
    rtf_content = r"{\rtf1\ansi Hello, {\b world}!}"

    async def mock_read(mime_type="text/plain"):
        if mime_type == "text/rtf":
            return rtf_content
        return ""

    with patch("mcp_clipboard.server.read_clipboard", side_effect=mock_read):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["text/rtf"]):
            result = await clipboard_paste()

    assert isinstance(result, str)
    assert "rich text (RTF)" in result
    assert rtf_content in result


@pytest.mark.asyncio
async def test_paste_rtf_truncated():
    """clipboard_paste truncates oversized RTF at 50KB."""
    rtf_content = r"{\rtf1\ansi " + ("x" * 60_000) + "}"

    async def mock_read(mime_type="text/plain"):
        if mime_type == "text/rtf":
            return rtf_content
        return ""

    with patch("mcp_clipboard.server.read_clipboard", side_effect=mock_read):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=["text/rtf"]):
            result = await clipboard_paste()

    assert "truncated" in result
    assert "rich text (RTF)" in result


@pytest.mark.asyncio
async def test_paste_rtf_skipped_when_text_present():
    """clipboard_paste does not attempt RTF read when plain text is available."""

    async def mock_read(mime_type="text/plain"):
        if mime_type == "text/plain":
            return "hello world"
        if mime_type == "text/rtf":
            raise AssertionError("RTF should not be read when plain text is present")
        return ""

    with patch("mcp_clipboard.server.read_clipboard", side_effect=mock_read):
        result = await clipboard_paste()

    assert "hello world" in result


@pytest.mark.asyncio
async def test_paste_rtf_error_falls_through():
    """clipboard_paste falls through to binary check when RTF read raises ClipboardError."""

    async def mock_read(mime_type="text/plain"):
        if mime_type == "text/rtf":
            raise ClipboardError("rtf not available")
        return ""

    with patch("mcp_clipboard.server.read_clipboard", side_effect=mock_read):
        with patch("mcp_clipboard.server.list_clipboard_formats", return_value=[]):
            result = await clipboard_paste()

    assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# 21. read_clipboard_image() fallback edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_clipboard_image_no_fallback_on_macos():
    """read_clipboard_image skips MIME fallback on macOS."""

    async def mock_reader(mime_type):
        return b""

    list_called = False

    async def mock_list():
        nonlocal list_called
        list_called = True
        return ["image/png;charset=binary"]

    with patch("mcp_clipboard.clipboard._get_backend", return_value="macos"):
        with patch.dict("mcp_clipboard.clipboard._IMAGE_READERS", {"macos": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"macos": mock_list}):
                result = await read_clipboard_image("image/png")

    assert result == b""
    assert not list_called


@pytest.mark.asyncio
async def test_read_clipboard_image_no_fallback_on_windows():
    """read_clipboard_image skips MIME fallback on Windows."""

    async def mock_reader(mime_type):
        return b""

    list_called = False

    async def mock_list():
        nonlocal list_called
        list_called = True
        return ["image/png;charset=binary"]

    with patch("mcp_clipboard.clipboard._get_backend", return_value="windows"):
        with patch.dict("mcp_clipboard.clipboard._IMAGE_READERS", {"windows": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"windows": mock_list}):
                result = await read_clipboard_image("image/png")

    assert result == b""
    assert not list_called


@pytest.mark.asyncio
async def test_read_clipboard_image_fallback_no_match():
    """read_clipboard_image returns empty bytes when fallback finds no matching base type."""

    async def mock_reader(mime_type):
        return b""

    async def mock_list():
        return ["image/tiff", "text/plain"]

    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._IMAGE_READERS", {"wayland": mock_reader}):
            with patch.dict("mcp_clipboard.clipboard._FORMAT_LISTERS", {"wayland": mock_list}):
                result = await read_clipboard_image("image/png")

    assert result == b""


# ---------------------------------------------------------------------------
# 22. write_clipboard() dispatch to all backends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_clipboard_dispatches_to_x11():
    """write_clipboard dispatches to x11 backend."""
    mock_writer = AsyncMock()
    with patch("mcp_clipboard.clipboard._get_backend", return_value="x11"):
        with patch.dict("mcp_clipboard.clipboard._WRITERS", {"x11": mock_writer}):
            await write_clipboard("test")

    mock_writer.assert_called_once_with("test")


@pytest.mark.asyncio
async def test_write_clipboard_dispatches_to_macos():
    """write_clipboard dispatches to macos backend."""
    mock_writer = AsyncMock()
    with patch("mcp_clipboard.clipboard._get_backend", return_value="macos"):
        with patch.dict("mcp_clipboard.clipboard._WRITERS", {"macos": mock_writer}):
            await write_clipboard("test")

    mock_writer.assert_called_once_with("test")


@pytest.mark.asyncio
async def test_write_clipboard_dispatches_to_windows():
    """write_clipboard dispatches to windows backend."""
    mock_writer = AsyncMock()
    with patch("mcp_clipboard.clipboard._get_backend", return_value="windows"):
        with patch.dict("mcp_clipboard.clipboard._WRITERS", {"windows": mock_writer}):
            await write_clipboard("test")

    mock_writer.assert_called_once_with("test")


# ---------------------------------------------------------------------------
# 23. clipboard_read_raw allowlist/rejection edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_raw_allows_application_xml():
    """clipboard_read_raw allows application/xml as text-readable."""
    xml_str = '<?xml version="1.0"?><root/>'
    with patch("mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=xml_str):
        result = await clipboard_read_raw(mime_type="application/xml")

    assert "root" in result
    assert "Cannot read binary" not in result


@pytest.mark.asyncio
async def test_read_raw_allows_application_xhtml():
    """clipboard_read_raw allows application/xhtml+xml as text-readable."""
    xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body>hi</body></html>'
    with patch("mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=xhtml):
        result = await clipboard_read_raw(mime_type="application/xhtml+xml")

    assert "hi" in result
    assert "Cannot read binary" not in result


@pytest.mark.asyncio
async def test_read_raw_rejects_octet_stream():
    """clipboard_read_raw rejects application/octet-stream."""
    result = await clipboard_read_raw(mime_type="application/octet-stream")

    assert "Cannot read binary" in result


@pytest.mark.asyncio
async def test_read_raw_rejects_numeric_mime():
    """clipboard_read_raw rejects MIME types starting with digits."""
    result = await clipboard_read_raw(mime_type="123/456")
    assert "Invalid MIME type" in result


@pytest.mark.asyncio
async def test_read_raw_rejects_underscore_mime():
    """clipboard_read_raw rejects MIME types like _/_."""
    result = await clipboard_read_raw(mime_type="_/_")
    assert "Invalid MIME type" in result


@pytest.mark.asyncio
async def test_read_raw_accepts_custom_mime():
    """clipboard_read_raw should accept valid custom MIME types."""
    # This should pass validation (but return empty since it's not on clipboard)
    with patch("mcp_clipboard.server.read_clipboard", new_callable=AsyncMock, return_value=""):
        result = await clipboard_read_raw(mime_type="application/x-custom")
    assert "Invalid MIME type" not in result


# ---------------------------------------------------------------------------
# 24. clipboard_copy() edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clipboard_copy_empty_string():
    """clipboard_copy handles empty string input."""
    with patch("mcp_clipboard.server.write_clipboard", new_callable=AsyncMock):
        result = await clipboard_copy("")

    assert "0 characters" in result


@pytest.mark.asyncio
async def test_clipboard_copy_unicode():
    """clipboard_copy handles unicode content correctly."""
    with patch("mcp_clipboard.server.write_clipboard", new_callable=AsyncMock) as mock:
        result = await clipboard_copy("Hello \U0001f30d \u4f60\u597d")

    mock.assert_called_once_with("Hello \U0001f30d \u4f60\u597d")
    assert "characters" in result


@pytest.mark.asyncio
async def test_clipboard_copy_rejects_oversized():
    """clipboard_copy rejects content exceeding the write limit."""
    with patch("mcp_clipboard.server._MAX_WRITE_BYTES", 10):
        result = await clipboard_copy("x" * 100)
    assert "exceeds clipboard write limit" in result


@pytest.mark.asyncio
async def test_clipboard_copy_at_limit():
    """clipboard_copy allows content exactly at the write limit."""
    with patch("mcp_clipboard.server._MAX_WRITE_BYTES", 5):
        with patch("mcp_clipboard.server.write_clipboard", new_callable=AsyncMock):
            result = await clipboard_copy("hello")  # 5 bytes
    assert "characters" in result


# ---------------------------------------------------------------------------
# 25. Misc medium-priority tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_windows_read_image_empty():
    """_windows_read_image returns empty bytes when no image on clipboard."""
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=""):
        result = await _windows_read_image("image/png")

    assert result == b""


@pytest.mark.asyncio
async def test_windows_read_image_jpeg():
    """_windows_read_image uses Jpeg format for image/jpeg."""
    import base64

    fake_data = b"\xff\xd8\xff"
    b64_text = base64.b64encode(fake_data).decode()
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=b64_text
    ) as mock_run:
        result = await _windows_read_image("image/jpeg")

    assert result == fake_data
    script = mock_run.call_args[0][0][-1]
    assert "ImageFormat]::Jpeg" in script


@pytest.mark.asyncio
async def test_windows_read_image_unsupported():
    """_windows_read_image rejects unsupported MIME types."""
    with pytest.raises(ClipboardError, match="Unsupported image type"):
        await _windows_read_image("image/webp")


@pytest.mark.asyncio
async def test_wayland_write_passes_env():
    """_wayland_write passes env from _wayland_env() to _run_with_stdin."""
    fake_env = {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000"}
    with patch("mcp_clipboard.clipboard._wayland_env", return_value=fake_env):
        with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
            await _wayland_write("hello")

    assert mock.call_args.kwargs["env"] == fake_env


@pytest.mark.asyncio
async def test_macos_read_image_jpeg_uti():
    """_macos_read_image maps image/jpeg to public.jpeg UTI."""
    import base64

    fake_data = b"\xff\xd8\xff"
    b64_text = base64.b64encode(fake_data).decode()
    with patch(
        "mcp_clipboard.clipboard._run", new_callable=AsyncMock, return_value=b64_text
    ) as mock_run:
        result = await _macos_read_image("image/jpeg")

    assert result == fake_data
    # Verify the osascript uses the correct UTI
    script = mock_run.call_args[0][0][-1]
    assert "public.jpeg" in script


@pytest.mark.asyncio
async def test_macos_read_image_unknown_mime_rejected():
    """_macos_read_image rejects MIME types without a known UTI mapping."""
    with pytest.raises(ClipboardError, match="Unsupported image type"):
        await _macos_read_image("image/webp")


@pytest.mark.asyncio
async def test_macos_read_image_injection_rejected():
    """_macos_read_image rejects MIME types that could escape the AppleScript string."""
    with pytest.raises(ClipboardError, match="Unsupported image type"):
        await _macos_read_image('image/png"; -- ')


def test_load_instruction_clipboard_copy():
    """_load_instruction loads the clipboard_copy instruction file."""
    result = _load_instruction("clipboard_copy")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_detect_backend_x11_fallback():
    """_detect_backend falls back to x11 when wl-paste is unavailable on Linux."""

    def mock_which(cmd):
        if cmd == "xclip":
            return "/usr/bin/xclip"
        return None  # wl-paste not found

    with patch("mcp_clipboard.clipboard.platform.system", return_value="Linux"):
        with patch("mcp_clipboard.clipboard.shutil.which", side_effect=mock_which):
            with patch.dict("os.environ", {}, clear=True):
                import mcp_clipboard.clipboard as cb

                cb._backend = None
                result = _detect_backend()

    assert result == "x11"


# ---------------------------------------------------------------------------
# 26. Typed write — platform backends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wayland_write_typed_plain():
    """_wayland_write_typed passes --type for text/plain."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _wayland_write_typed("hello", "text/plain")

    cmd = mock.call_args[0][0]
    assert "--type" in cmd
    assert "text/plain" in cmd
    assert mock.call_args[0][1] == b"hello"


@pytest.mark.asyncio
async def test_wayland_write_typed_html():
    """_wayland_write_typed passes --type text/html."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _wayland_write_typed("<b>hi</b>", "text/html")

    cmd = mock.call_args[0][0]
    assert "--type" in cmd
    assert "text/html" in cmd
    assert mock.call_args[0][1] == b"<b>hi</b>"


@pytest.mark.asyncio
async def test_x11_write_typed_plain():
    """_x11_write_typed passes -target for text/plain."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _x11_write_typed("hello", "text/plain")

    cmd = mock.call_args[0][0]
    assert "-target" in cmd
    assert "text/plain" in cmd
    assert mock.call_args[0][1] == b"hello"


@pytest.mark.asyncio
async def test_x11_write_typed_html():
    """_x11_write_typed passes -target text/html."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _x11_write_typed("<p>hello</p>", "text/html")

    cmd = mock.call_args[0][0]
    assert "-target" in cmd
    assert "text/html" in cmd


@pytest.mark.asyncio
async def test_macos_write_typed_plain():
    """_macos_write_typed uses pbcopy for text/plain."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _macos_write_typed("hello", "text/plain")

    cmd = mock.call_args[0][0]
    assert cmd == ["pbcopy"]
    assert mock.call_args[0][1] == b"hello"


@pytest.mark.asyncio
async def test_macos_write_typed_html():
    """_macos_write_typed uses osascript with public.html UTI for text/html."""
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock) as mock:
        await _macos_write_typed("<b>hello</b>", "text/html")

    script = mock.call_args[0][0][-1]
    assert "public.html" in script
    assert "NSPasteboard" in script


@pytest.mark.asyncio
async def test_macos_write_typed_rtf():
    """_macos_write_typed uses osascript with public.rtf UTI for text/rtf."""
    with patch("mcp_clipboard.clipboard._run", new_callable=AsyncMock) as mock:
        await _macos_write_typed(r"{\rtf1 hello}", "text/rtf")

    script = mock.call_args[0][0][-1]
    assert "public.rtf" in script


@pytest.mark.asyncio
async def test_macos_write_typed_unsupported():
    """_macos_write_typed raises ClipboardError for unsupported MIME types."""
    with pytest.raises(ClipboardError, match="macOS"):
        await _macos_write_typed("data", "text/csv")


@pytest.mark.asyncio
async def test_windows_write_typed_plain():
    """_windows_write_typed uses Set-Clipboard for text/plain."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _windows_write_typed("hello", "text/plain")

    cmd = mock.call_args[0][0]
    assert "powershell" in cmd[0].lower()
    assert mock.call_args[0][1] == b"hello"


@pytest.mark.asyncio
async def test_windows_write_typed_html():
    """_windows_write_typed wraps HTML in CF_HTML format for text/html."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _windows_write_typed("<b>hello</b>", "text/html")

    data = mock.call_args[0][1]
    text = data.decode("utf-8")
    # CF_HTML header must be present
    assert "Version:0.9" in text
    assert "StartHTML:" in text
    assert "StartFragment:" in text
    assert "<!--StartFragment-->" in text
    assert "<b>hello</b>" in text


@pytest.mark.asyncio
async def test_windows_write_typed_rtf():
    """_windows_write_typed passes RTF content for text/rtf."""
    with patch("mcp_clipboard.clipboard._run_with_stdin", new_callable=AsyncMock) as mock:
        await _windows_write_typed(r"{\rtf1 hi}", "text/rtf")

    cmd = mock.call_args[0][0]
    assert "Rtf" in " ".join(cmd)


@pytest.mark.asyncio
async def test_windows_write_typed_unsupported():
    """_windows_write_typed raises ClipboardError for unsupported MIME types."""
    with pytest.raises(ClipboardError, match="Windows"):
        await _windows_write_typed("data", "text/csv")


# ---------------------------------------------------------------------------
# 27. _windows_html_clipboard_wrap unit tests
# ---------------------------------------------------------------------------


def test_windows_html_clipboard_wrap_contains_header():
    result = _windows_html_clipboard_wrap("<p>Hello</p>")
    assert result.startswith("Version:0.9")
    assert "StartHTML:" in result
    assert "EndHTML:" in result
    assert "StartFragment:" in result
    assert "EndFragment:" in result


def test_windows_html_clipboard_wrap_contains_content():
    result = _windows_html_clipboard_wrap("<p>Hello</p>")
    assert "<p>Hello</p>" in result
    assert "<!--StartFragment-->" in result
    assert "<!--EndFragment-->" in result


def test_windows_html_clipboard_wrap_offsets_are_valid():
    """Byte offsets in the CF_HTML header must point to correct positions."""
    html = "<p>Test</p>"
    result = _windows_html_clipboard_wrap(html)
    result_bytes = result.encode("utf-8")

    import re

    start_html = int(re.search(r"StartHTML:(\d+)", result).group(1))
    end_html = int(re.search(r"EndHTML:(\d+)", result).group(1))
    start_frag = int(re.search(r"StartFragment:(\d+)", result).group(1))
    end_frag = int(re.search(r"EndFragment:(\d+)", result).group(1))

    assert result_bytes[start_html : start_html + 6] == b"<html>"
    assert result_bytes[start_frag : start_frag + len(html)] == html.encode("utf-8")
    assert end_html == start_html + len(result_bytes[start_html:])
    assert end_frag == start_frag + len(html.encode("utf-8"))


# ---------------------------------------------------------------------------
# 28. write_clipboard_typed dispatch + server clipboard_copy with mime_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_clipboard_typed_dispatches():
    """write_clipboard_typed dispatches to the correct backend."""
    mock_writer = AsyncMock()
    with patch("mcp_clipboard.clipboard._get_backend", return_value="wayland"):
        with patch.dict("mcp_clipboard.clipboard._TYPED_WRITERS", {"wayland": mock_writer}):
            await write_clipboard_typed("<b>hi</b>", "text/html")

    mock_writer.assert_called_once_with("<b>hi</b>", "text/html")


@pytest.mark.asyncio
async def test_clipboard_copy_with_mime_type_html():
    """clipboard_copy with mime_type=text/html uses write_clipboard_typed."""
    with patch("mcp_clipboard.server.write_clipboard_typed", new_callable=AsyncMock) as mock:
        result = await clipboard_copy("<b>hello</b>", mime_type="text/html")

    mock.assert_called_once_with("<b>hello</b>", "text/html")
    assert "text/html" in result


@pytest.mark.asyncio
async def test_clipboard_copy_default_mime_type():
    """clipboard_copy defaults to text/plain and uses write_clipboard."""
    with patch("mcp_clipboard.server.write_clipboard", new_callable=AsyncMock) as mock:
        result = await clipboard_copy("hello")

    mock.assert_called_once_with("hello")
    assert "text/plain" in result


@pytest.mark.asyncio
async def test_clipboard_copy_rejects_binary_mime():
    """clipboard_copy rejects binary MIME types."""
    result = await clipboard_copy("data", mime_type="image/png")
    assert "Cannot write binary" in result


@pytest.mark.asyncio
async def test_clipboard_copy_rejects_audio_mime():
    """clipboard_copy rejects audio/* MIME types."""
    result = await clipboard_copy("data", mime_type="audio/mp3")
    assert "Cannot write binary" in result


@pytest.mark.asyncio
async def test_clipboard_copy_typed_error():
    """clipboard_copy surfaces ClipboardError from write_clipboard_typed."""
    with patch(
        "mcp_clipboard.server.write_clipboard_typed", side_effect=ClipboardError("unsupported")
    ):
        result = await clipboard_copy("<b>hi</b>", mime_type="text/html")

    assert "Error" in result
    assert "unsupported" in result


# ---------------------------------------------------------------------------
# __version__ resilience (#28)
# ---------------------------------------------------------------------------


def test_version_fallback_when_not_installed():
    """__version__ should not crash when the package is not installed."""
    from importlib.metadata import PackageNotFoundError
    from unittest.mock import patch as mock_patch

    with mock_patch(
        "importlib.metadata.version", side_effect=PackageNotFoundError("mcp-clipboard")
    ):
        # Re-import to trigger the version lookup
        import importlib

        import mcp_clipboard

        importlib.reload(mcp_clipboard)
        assert mcp_clipboard.__version__ == "0.0.0+dev"

    # Restore the real version
    importlib.reload(mcp_clipboard)
