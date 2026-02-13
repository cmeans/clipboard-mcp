# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

clipboard-mcp is an MCP (Model Context Protocol) server that reads content from the system clipboard — tables, plain text, code, JSON, URLs, and more. Preserves structure when possible (e.g. spreadsheet row/column layout from HTML) and returns non-tabular content with smart formatting.

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_parser.py

# Run a single test function
uv run pytest tests/test_parser.py::test_parse_google_sheets_html

# Run the MCP server (stdio mode)
uv run clipboard-mcp

# Run with debug logging
uv run clipboard-mcp --debug
# or: CLIPBOARD_MCP_DEBUG=1 uv run clipboard-mcp

# Test interactively with MCP Inspector
uv run mcp dev src/clipboard_mcp/server.py
```

## Architecture

Three-layer design with clean separation:

- **server.py** — MCP server (`FastMCP`, name `clipboard_mcp`) exposing 4 tools:
  - `clipboard_paste(output_format)` — Primary tool. Handles any clipboard content: tables → markdown/json/csv; non-tabular → smart formatting (JSON, code, URL, text).
  - `clipboard_read_table(output_format)` — Backward-compatible alias for `clipboard_paste`.
  - `clipboard_read_raw(mime_type)` — Returns raw clipboard content for a given MIME type (truncated at 50KB).
  - `clipboard_list_formats()` — Lists available MIME types on clipboard.

- **clipboard.py** — Platform-agnostic clipboard abstraction. Auto-detects backend (Wayland `wl-paste`, X11 `xclip`, macOS `osascript`/`pbpaste`, Windows PowerShell). All operations are async with 5-second timeout. Exit code 1 means "format not available" (not an error).

- **parser.py** — HTML table extraction (custom `HTMLParser` subclass), TSV parsing, HTML-to-text extraction, content-type detection (json/url/code/text), and table formatters (Markdown, JSON, CSV).

**Data flow**: `clipboard_paste` → try HTML → `parse_html_table()` → if rows, format table → return. Else try plain text → `parse_tsv()` → if rows, format table → return. Else `detect_content_type()` → return with smart formatting.

## Testing

Tests use `pytest` with `pytest-asyncio` (async mode: auto). Server tests mock clipboard operations via `unittest.mock.patch` on `clipboard_mcp.server.clipboard`. Parser tests are pure unit tests with no mocking needed.

## Key Details

- Python 3.11+ required
- Only runtime dependency: `mcp[cli]>=1.2.0`
- HTML parsing uses stdlib `html.parser` (no BeautifulSoup)
- `pytest.ini` sets `pythonpath = src` and `asyncio_mode = auto`
- Entry point: `clipboard_mcp.server:main()`
