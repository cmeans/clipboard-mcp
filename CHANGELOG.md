# Changelog

All notable changes to this project will be documented here.

## [2.0.1] - 2026-04-04

### Added
- Server icons (light/dark SVG) embedded as data URIs via FastMCP `icons` parameter

### Fixed
- Claude Code install command now uses `--scope user` for global availability

## [2.0.0] - 2026-04-04

### Changed
- **Breaking**: Renamed PyPI package from `clipboard-mcp-server` to `mcp-clipboard`
- **Breaking**: Renamed Python package from `clipboard_mcp` to `mcp_clipboard`
- **Breaking**: CLI command renamed from `clipboard-mcp` to `mcp-clipboard`
- **Breaking**: Debug env var renamed from `CLIPBOARD_MCP_DEBUG` to `MCP_CLIPBOARD_DEBUG`
- License changed from MIT to Apache 2.0
- README rewritten with Claude Code clipboard padding workaround as key feature

## [1.4.0] - 2026-03-15

### Added
- `clipboard_copy` gains a `mime_type` parameter (default: `text/plain`) for writing typed clipboard content
- Wayland and X11: any `text/*` MIME type is passed through to `wl-copy --type` / `xclip -target`
- macOS: `text/html` written via NSPasteboard (`public.html` UTI); `text/rtf` via `public.rtf` UTI; both use base64 encoding to safely pass content through `osascript`
- Windows: `text/html` written with the CF_HTML byte-offset header format; `text/rtf` written via `DataFormats::Rtf`
- Binary MIME types (`image/*`, `audio/*`, `video/*`, `application/octet-stream`) are rejected with a clear error message
- New `write_clipboard_typed(content, mime_type)` in `clipboard.py`; `_windows_html_clipboard_wrap()` helper for CF_HTML formatting

### Limitations
- Writing multiple MIME types atomically (e.g. both `text/html` and `text/plain`) in a single clipboard operation is not supported on Wayland/X11 — doing so requires owning the clipboard selection across calls

## [1.3.0] - 2026-03-15

### Added
- Five new `output_format` values for destination-aware table formatting:
  - `slack` — `*bold*` header line followed by space-aligned data in a monospace code block
  - `jira` — `||Header||` / `|Cell|` Jira wiki markup
  - `confluence` — same as `jira` (shared Atlassian wiki syntax)
  - `html` — `<table>` with `<thead>`/`<th>`/`<tbody>`/`<td>`
  - `notion` — standard GFM pipe table (Notion renders these natively; same output as `markdown`)
- README: new "Destination-aware output formats" section with format/destination table and example phrases

## [1.2.0] - 2026-03-15

### Added
- Table schema inference: new `infer_column_types(rows)` in `parser.py` infers a data type per column (integer, float, currency, percentage, date, boolean, text); majority-wins per column; empty cells skipped; header excluded
- `clipboard_paste` gains `include_schema: bool = False` parameter — when `True` and the clipboard contains a table, a **Column types** table is appended after the data
- Date detection supports ISO 8601 (`datetime.fromisoformat`) plus common regional formats (`MM/DD/YYYY`, `DD/MM/YYYY`, `Month DD, YYYY`, etc.)
- Currency detection handles `$`, `£`, `€`, `¥` prefix and suffix forms with optional thousands separators

## [1.1.0] - 2026-03-15

### Added
- RTF clipboard read support (`text/rtf`) on macOS (via `osascript`/NSPasteboard) and Windows (via PowerShell/`DataFormats::Rtf`)
- `clipboard_paste` Strategy 3: when HTML and plain text are both empty, attempts `text/rtf` as a fallback before checking for binary formats; RTF content is returned in a fenced code block labelled "rich text (RTF)", truncated at 50KB
- Wayland and X11 backends already supported `text/rtf` via pass-through MIME to `wl-paste`/`xclip`

## [1.0.1] - 2026-03-14

