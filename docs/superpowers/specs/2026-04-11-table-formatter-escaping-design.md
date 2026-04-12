# Table Formatter Escaping -- Design Spec

**Date:** 2026-04-11
**Issues:** #16, #17, #18 (skipping #15 -- potential contributor)
**Scope:** Fix pipe-character escaping in Markdown/Notion and Jira/Confluence formatters; add escaping test matrix for all output formats.

## Problem

`_format_markdown` and `_format_jira` in `parser.py` interpolate raw cell values into pipe-delimited table syntax. A cell containing `|` breaks the table structure in every downstream renderer. Backslash `\` also needs escaping since it is the escape character in both formats.

Zero tests cover special characters in any formatter.

## Approach

Per-formatter escape helpers (Approach A). Each formatter gets its own escape function. The logic is identical today (`\` -> `\\`, then `|` -> `\|`), but separate helpers keep each formatter self-contained and extensible for format-specific concerns later.

## PR 1: Fix #16 -- Markdown/Notion pipe escaping

### Changes in `src/mcp_clipboard/parser.py`

Add helper:

```python
def _escape_md_cell(cell: str) -> str:
    """Escape characters that break GFM pipe tables."""
    return cell.replace("\\", "\\\\").replace("|", "\\|")
```

Modify `_format_markdown()`:
- Apply `_escape_md_cell()` to every cell value in header and data rows
- Compute column widths from the *escaped* values so alignment is correct
- Apply escaping *before* `ljust()` padding

Notion routes through `_format_markdown` -- no additional changes needed.

### Tests

Add tests in `tests/test_parser.py` (alongside existing formatter tests):
- Cell containing `|` -- assert column count preserved, pipe escaped in output
- Cell containing `||` -- same
- Cell containing `\` -- assert escaped to `\\`
- Cell containing `\|` -- assert escaped to `\\|` (no ambiguity)
- Leading/trailing `|` in a cell

## PR 2: Fix #17 -- Jira/Confluence pipe escaping

### Changes in `src/mcp_clipboard/parser.py`

Add helper:

```python
def _escape_jira_cell(cell: str) -> str:
    """Escape characters that break Jira/Confluence wiki markup tables."""
    return cell.replace("\\", "\\\\").replace("|", "\\|")
```

Modify `_format_jira()`:
- Apply `_escape_jira_cell()` to every cell value in header and data rows

Confluence routes through `_format_jira` -- no additional changes needed.

### Tests

Add tests in `tests/test_parser.py`:
- Cell containing `|` -- assert column count preserved, pipe escaped
- Cell containing `||` -- assert no accidental header promotion
- Cell containing `\` -- assert escaped
- Leading/trailing `|` in a cell

## PR 3: Fix #18 -- Escaping test matrix

### New file: `tests/test_escaping.py`

Parametrized test matrix covering every `OutputFormat` with special characters.

### Merge strategy

PR 3 rebases onto main after PRs 1 and 2 are merged. Markdown/Notion/Jira/Confluence pipe tests are passing assertions (not xfails).

## Out of scope

- #15: HTML XSS (`_format_html` cell escaping) -- potential contributor
- #19: Slack `*` and backtick escaping -- medium priority, separate PR
- #20: `detect_content_type` false positives -- unrelated
