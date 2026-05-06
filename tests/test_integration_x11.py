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

from mcp_clipboard.clipboard import (
    list_clipboard_formats,
    read_clipboard,
    read_clipboard_image,
    reset_backend_cache,
    write_clipboard,
    write_clipboard_image,
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
    reset_backend_cache()
    yield
    reset_backend_cache()


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


# Smallest possible PNG (1x1, fully transparent) — proves the write path
# round-trips bytes intact through xclip without mangling.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "0000000100000001080600000015b9da38"
    "0000000a49444154789c63000100000005000182dd8a73"
    "0000000049454e44ae426082"
)

_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000"
    "ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d"
    "1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d3832"
    "3c2e333432"
    "ffc0000b08000100010101110000"
    "ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
    "ffda0008010100003f00d2cf20ffd9"
)


@pytest.mark.asyncio
async def test_x11_write_image_png_round_trip():
    """write_clipboard_image(PNG) round-trips intact through xclip."""
    await write_clipboard_image(_TINY_PNG, "image/png")
    result = await read_clipboard_image("image/png")
    assert result == _TINY_PNG


@pytest.mark.asyncio
async def test_x11_write_image_jpeg_round_trip():
    """write_clipboard_image(JPEG) round-trips intact through xclip."""
    await write_clipboard_image(_TINY_JPEG, "image/jpeg")
    result = await read_clipboard_image("image/jpeg")
    assert result == _TINY_JPEG


@pytest.mark.asyncio
async def test_x11_write_image_advertises_target():
    """After write_clipboard_image, list_clipboard_formats reports the MIME."""
    await write_clipboard_image(_TINY_PNG, "image/png")
    formats = await list_clipboard_formats()
    assert any(f == "image/png" for f in formats), f"image/png not in {formats}"


@pytest.mark.asyncio
async def test_x11_round_trip_svg_typed():
    """SVG round-trips through xclip's image/svg+xml target unchanged.

    SVG is text (XML) but rides the typed-write path under an image MIME.
    Verifies #112: clipboard_copy(mime_type='image/svg+xml') reaches the
    OS pasteboard and reads back byte-identical.
    """
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<rect width="10" height="10" fill="red"/>'
        "</svg>"
    )
    await write_clipboard_typed(svg, "image/svg+xml")
    result = await read_clipboard("image/svg+xml")
    assert result.strip() == svg


@pytest.mark.asyncio
async def test_x11_list_formats_after_svg_write():
    """After writing SVG, xclip -target TARGETS reports image/svg+xml."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg"/>'
    await write_clipboard_typed(svg, "image/svg+xml")
    formats = await list_clipboard_formats()
    assert any(f == "image/svg+xml" for f in formats), f"image/svg+xml not in {formats}"