### Fixed
- `clipboard_paste` was missing a `-> str | Image` return type annotation, which
  could affect MCP schema generation
- `_BINARY_MIME_PREFIXES` contained `"application/octet-stream"` as a pseudo-prefix
  rather than an exact match; split into a separate `_BINARY_MIME_EXACT` set
- `_TEXT_READABLE_MIMES` contained `application/json`, `application/xml`, and
  `application/xhtml+xml` which were never reachable by the prefix guard; only
  `image/svg+xml` is now listed
- Exit code 1 was silently swallowed for macOS (`osascript`, `pbpaste`) and Windows
  (PowerShell) backends, hiding real errors; exit-1-as-empty is now restricted to
  Wayland and X11 backends

### Changed
- `_base_mime_type()` renamed to `base_mime_type()` (public API)
- `_run()` and `_run_binary()` refactored to share a common `_run_subprocess()`
  core, eliminating ~20 lines of duplicated error handling
- `_configure_logging()` moved from module import time into `main()` so that
  importing `clipboard_mcp.server` no longer configures root logging as a side
  effect
- Added basic MIME type format validation in `clipboard_read_raw` to reject
  malformed input before passing it to a subprocess
- Removed `"use "` from code-detection patterns in `parser.py` to avoid false
  positives on ordinary English text

### Known limitations
- `clipboard_paste` has no return type annotation (`-> str | Image`) because
  FastMCP passes the annotation through Pydantic's `create_model()`, which cannot
  generate a schema for `Image`. The omission is intentional; see the comment in
  `server.py` for details.

### Metadata
- PyPI classifier updated from "Development Status :: 3 - Alpha" to
  "Development Status :: 5 - Production/Stable"
- Added PyPI keywords for better discoverability
- Publish workflows now run the test suite before building and publishing
- README clarifies that X11 has unit test coverage but has not been verified on a
  live X11 session

## [1.0.0] - 2026-03-14

### Added
- Features, Acknowledgments, and copyright sections in README
- GitHub Actions updated to latest major versions

## [0.1.3] - 2026-03-14

### Added
- `clipboard_copy` tool — write text to the system clipboard via `wl-copy`/`xclip`/
  `pbcopy`/PowerShell
- Image passthrough — `clipboard_paste` now returns clipboard images as base64-encoded
  MCP image content blocks that Claude can see and analyze
- `clipboard_read_raw` now accepts `image/svg+xml`, `application/json`,
  `application/xml`, and `application/xhtml+xml` (previously rejected as binary)

### Fixed
- MIME parameter suffixes (e.g. `text/plain;charset=utf-8`) are now stripped before
  comparison, fixing format fallback on some Wayland compositors
- `wl-copy` timeout: stdout/stderr are now redirected to `/dev/null` to avoid
  blocking on the background child process that holds the clipboard

## [0.1.2] - 2026-03-14

### Added
- X11 (`xclip`) backend unit tests
- GitHub Actions CI workflow (`test.yml`) running tests on Python 3.11–3.13

### Fixed
- Improved error handling and test coverage gaps identified in code review

## [0.1.1] - 2026-02-15

### Fixed
- `uvx` and `pipx` install instructions corrected to use `--from clipboard-mcp-server`
  with the `clipboard-mcp` command name

## [0.1.0] - 2026-02-15

### Added
- Initial PyPI release as `clipboard-mcp-server`
- GitHub Actions trusted publisher workflows for PyPI and TestPyPI
- `clipboard_paste` — read tables (HTML/TSV → Markdown/JSON/CSV), JSON, URLs, code,
  and plain text from the clipboard
- `clipboard_read_raw` — return raw clipboard content for a given MIME type
- `clipboard_list_formats` — list available MIME types on the clipboard
- Wayland auto-detection via `$XDG_RUNTIME_DIR` socket scan
- Platform support: Wayland, X11, macOS (osascript/pbpaste), Windows (PowerShell)
