# mcp-clipboard Windows End-to-End Test Suite

**Spec source:** awareness `logical_key=mcp-clipboard-windows-e2e-suite`, `source=mcp-clipboard-project`. Update in place via `update_entry` (preserves changelog history) when the suite evolves. Do not create a second copy.

**How a user invokes it:** "run the mcp-clipboard Windows e2e suite from awareness" (on Claude Code or Claude Desktop, both on Windows). The agent fetches this spec by logical_key and executes the section that matches its platform plus the common section.

---

## 0. Pre-flight (every run)

The agent must do all of this before running any test. If any step fails, abort the run and write a single `add_context` entry tagged `["mcp-clipboard","windows-test","preflight-fail"]` describing what failed.

1. **Identify platform — and abort if no local clipboard MCP.** The suite requires a host that has the `mcp-clipboard` MCP server wired up locally on the Windows guest. Probe by attempting `clipboard_list_formats`. If the tool is not available (the host has no local stdio MCP wiring — common on the cloud Claude.ai web client and the Anthropic-Claude desktop wrapper that proxies to claude.ai), abort with a `preflight-fail` `add_context` entry tagged `["mcp-clipboard","windows-test","preflight-fail"]` and reason `no-local-clipboard-mcp`, and stop. Do not run any tests. Otherwise determine whether the agent is running under Claude Code (CC) or Claude Desktop (CD). Record as `platform` in every result entry. Set `learned_from` accordingly: `"claude-code"` or `"claude-desktop"`.
2. **Identify mcp-clipboard version.** Call `clipboard_paste` after copying the literal string `__VERSION_PROBE__`; if the round-trip works the tool is connected. To get the version: CC runs `python -c "import mcp_clipboard; print(mcp_clipboard.__version__)"` if the package exposes it, otherwise reads `pyproject.toml` from a known install path; CD reads it from any visible config or asks the user once. Record `mcp_clipboard_version`.
3. **Identify host info.** OS build (CC: `[System.Environment]::OSVersion.VersionString` via PowerShell; CD: ask user once and record), PowerShell version (CC: `pwsh --version` or `powershell --version`), and the host application version if visible.
4. **Snapshot the user's clipboard (best-effort).** Call `clipboard_list_formats` and `clipboard_paste`. If the result is short text or empty, record it in the run-index entry under `pre_run_clipboard_snapshot`. If the clipboard contained binary or oversized content, record `pre_run_clipboard_snapshot: "binary or oversized; not preserved"` and warn the user once in chat that their clipboard contents will be overwritten by tests.
5. **Generate the run id.** `run_id = "mcp-clipboard-windows-e2e-run-" + platform + "-" + ISO8601_UTC` (e.g., `mcp-clipboard-windows-e2e-run-claude-desktop-2026-05-08T12-34-56Z`). Use this as the `logical_key` of the run-index entry created in §10.
6. **Emit a one-line chat status.** "Starting mcp-clipboard Windows e2e suite, platform=<platform>, version=<v>, run_id=<id>." That is the agent's only allowed verbose output until the final summary; per-test output during the run is one line per test (see §3).

---

## 1. Per-test result entry schema

For every test, the agent writes one `add_context` entry (so it auto-expires after 90 days; long-term comparison is via the run-index entry which uses `remember`).

```
source: "mcp-clipboard-project"
expires_days: 90
tags: ["mcp-clipboard", "windows-test", "<platform>", "<test-id>", "<class>"]
  where <class> is "wire" | "render" | "edge" | "diagnostic"
description: "<test-id> <verdict> on <platform> at <ISO timestamp> — <one-line summary>"
content: JSON-stringified object:
  {
    "run_id": "<run_id from §0>",
    "test_id": "<test-id>",
    "platform": "claude-code" | "claude-desktop",
    "agent_version": "<host app version if known>",
    "mcp_clipboard_version": "<v>",
    "started_at": "<ISO>",
    "ended_at": "<ISO>",
    "duration_ms": <int>,
    "verdict": "PASS" | "FAIL" | "SKIP" | "ERROR",
    "expected": <whatever was expected — string, bytes-as-hex, or structure>,
    "actual": <whatever was observed>,
    "diagnostics": {
      "tool_calls": [{ "tool": "...", "args": {...}, "result_summary": "..." }],
      "exception": "<message if ERROR>",
      "user_response": "<verbatim text if class=render>",
      "byte_dump": "<hex if applicable>",
      "notes": "<freeform>"
    },
    "skipped_reason": "<if SKIP>"
  }
```

---

## 2. Run-index entry schema

Written once at the end of every run (or, if the agent crashes mid-run, written after the user re-prompts).

