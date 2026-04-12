"""Integration tests that exercise real clipboard tools.

Skipped by default. Run with:

    uv run pytest -m integration

Requires a running clipboard daemon (Wayland compositor, X11 server,
or macOS/Windows desktop session). These tests write to and read from
the actual system clipboard.
"""

from __future__ import annotations

import pytest

from mcp_clipboard.clipboard import (
    list_clipboard_formats,
    read_clipboard,
    write_clipboard,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_round_trip_plain_text():
    """Write plain text and read it back."""
    test_value = "mcp-clipboard integration test"
    await write_clipboard(test_value)
    result = await read_clipboard("text/plain")
    assert result.strip() == test_value


@pytest.mark.asyncio
async def test_round_trip_unicode():
    """Write unicode text and read it back."""
    test_value = "Hello \U0001f30d \u4f60\u597d"
    await write_clipboard(test_value)
    result = await read_clipboard("text/plain")
    assert result.strip() == test_value


@pytest.mark.asyncio
async def test_round_trip_multiline():
    """Write multiline text and read it back."""
    test_value = "line one\nline two\nline three"
    await write_clipboard(test_value)
    result = await read_clipboard("text/plain")
    assert result.strip() == test_value


@pytest.mark.asyncio
async def test_round_trip_special_chars():
    """Write text with special characters and read it back."""
    test_value = 'pipes | and "quotes" and <angles> & ampersands'
    await write_clipboard(test_value)
    result = await read_clipboard("text/plain")
    assert result.strip() == test_value


@pytest.mark.asyncio
async def test_list_formats_includes_text():
    """After writing text, list_clipboard_formats should include a text type."""
    await write_clipboard("format check")
    formats = await list_clipboard_formats()
    assert isinstance(formats, list)
    assert len(formats) > 0
    # At least one text format should be present
    text_formats = [f for f in formats if "text" in f.lower() or "string" in f.lower()]
    assert text_formats, f"No text format found in: {formats}"


@pytest.mark.asyncio
async def test_read_empty_mime_returns_empty():
    """Reading an unavailable MIME type should return an empty string."""
    result = await read_clipboard("application/x-nonexistent-format")
    assert result == ""
