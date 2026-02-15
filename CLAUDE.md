# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

clipboard-mcp is an MCP (Model Context Protocol) server that reads content from the system clipboard — tables, plain text, code, JSON, URLs, and more. Preserves structure when possible (e.g. spreadsheet row/column layout from HTML) and returns non-tabular content with smart formatting. Binary content (images, audio, video) is detected and reported but not returned.

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

# Build wheel (to verify packaging)
uv build --wheel
```

## Architecture

Three-layer design with clean separation:

- **server.py** — MCP server (`FastMCP`, name `clipboard_mcp`) exposing 4 tools:
  - `clipboard_paste(output_format)` — Primary tool. Handles any clipboard content: tables → markdown/json/csv; non-tabular → smart formatting (JSON, code, URL, text). Detects binary clipboard content and reports it.
  - `clipboard_read_raw(mime_type)` — Returns raw clipboard content for a given MIME type (truncated at 50KB). Rejects binary MIME types.
  - `clipboard_list_formats()` — Lists available MIME types on clipboard.

- **clipboard.py** — Platform-agnostic clipboard abstraction. Auto-detects backend (Wayland `wl-paste`, X11 `xclip`, macOS `osascript`/`pbpaste`, Windows PowerShell). All operations are async with 5-second timeout. Exit code 1 means "format not available" (not an error). macOS UTI types and Windows format names are mapped to MIME types in `list_formats`. Read functions only handle `text/html` and `text/plain`; unsupported MIME types return empty string.

- **parser.py** — HTML table extraction (custom `HTMLParser` subclass), TSV parsing, HTML-to-text extraction, content-type detection (json/url/code/text), and table formatters (Markdown, JSON, CSV).

- **instructions/** — Markdown files containing MCP server instructions and tool descriptions. Loaded at startup by `server.py` via `_load_instruction()`. These are the descriptions the host model sees when deciding which tool to call. Edit these files to change tool behavior descriptions without touching Python code.

**Data flow**: `clipboard_paste` → try HTML → `parse_html_table()` → if rows, format table → return. Else try plain text → `parse_tsv()` → if rows, format table → return. Else if no text content, check for binary formats → report. Else `detect_content_type()` → return with smart formatting.

## Testing

Tests use `pytest` with `pytest-asyncio` (async mode: auto). All pytest config is in `pyproject.toml` (`[tool.pytest.ini_options]`). Server tests mock clipboard operations via `unittest.mock.patch` on `clipboard_mcp.server.clipboard`. Parser tests are pure unit tests with no mocking needed. Platform-specific backend tests (macOS, Windows) mock `clipboard_mcp.clipboard._run`.

## Key Details

- Python 3.11+ required
- Only runtime dependency: `mcp[cli]>=1.2.0`
- HTML parsing uses stdlib `html.parser` (no BeautifulSoup)
- Pytest config is in `pyproject.toml` (no separate pytest.ini)
- Entry point: `clipboard_mcp.server:main()`
- Tool descriptions live in `src/clipboard_mcp/instructions/*.md` — edit those files to change what the host model sees
- `pyproject.toml` `artifacts` setting ensures instruction `.md` files are included in the wheel
- Linux with Wayland and X11 is tested; macOS and Windows implementations are complete but untested on real hardware