```
source: "mcp-clipboard-project"
logical_key: "<run_id from §0>"
tags: ["mcp-clipboard", "windows-test", "<platform>", "run-index"]
description: "Windows e2e suite run on <platform> at <ISO> — N pass / M fail / S skip / E error (mcp-clipboard <v>)"
content: JSON-stringified object:
  {
    "run_id": "<run_id>",
    "platform": "...",
    "mcp_clipboard_version": "...",
    "host_info": { "os": "...", "powershell": "...", "app_version": "..." },
    "started_at": "<ISO>",
    "ended_at": "<ISO>",
    "pre_run_clipboard_snapshot": "...",
    "summary": { "pass": <n>, "fail": <n>, "skip": <n>, "error": <n>, "total": <n> },
    "test_entry_ids": { "<test-id>": "<awareness entry id>", ... },
    "first_failure": { "test_id": "...", "summary": "..." } | null,
    "post_run_clipboard_restored": <bool>
  }
```

---

## 3. Per-test execution protocol

For each test in the catalog:

1. Emit `<test-id> START` to chat (one line).
2. Run setup. Run the action. Capture actual results.
3. Compare against `expected`.
4. Construct the per-test entry (§1) and write it via `add_context`. Capture the returned entry id.
5. Emit `<test-id> <PASS|FAIL|SKIP|ERROR> — <one-line summary>` to chat.
6. Continue to the next test even if this one failed. Never abort the run on a failed assertion.

Render-class tests follow the same protocol but include a step 2.5: the agent prompts the user with a single yes/no question and captures the verbatim response in `diagnostics.user_response`. The agent must wait for the user's reply before writing the result entry.

---

## 4. Common test catalog (both CC and CD unless tagged platform-only)

Test IDs follow `mc-<NNN>` (mc = mcp-clipboard).

### Wire tests — round-trips

- **mc-001 Plain ASCII round-trip.** copy `"Hello World."` via `clipboard_copy(content="Hello World.")` → `clipboard_paste` → expect string equals input.
- **mc-002 Plain UTF-8 punctuation round-trip.** copy `"He said —"that's right'"…"` → paste → equality. Regression for #129.
- **mc-003 CJK + RTL + emoji round-trip.** copy `"日本語 العربية 🚀"` → paste → equality.
- **mc-004 Multi-line plain text.** copy `"line1\nline2\nline3"` → paste → equality (line endings may normalize on Windows; record actual bytes).
- **mc-005 SVG round-trip (markup).** copy `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="green"/></svg>` via `clipboard_copy(content=<above>, mime_type="image/svg+xml")` → `clipboard_paste` → expect output contains `<svg` and `</svg>` and the literal text matches; also record the exact bytes between `</svg>` and the closing fence (this is the watch-item probe — record but do not assert a specific value). Regression for #138.
- **mc-006 PNG round-trip.** Generate a 100×100 red PNG (16-byte header + IDAT minimal); base64-encode; call `clipboard_copy_image(image_data=<base64>, mime_type="image/png")`; paste; expect Image content with `mimeType="image/png"`. Capture base64-decoded byte length and confirm > 0.
- **mc-007 JPEG round-trip.** Same as mc-006 with a 100×100 blue JPEG.
- **mc-008 Markdown rich-text round-trip.** `clipboard_copy_markdown(text="# Heading\n\n**bold** and a [link](https://anthropic.com)")` → `clipboard_list_formats` → expect both `text/html` AND `text/plain` present (Windows multi-format) → `clipboard_read_raw(mime_type="text/html")` → expect contains `<h1` and `<strong` and the link href.
- **mc-009 HTML table round-trip.** `clipboard_copy(content="<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>", mime_type="text/html")` → `clipboard_paste` → expect output is a markdown table with cells `A | B` / `1 | 2`.
- **mc-010 RTF round-trip.** copy a known RTF blob via `clipboard_copy(content=<rtf>, mime_type="text/rtf")` → `clipboard_read_raw(mime_type="text/rtf")` → equality.

### Wire tests — auto-detect formatting

