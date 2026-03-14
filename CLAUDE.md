# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

clipboard-mcp is an MCP (Model Context Protocol) server that reads and writes the system clipboard — tables, plain text, code, JSON, URLs, images, and more. Preserves structure when possible (e.g. spreadsheet row/column layout from HTML) and returns non-tabular content with smart formatting. Images on the clipboard are returned as viewable content; audio and video are detected and reported but not returned.

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

# Publish to PyPI (do NOT publish directly — push a tag to trigger GitHub Actions)
git tag v0.1.x && git push origin v0.1.x   # triggers .github/workflows/publish.yml
git tag test-v0.1.x && git push origin test-v0.1.x  # triggers test-publish.yml (TestPyPI)
```

## Architecture

Three-layer design with clean separation:

- **server.py** — MCP server (`FastMCP`, name `clipboard_mcp`) exposing 4 tools:
  - `clipboard_paste(output_format)` — Primary tool. Handles any clipboard content: tables → markdown/json/csv; non-tabular → smart formatting (JSON, code, URL, text). Images are returned as base64-encoded image content. Audio/video are detected and reported.
  - `clipboard_copy(content)` — Writes text to the system clipboard.
  - `clipboard_read_raw(mime_type)` — Returns raw clipboard content for a given MIME type (truncated at 50KB). Rejects binary MIME types.
  - `clipboard_list_formats()` — Lists available MIME types on clipboard.

- **clipboard.py** — Platform-agnostic clipboard abstraction. Auto-detects backend (Wayland `wl-paste`/`wl-copy`, X11 `xclip`, macOS `osascript`/`pbpaste`/`pbcopy`, Windows PowerShell). All operations are async with 5-second timeout. Exit code 1 means "format not available" (not an error). macOS UTI types and Windows format names are mapped to MIME types in `list_formats`. Supports text read/write and binary image reads.

- **parser.py** — HTML table extraction (custom `HTMLParser` subclass), TSV parsing, HTML-to-text extraction, content-type detection (json/url/code/text), and table formatters (Markdown, JSON, CSV).

- **instructions/** — Markdown files containing MCP server instructions and tool descriptions. Loaded at startup by `server.py` via `_load_instruction()`. These are the descriptions the host model sees when deciding which tool to call. Edit these files to change tool behavior descriptions without touching Python code.

**Data flow**: `clipboard_paste` → try HTML → `parse_html_table()` → if rows, format table → return. Else try plain text → `parse_tsv()` → if rows, format table → return. Else if no text content, check for image formats → read and return as image content. Else check for other binary formats → report. Else `detect_content_type()` → return with smart formatting.

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
- PyPI package name is `clipboard-mcp-server` (the command and import name remain `clipboard-mcp` / `clipboard_mcp`)
- Linux with Wayland is tested on real hardware; X11 has unit tests but is unverified on live hardware; macOS and Windows are complete but untested
- `clipboard_paste` intentionally has no return type annotation — adding `-> str | Image` causes FastMCP to fail Pydantic schema generation for `Image`

## Packaging Feature Branches

- **`feature/homebrew-tap`** (local only) — Homebrew formula, update script, and CI template for a `cmeans/homebrew-clipboard-mcp` tap. Formula resource stanzas need populating via `brew update-python-resources` on macOS before the tap can be published. Has 36 transitive dependencies from `mcp[cli]`.
- **`feature/aur-package`** (pushed to origin) — PKGBUILD for Arch Linux AUR. Ready to test in an Arch VM or Docker container. Note: depends on `python-mcp` which may need its own AUR package first. Test with `makepkg -si` in a VM or Docker build validation per `packaging/aur/README.md`.
