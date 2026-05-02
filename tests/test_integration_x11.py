"""Headless X11 integration tests.

Forces the X11 backend (`MCP_CLIPBOARD_BACKEND=x11`) and exercises the
full xclip-driven read/write/list_formats stack end-to-end against a real
xclip process. Designed to run under Xvfb in CI:

    sudo apt-get install -y xvfb xclip
    MCP_CLIPBOARD_BACKEND=x11 xvfb-run -a uv run pytest tests/test_integration_x11.py -m integration

Per the architecture review, the X11 stack (`_x11_read`, `_x11_list_formats`,
`_x11_read_image`, `_x11_write`, `_x11_write_typed`) was previously
mock-only despite shipping in production builds. These tests close the
real-hardware gap with a single Xvfb session that's standard in Ubuntu CI.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

import mcp_clipboard.clipboard as cb
from mcp_clipboard.clipboard import (
    list_clipboard_formats,
    read_clipboard,
    read_clipboard_image,
    write_clipboard,
    write_clipboard_typed,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("xclip") is None,
        reason="xclip not installed",
    ),
    pytest.mark.skipif(
        not os.environ.get("DISPLAY"),
        reason="No X11 display available (run under xvfb-run)",
    ),
]


@pytest.fixture(autouse=True)
def _force_x11_backend(monkeypatch):
    """Force the X11 backend for every test in this module."""
    monkeypatch.setenv("MCP_CLIPBOARD_BACKEND", "x11")
    cb._backend = None
    yield
    cb._backend = None


@pytest.mark.asyncio
async def test_x11_round_trip_plain_text():
    """write_clipboard then read_clipboard via xclip preserves plain text."""
    payload = "mcp-clipboard X11 integration test"
    await write_clipboard(payload)
    result = await read_clipboard("text/plain")
    assert result.strip() == payload


@pytest.mark.asyncio
async def test_x11_round_trip_unicode():
    """xclip handles UTF-8 sequences (emoji, CJK) without mangling."""
    payload = "Hello \U0001f30d 你好"
    await write_clipboard(payload)
    result = await read_clipboard("text/plain")
    assert result.strip() == payload


@pytest.mark.asyncio
async def test_x11_round_trip_html_typed():
    """write_clipboard_typed("text/html", ...) round-trips through xclip's
    -target mechanism."""
    html = "<table><tr><td>hello</td><td>world</td></tr></table>"
    await write_clipboard_typed(html, "text/html")
    result = await read_clipboard("text/html")
    assert "<table>" in result
    assert "hello" in result
    assert "world" in result


@pytest.mark.asyncio
async def test_x11_list_formats_after_typed_write():
    """After writing HTML, xclip -target TARGETS reports text/html."""
    await write_clipboard_typed("<p>hi</p>", "text/html")
    formats = await list_clipboard_formats()
    assert isinstance(formats, list)
    assert any(f == "text/html" for f in formats), f"text/html not in {formats}"


@pytest.mark.asyncio
async def test_x11_read_unavailable_mime_returns_empty():
    """xclip exits 1 ("target not available") when the MIME type isn't on
    the clipboard; the backend treats that as empty bytes."""
    await write_clipboard("plain text only")
    result = await read_clipboard("application/x-unavailable-format")
    assert result == ""


@pytest.mark.asyncio
async def test_x11_read_image_binary_round_trip():
    """xclip -target image/png accepts arbitrary bytes; the binary read
    path round-trips them via _x11_read_image."""
    payload = b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03\x04\x05\xff\xfe"
    proc = await asyncio.create_subprocess_exec(
        "xclip",
        "-selection",
        "clipboard",
        "-target",
        "image/png",
        stdin=asyncio.subprocess.PIPE,
    )
    await proc.communicate(input=payload)
    assert proc.returncode == 0

    result = await read_clipboard_image("image/png")
    assert result == payload
