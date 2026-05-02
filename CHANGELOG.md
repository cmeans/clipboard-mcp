# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

### Added
- Public `clipboard.reset_backend_cache()` helper. Replaces the previous
  pattern of poking the module-private `_backend` global directly (which
  the autouse fixtures in `tests/test_server.py` and
  `tests/test_integration_x11.py` were already doing). Production code
  has no reason to call this; it exists for tests that switch backends
  or re-read `MCP_CLIPBOARD_BACKEND` mid-process. (#104)
- Direct unit tests for `parser._has_header_row` covering the
  `len(rows) < 2` early-return path and the all-text-no-header path,
  plus a positive case for text-headers-over-numeric-data. Previously
  exercised only indirectly via `format_table` JSON output. (#104)
- Coverage for `clipboard_paste` `include_schema=True` when the data
  rows are wider than the header row -- the padding loop at
  `server.py:222-228` now has a regression test that asserts synthetic
  `Col 3` / `Col 4` labels are emitted. (#104)
- Coverage for `MCP_CLIPBOARD_MAX_WRITE_BYTES` and
  `MCP_CLIPBOARD_MAX_IMAGE_BYTES` env-var validation. Both vars are
  parsed via `int(os.environ.get(...))` at module import; a non-integer
  value raises `ValueError` before anything else runs. Tests exercise
  each in a subprocess so the partial-import state stays out of the
  in-process module cache. (#104)
- Headless X11 integration tests (`tests/test_integration_x11.py`) and a
  matching CI `integration-x11` job that runs them against a real `xclip`
  process under Xvfb. Five round-trip tests exercise plain text, unicode,
  HTML via `-target`, format listing after a typed write, and binary
  image read. Closes the gap from the audit that the X11 stack
  (`_x11_read`, `_x11_list_formats`, `_x11_read_image`, `_x11_write`,
  `_x11_write_typed`) was mock-only despite shipping in production
  builds. (#102)
- README badge breakouts for installer mix (pip, pipenv, pipx, uv,
  poetry, pdm) and OS distribution (linux, macos, windows), powered by
  the per-installer (v0.2.0) and per-OS (v0.3.0) endpoints from
  pypi-winnow-downloads. Existing hero `Downloads` badge is unchanged.
- `.github/PULL_REQUEST_TEMPLATE.md` auto-fills new human-authored
  PR bodies with Summary, Test plan (matching the CI's `pytest`,
  `ruff check`, `ruff format --check`, `mypy` invocations), and
  CHANGELOG-confirmation sections. Dependabot bypasses the template
  and is handled by the auto-CHANGELOG workflow instead.
- `.github/workflows/dependabot-changelog.yml` auto-prepends a
  `## [Unreleased]` → `### Changed` entry to Dependabot-authored PRs
  so they satisfy the per-PR CHANGELOG rule without manual
  intervention. Runs on `pull_request_target`, filters to
  `dependabot[bot]`, mints a GitHub App installation token via
  `actions/create-github-app-token`, fetches metadata via
  `dependabot/fetch-metadata@v3.1.0` (the v3 line fixed empty
  `prevVersion`/`newVersion` on grouped PRs), and pushes the
  CHANGELOG commit under the `cmeans-claude-dev[bot]` identity.
  Subsection insertion respects Keep-a-Changelog v1.1.0 ordering
  (Added → Changed → Deprecated → Removed → Fixed → Security) so a
  newly-created `### Changed` block lands in the right position.
  Loop guard skips when the last commit is already by the bot;
  idempotency guard skips when the PR number is already referenced
  in `CHANGELOG.md`. Operator must configure two repo secrets
  (`BOT_APP_ID`, `BOT_APP_PRIVATE_KEY`) before the workflow can run.
- `CLAUDE.md § Conventions` documents the per-PR CHANGELOG rule and
  the Keep-a-Changelog category set, mirroring the conventions
  already in place across `cmeans/mcp-synology` and
  `cmeans/pypi-winnow-downloads`.
- Dependabot version-update configuration (`.github/dependabot.yml`)
  for pip and github-actions ecosystems. Weekly schedule (Monday
  06:00 America/Chicago), grouped per ecosystem to reduce noise.
  Commit-message uses `prefix: chore` with `include: scope` so
  Dependabot's auto-appended `(deps)` scope yields canonical
  `chore(deps): bump <foo>` subjects (avoids the doubled-prefix
  failure mode documented in the dependabot-pr-hygiene playbook).
  Labels `dependencies`, `python`, and `github-actions` are
  pre-created on the repo so PRs are categorized on creation.

### Changed
- `clipboard_read_raw` instruction text no longer enumerates a fixed list
  of `application/*` types as if they were specially permitted. The
  implementation only blocks the `image/`, `audio/`, and `video/`
  prefixes plus the exact type `application/octet-stream`, so any other
  MIME type (text/*, application/json, application/xml,
  application/xhtml+xml, image/svg+xml, etc.) passes through. The
  reworded text reflects that, removing the maintenance trap where the
  enumeration would silently drift from the code if the blocklist
  changes. (#102)
- Defensive comment on the `_format_non_tabular` JSONDecodeError fallback
  in `server.py:189-194` documenting that the branch is currently
  unreachable: `detect_content_type` only returns `"json"` after a
  successful `json.loads` on the same (already-truncated) text the
  caller will re-parse. Kept as a safety net in case content-type
  detection ever drifts. No behavioural change. (#102)
- README downloads badge now points at the dogfooded
  `cmeans/pypi-winnow-downloads` endpoint
  (`pypi-badges.intfar.com/mcp-clipboard/downloads-30d-non-ci.json`)
  instead of `shields.io/pypi/dm/mcp-clipboard`. The new number is
  30-day non-CI installs (the metric that signals real adoption);
  the previous shields.io built-in counted CI/installer/mirror
  traffic. Badge link target swapped from the PyPI project page
  (already covered by the `PyPI version` badge above) to
  `github.com/cmeans/pypi-winnow-downloads` so a click surfaces the
  source-of-truth methodology. Closes #97.
- **Bump github-actions group: codecov/codecov-action 5→6** (#95)
- Add `workflow_dispatch:` trigger to `pr-labels-ci.yml` to restore
  template parity with `cmeans/yt-dont-recommend`. Gives maintainers a
  manual "Run workflow" handle and primes the `workflow_run` dispatcher
  when the file is first introduced to a fresh repo. No-op on existing
  PRs because the job-level `if:` guards require `workflow_run` context.
  Closes #89.

### Removed
- Glama integration. The README Glama score badge and the `glama.json`
  registry metadata file are gone. Supersedes the in-Unreleased badge
  swap from PR #100 (which is now moot). (#103)

### Fixed
- Harden GitHub Actions context handling against shell script injection in
  `pr-labels-ci.yml` and `qa-gate.yml`. Contributor-controlled values
  (notably `workflow_run.head_branch` from fork PRs) and label/sha/repo
  context are now passed through `env:` blocks instead of being interpolated
  directly into `run:` shell. Aligns with the pattern already used in
  `pr-labels.yml`. Closes #87.
- Remove the literal empty GitHub Actions expression from two shell
  comments in `pr-labels-ci.yml`. GHA substitutes such sequences inside
  `run:` blocks before the shell sees them (including within comments),
  and the queue-time parser rejects the empty form on `workflow_dispatch`.
  The `workflow_run` path tolerated it, so the bug was latent here but
  blocked manual dispatch and fresh-repo cascades. Closes #91.
- Windows clipboard `list_formats` now deduplicates MIME types when multiple
  native format names map to the same MIME (e.g. `Text` and `UnicodeText`
  both map to `text/plain`), matching the existing macOS behavior. Prevents
  inflated format counts and downstream duplicate iteration. (#101)
- Nested HTML tables no longer leak inner-table cell text into the outer
  cell. `_TableExtractor.handle_data` now gates on `_table_depth == 1` so
  text inside an inner `<table><tr><td>...</td></tr></table>` is no longer
  concatenated into the surrounding outer cell. (#101)
- macOS `_macos_write_typed` no longer trips AppleScript's 32,767-character
  per-line limit when writing HTML or RTF content larger than ~24 KB. The
  base64-encoded payload is split across multiple `set b64 to b64 & "..."`
  statements with a 4,000-character chunk size. (#101)
- `_run_subprocess` and `_run_with_stdin` no longer orphan their child
  process when the calling task is cancelled (e.g. on MCP client
  disconnect). A `finally` block now calls `proc.kill()` on any non-normal
  exit including `asyncio.CancelledError`, which inherits from
  `BaseException` and previously bypassed the timeout-only `except`
  handler. (#101)
- `parse_tsv` no longer treats single-cell input with a stray tab
  (`"word\t"`, commonly produced when copying one Excel cell on Windows)
  as a 1x2 table with a phantom empty column. Single-row results now
  require at least two non-empty cells. (#101)

### Security
- New `MCP_CLIPBOARD_MAX_IMAGE_BYTES` cap (default 10 MB) on
  `read_clipboard_image`. A 100 MB clipboard bitmap previously became
  ~133 MB base64 in a single MCP response and could time out or drop
  the MCP transport. Oversized reads now raise the new
  `ClipboardSizeError`, and `clipboard_paste` returns an explanatory
  message instead of forwarding the payload. The cap is a wire-level
  guard rather than a memory-bounded read: the backend still buffers
  the full image before the size check, so the inflated wire response
  is prevented but local memory pressure on the host running the
  server is not. (#101)
- Image subtype passed to `mcp.Image(format=...)` is now validated against
  an allowlist (`png`, `jpeg`, `gif`, `webp`, `tiff`, `bmp`). Clipboard-
  controlled MIME strings with parameter injection or unexpected subtypes
  fall back to `png` rather than flowing through to the host. (#101)
- Markdown code fences in `clipboard_paste` (JSON, code, RTF branches) now
  size dynamically to one longer than the longest backtick run inside the
  wrapped content. Prevents clipboard text containing literal triple
  backticks from closing the fence early and rendering injected content
  as Markdown (or HTML on permissive hosts). (#101)

## [2.2.1] - 2026-04-16

### Added
- Strengthened `test_paste_large_content_truncated` with a size-bound
  assertion so it can no longer pass if truncation regresses. Closes #70.
- Strengthened `test_format_destination_ragged_rows` with per-format
  structural assertions. Previously only checked non-empty output;
  now verifies cell-count uniformity for jira/confluence (`||`/`|` cell
  parsing) and html (`<th>`/`<td>` counts), so a formatter that dropped
  or failed to pad the short row would be caught. Closes #71.

### Changed
- `tests/test_server.py` adds an autouse fixture that resets the module
  global `cb._backend` around every test, replacing scattered manual
  `cb._backend = None` lines in backend-detection and env-override tests.
  Removes the ordering-dependent state hazard called out in #72. Closes #72.

### Fixed
- Subprocess reaping on timeout in `_run_subprocess` and `_run_with_stdin`.
  After `proc.kill()`, the process is now awaited via
  `await asyncio.wait_for(proc.wait(), timeout=1.0)` so the pipes are
  drained and the child is fully reaped, rather than left pending for the
  asyncio child watcher. Closes #69.
- `detect_content_type` no longer misclassifies English prose containing
  "from " or "import " (and other strong code keywords) as code. Strong
  patterns now anchor to the start of a line (after leading whitespace),
  so phrases like "data from the system" or "each import before release"
  are correctly treated as text, while real `import os` / `from x import y`
  at a line start are still detected as code. Closes #68.
- `clipboard_paste` instruction file now describes the `slack` format
  accurately: monospace code block with a dashed-underline header row.
  The prior description ("`*bold*` header + space-aligned data") reflected
  the pre-#50 implementation and was stale. Closes #73.
- `detect_content_type` no longer misclassifies prose that starts with a
  lowercase strong-pattern keyword. Strong patterns were converted from
  substring checks to MULTILINE regex patterns that require syntactic
  context: `def X(`, `let/var/const X =`, `import X$`, `from X import Y`,
  etc. Prose like "let me know", "from the desk of", "import tariffs
  affect trade", "def leaves me confused", and "var is short for variable"
  is now correctly classified as text, while real code forms are still
  detected. Closes #77.
- macOS `_macos_list_formats` now deduplicates MIME types. Both
  `public.utf8-plain-text` and `public.plain-text` map to `text/plain`;
  when both UTIs are on the pasteboard, the result list previously
  contained `text/plain` twice. Closes #74.
- `clipboard_copy` now validates `mime_type` against `_MIME_RE` before
  writing to the clipboard. Previously only `clipboard_read_raw` validated;
  invalid values like `not-a-mime` or `123/456` passed through unchecked
  to the backend subprocess. Closes #75.

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
