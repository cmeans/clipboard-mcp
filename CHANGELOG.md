# Changelog

All notable changes to this project will be documented here.

## [2.2.0] - 2026-04-12

### Added
- `clipboard_copy` now enforces a write-side size limit (default 1 MiB).
  Rejects oversized content with a clear error message. Override via
  `MCP_CLIPBOARD_MAX_WRITE_BYTES` env var. Closes #27.
- `MCP_CLIPBOARD_BACKEND` env var to override auto-detected clipboard
  backend. Valid values: `wayland`, `x11`, `macos`, `windows`. Useful
  for debugging wrong-backend issues. Closes #29.
- `_run_with_stdin` now captures stderr when `MCP_CLIPBOARD_DEBUG=1`
  and includes it in the `ClipboardError` message on write failures.
  Stderr is still sent to /dev/null in normal mode to avoid the
  wl-copy pipe-deadlock issue. Closes #32.
- Opt-in integration test suite (`tests/test_integration.py`) that
  exercises real clipboard tools. Skipped by default; run with
  `uv run pytest -m integration`. Covers text round-trip, unicode,
  multiline, special characters, format listing, and unavailable
  MIME types. Closes #23.
- `py.typed` PEP 561 marker so downstream type checkers (mypy, pyright)
  see the package's type annotations. Closes #33.

### Fixed
- `_TextExtractor` now uses a depth counter instead of a boolean for
  skipping `<script>`/`<style>` content. Prevents `</style>` from
  prematurely re-enabling text extraction when inside a `<script>` tag
  (and vice versa). Closes #36.
- MIME type validation regex now requires type and subtype to start
  with a letter. Rejects nonsensical values like `123/456` and `_/_`.
  Also validates parameter syntax (`name=value`). Closes #35.
- JSON output now uses type inference to detect headers. When the first
  row's types differ from the data (e.g., text header over integer data),
  it's used as keys. When all rows have matching types, all data is
  preserved as a flat array or list of lists. Removes the undocumented
  `{"values": row}` wrapper. Closes #30.
- `_format_html` now escapes cell values with `html.escape()`, preventing
  XSS via injected `<script>` tags or other HTML in cell content.
  Closes #15.

## [2.1.1] - 2026-04-12

### Fixed
- `detect_content_type` no longer false-positives on prose containing
  common English words like "return", "class", or "public", or operators
  like `->`, `||`, `::`. Short/ambiguous patterns now require 2+ distinct
  matches to classify as code. Closes #20.
- `_windows_read_image` now honors the requested MIME type instead of
  always returning PNG. Maps `image/jpeg`, `image/bmp`, `image/gif`,
  and `image/tiff` to their .NET `ImageFormat` equivalents. Rejects
  unsupported types with `ClipboardError`. Closes #34.
- Truncation message now says "50,000 characters" instead of "50KB".
  The limit is a character count, not a byte count. Constant renamed
  from `_MAX_CONTENT_LEN` to `_MAX_CONTENT_CHARS`. Closes #37.
- `__version__` no longer crashes with `PackageNotFoundError` when
  running from source without installing. Falls back to `"0.0.0+dev"`.
  Closes #28.
- Date inference in `_classify_cell` now short-circuits on values with
  no digits, skipping up to 10 exception-driven `strptime` calls per
  text cell. Closes #26.

## [2.1.0] - 2026-04-12

### Added
- QA workflow labels and `pr-labels` / `qa-gate` automation, matching
  `mcp-synology` and `mcp-awareness`. Adds `Dev Active`, `Awaiting CI`,
  `Ready for QA`, `QA Active`, `Ready for QA Signoff`, `QA Failed`,
  `QA Approved`, `CI Failed`, `merge-order: 0`–`3`, and `dependencies`
  labels. New workflows: `pr-labels.yml`, `pr-labels-ci.yml`,
  `qa-gate.yml`.
- `CONTRIBUTING.md` — license of contribution (Apache-2.0 § 5
  inbound=outbound), no-bounty policy, dev-env setup, PR
  requirements, review process walkthrough, issue template guide,
  and code style notes.
- `SECURITY.md` — private disclosure via GitHub Private Security
  Advisories (the only supported channel; no email fallback), scope,
  and response expectations. Private vulnerability reporting enabled
  on the repository.
- `CODE_OF_CONDUCT.md` — adopts Contributor Covenant 2.1 by
  reference; reports route through a Private Security Advisory
  titled `Conduct` as a workaround for GitHub's lack of a general
  private-contact channel. Closes #25.
- Parametrized escaping test matrix covering special characters
  (pipes, backslashes, angle brackets, quotes, backticks, newlines,
  multibyte) across all 8 output formats. Closes #18.
- `ruff` linter/formatter and `mypy` type checker added to CI as
  separate jobs. Configured in `pyproject.toml`. Closes #22.

### Fixed
- Pipe (`|`) and backslash (`\`) in table cell values are now escaped in the
  `markdown` and `notion` output formats, preventing column-structure corruption
  in rendered tables. Closes #16.
- Pipe (`|`) and backslash (`\`) in table cell values are now escaped in the
  `jira` and `confluence` output formats, preventing cell-boundary corruption
  and accidental header syntax. Closes #17.
- `_macos_read_image` now rejects MIME types without a known UTI mapping
  instead of interpolating raw caller input into an AppleScript string
  literal. Prevents potential script injection via crafted MIME types.
  Closes #24.
- `parse_tsv` now uses `csv.reader` with RFC 4180 quoting instead of
  naive `str.split("\t")`. Fields containing embedded tabs or newlines
  are preserved when wrapped in double quotes. Closes #21.
- Slack table format now renders the entire table (header + data) inside
  a single code block with a dashed underline separator. This avoids
  special character corruption (`*`, `` ` ``) from Slack's mrkdwn
  formatting and fixes header/data column misalignment from mixed
  proportional/monospace fonts. Closes #19, closes #31.

### Changed
- Renamed `.github/workflows/test.yml` → `ci.yml` and the workflow
  `name:` from `Tests` to `CI` for cross-repo consistency. README
  badge URL updated to match.

## [2.0.2] - 2026-04-05

### Added
- Test coverage reporting via pytest-cov and Codecov (96% coverage)
- Coverage badge in README
- PyPI, CI, license, and download badges in README

### Fixed
- README images now use absolute GitHub URLs so logos render on PyPI

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
