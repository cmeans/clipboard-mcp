# Changelog

All notable changes to this project will be documented here.

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
  with the `clipboard-mcp` command name (the package name and command name differ)

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