- **mc-011 JSON auto-detect.** copy `'{"a": 1, "b": [2,3]}'` (as plain text) → `clipboard_paste` → expect output contains the JSON inside a ```json fence.
- **mc-012 URL auto-detect.** copy `"https://anthropic.com/news"` → paste → expect bare URL output (no fence) per the URL detection branch.
- **mc-013 Code auto-detect.** copy `"def add(a, b):\n    return a + b\n"` → paste → expect output contains a code fence.
- **mc-014 TSV auto-detect.** copy `"name\tage\nAlice\t30\nBob\t25\n"` → paste → expect markdown table output with cells `name | age` / `Alice | 30` / `Bob | 25`.

### Wire tests — list_formats sanity

- **mc-015 list_formats after plain copy.** copy `"x"` → `clipboard_list_formats` → expect `text/plain` present.
- **mc-016 list_formats after PNG copy.** copy_image PNG → list_formats → expect `image/png` present.
- **mc-017 list_formats after SVG copy.** copy SVG → list_formats → expect `image/svg+xml` present.
- **mc-018 list_formats after markdown copy.** copy_markdown → list_formats → expect both `text/html` AND `text/plain` present (Windows: from #116 multi-format write).

### Wire tests — read_raw behavior

- **mc-019 read_raw text/plain.** copy `"raw-test"` → `clipboard_read_raw(mime_type="text/plain")` → equality.
- **mc-020 read_raw image/svg+xml.** copy SVG → `clipboard_read_raw(mime_type="image/svg+xml")` → equality of markup.
- **mc-021 read_raw rejects binary.** copy_image PNG → `clipboard_read_raw(mime_type="image/png")` → expect error or rejection (not silently returning bytes).
- **mc-022 read_raw absent format.** copy `"plain only"` → `clipboard_read_raw(mime_type="text/html")` → expect empty string (not error).

### Wire tests — edge cases

- **mc-023 Empty clipboard.** Set the clipboard to empty (CC: PowerShell `[System.Windows.Forms.Clipboard]::Clear()`; CD: copy a single space then immediately re-clear via `clipboard_copy(content="")` if supported, else SKIP and note in diagnostics) → paste → expect output `"Clipboard is empty"`.
- **mc-024 Multi-format raster+SVG dispatch.** Set both PNG + SVG on the clipboard simultaneously (CC: PowerShell DataObject with both formats; CD: SKIP because the host has no way to write two formats atomically) → paste → expect Image content (raster wins). Regression for #138 dispatch.
- **mc-025 Truncation marker.** Copy SVG markup whose total length > `_MAX_CONTENT_CHARS` (50000 chars; pad with comments) → paste → expect output contains `[truncated`. Regression for #138 truncation test coverage.
- **mc-026 Em dash byte verification (write side).** copy `"em — dash"` → `clipboard_read_raw(mime_type="text/plain")` → assert the bytes contain `0xE2 0x80 0x94` (UTF-8 encoding of em dash). Read-side verification of the #129 fix.
- **mc-027 CJK byte verification.** copy `"日本"` → `read_raw text/plain` → assert bytes contain `0xE6 0x97 0xA5 0xE6 0x9C 0xAC` (UTF-8 of 日本).
- **mc-028 SVG with non-ASCII.** copy `'<svg xmlns="http://www.w3.org/2000/svg"><text>héllo — 日本</text></svg>'` as image/svg+xml → paste → expect markup contains the non-ASCII characters intact (UTF-8 surviving the read path; partial coverage of #132).

---

## 5. Claude Code only

These tests use Bash / PowerShell / Python access that CD does not have. Tag with `platform="claude-code"`.

- **mc-101 PowerShell version capture.** `powershell -NoProfile -Command "$PSVersionTable.PSVersion.ToString()"` → record (no pass/fail; diagnostic only).
- **mc-102 Direct PowerShell read of plain.** copy `"hello"` via `clipboard_copy` → run `powershell -NoProfile -Command "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; [Console]::Write((Get-Clipboard -Raw))"` → expect stdout equals `"hello"` byte-for-byte (no trailing newline).
- **mc-103 Direct PowerShell read of SVG.** copy SVG via `clipboard_copy(mime_type="image/svg+xml")` → run a PowerShell script that calls `[System.Windows.Forms.Clipboard]::GetData('image/svg+xml')` and emits raw bytes → expect the SVG markup, hex-dump the trailing 4 bytes (record whether ends in `</svg>`, `</svg>\n`, `</svg>\r\n`, or other). The CRLF watch-item probe.
- **mc-104 Cross-check list_formats vs DataObject.** copy_markdown → run a PowerShell script that enumerates `Clipboard::GetDataObject().GetFormats()` → compare with `clipboard_list_formats` output → expect set-equality.
- **mc-105 Wheel and entry-point sanity.** `python -c "from importlib.metadata import version; print(version('mcp-clipboard'))"` → expect matches `mcp_clipboard_version` recorded in §0.

---

## 6. Claude Desktop only

These tests use rendering primitives or interactive confirmation that CC cannot do. Tag with `platform="claude-desktop"`, `class="render"`.

- **mc-201 Render: SVG round-trip.** copy SVG (green 100×100 square) → paste → ask user verbatim: *"Did a green 100×100 square render in this chat above this message? Reply 'rendered' or 'blank'."* → record the user's verbatim response in `diagnostics.user_response`. Verdict is PASS if reply normalizes to "rendered", FAIL if "blank", ERROR if anything else.
- **mc-202 Render: PNG round-trip.** copy_image PNG (red 100×100 square) → paste → ask user verbatim: *"Did a red 100×100 square render above? Reply 'rendered' or 'blank'."* → same scoring.
- **mc-203 Render: JPEG round-trip.** Same as mc-202 with blue JPEG.
- **mc-204 Render: HTML table round-trip.** `clipboard_copy(content="<table><tr><th>Col1</th><th>Col2</th></tr><tr><td>foo</td><td>bar</td></tr></table>", mime_type="text/html")` → paste → ask user: *"Did a 2×2 table with cells foo / bar render above? Reply 'rendered' or 'blank'."* → same scoring.
- **mc-205 Render: markdown rich text → host display.** copy_markdown with `"# Heading\n\n**bold** _italic_"` → ask user: *"Now switch to Slack/Notion/another rich-text app and paste. Did the heading and bold/italic formatting come through? Reply 'yes', 'partial', or 'no'."* → PASS only on `"yes"`. SKIP if user replies "no rich-text target available".
- **mc-206 Render comparison: visualize show_widget.** call the configured `visualize:show_widget` (or whichever widget tool the host exposes) directly with the same SVG markup → ask user: *"Did a green square render in chat from this widget call? Reply 'rendered' or 'blank'."* → diagnostic for separating CD's widget renderer from clipboard_paste output. Don't compute pass/fail on this; record both responses for comparison with mc-201.

---

## 7. Failure-mode probes (both platforms)

Run only if any of mc-005, mc-020, mc-024, mc-025, mc-201 failed in this run. Tagged `class="diagnostic"`.

- **mc-301 Trailing-byte probe.** copy SVG → read_raw image/svg+xml → record the byte count and the last 4 bytes as hex in diagnostics. Do not assert a value. Helps the maintainer correlate render outcomes with byte shape.
- **mc-302 Byte-equality probe.** Copy 8 known SVG inputs of varying length; for each, read back via `clipboard_read_raw` and compute SHA-256 of input vs output. Record both hashes in diagnostics. Helps detect intermittent corruption ("flake" vs "deterministic loss").
- **mc-303 Repeated-render flake check (CD only).** Run mc-201 five times in a row. Verdict is PASS only if all 5 are user-confirmed `"rendered"`. Helps distinguish "always broken" from "flake".

---

## 8. Teardown (every run)

1. **Restore clipboard.** If `pre_run_clipboard_snapshot` was capturable plain text, call `clipboard_copy(content=<snapshot>)` to restore. Set `post_run_clipboard_restored = true` in the run-index entry. If snapshot was binary or oversized, set `post_run_clipboard_restored = false` and explicitly note in the final chat summary.
2. **Write the run-index entry.** Use `remember` (permanent) with `logical_key=<run_id>`. Schema in §2.
3. **Final chat summary (one or two sentences).** "Run <run_id>: N pass / M fail / S skip / E error. Index entry id <id>. First failure: <test-id>: <summary>." If all pass, just "Run <run_id> all green (N tests)." Nothing else; the maintainer reads details from awareness.

---

## 9. Cross-run analysis (maintainer queries; not part of a run)

For reference, the maintainer can query awareness as follows:

- All runs: `get_knowledge(tags=["mcp-clipboard", "windows-test", "run-index"], mode="list")`
- All results for a single test across runs: `get_knowledge(tags=["mcp-clipboard", "windows-test", "mc-201"], mode="list")`
- All failures in the last 7 days: `get_knowledge(tags=["mcp-clipboard", "windows-test"], since="<ISO 7 days ago>", mode="list")` and filter description contains `FAIL`.
- One specific run's per-test entries: pull the run-index entry, read `test_entry_ids`, then `get_actions` or direct queries by id.

---

## 10. Maintenance

- Test ids never get reused. If a test is removed, its id is retired and skipped going forward (recorded in this spec's history section).
- New tests append at the end of the relevant section with the next available id.
- This spec is updated via `update_entry` against `logical_key=mcp-clipboard-windows-e2e-suite`. Awareness keeps a changelog automatically.
- The CD-Windows trailing-CRLF watch item documented in `mcp-clipboard-pr138-status` is what mc-005 / mc-103 / mc-301 / mc-201 collectively probe. If any single run has mc-201 PASS while mc-301 records the trailing CRLF as absent, that's the signal that CD-Windows render no longer requires the CRLF and the cleanup can be revisited.
