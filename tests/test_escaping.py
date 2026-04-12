"""Parametrized escaping/special-character tests for all output formats.

Covers issue #18. Tests for formats with known unfixed escaping bugs
are marked xfail so they document the gap without blocking CI.
"""

from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser

import pytest

from mcp_clipboard.parser import OutputFormat, format_table

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Each entry: (id, cell_value)
SPECIAL_CHARS: list[tuple[str, str]] = [
    ("pipe", "a|b"),
    ("double-pipe", "a||b"),
    ("backslash", "a\\b"),
    ("backslash-pipe", "a\\|b"),
    ("leading-pipe", "|leading"),
    ("trailing-pipe", "trailing|"),
    ("both-pipes", "|both|"),
    ("angle-brackets", "<b>bold</b>"),
    ("ampersand", "A&B"),
    ("double-quote", 'say "hello"'),
    ("single-quote", "it's"),
    ("asterisk", "a*b*c"),
    ("backtick", "use `code` here"),
    ("triple-backtick", "```block```"),
    ("tilde-fence", "~~~fence~~~"),
    ("newline", "line1\nline2"),
    ("empty", ""),
    ("whitespace-only", "   "),
    ("cjk", "\u4f60\u597d\u4e16\u754c"),
    ("emoji", "\U0001f680\U0001f30d"),
]

ALL_FORMATS: list[OutputFormat] = [
    "markdown",
    "json",
    "csv",
    "slack",
    "jira",
    "confluence",
    "html",
    "notion",
]

# Known unfixed bugs -- xfail these specific (format, char) combos
_XFAIL_MAP: dict[tuple[str, str], str] = {}
for _fmt in ("html",):
    for _char_id in ("angle-brackets", "ampersand", "double-quote"):
        _XFAIL_MAP[(_fmt, _char_id)] = "see #15"
for _fmt in ("slack",):
    for _char_id in ("asterisk", "backtick", "triple-backtick"):
        _XFAIL_MAP[(_fmt, _char_id)] = "see #19"
# Newlines in cells break line-based formats (markdown, jira, slack) -- no escape exists
for _fmt in ("markdown", "notion", "jira", "confluence", "slack"):
    _XFAIL_MAP[(_fmt, "newline")] = "newlines in cells break line-based table formats"


def _make_rows(special_value: str) -> list[list[str]]:
    """Build a 3-col, 3-row table with the special value in one data cell."""
    return [
        ["Header1", "Header2", "Header3"],
        [special_value, "normal", "data"],
        ["more", special_value, "rows"],
    ]


# ---------------------------------------------------------------------------
# Format-specific column-count verifiers
# ---------------------------------------------------------------------------


def _count_md_columns(line: str) -> int:
    """Count columns in a GFM pipe-table line."""
    parts = re.split(r"(?<!\\)\|", line)
    # GFM lines: "" | cell | cell | "" (leading/trailing empty from split)
    return len(parts) - 2


def _count_jira_header_columns(line: str) -> int:
    """Count columns in a Jira ||header|| line."""
    inner = line.strip("|")
    parts = re.split(r"(?<!\\)\|\|", "||" + inner + "||")
    return len(parts) - 2


def _count_jira_data_columns(line: str) -> int:
    """Count columns in a Jira |data| line."""
    parts = re.split(r"(?<!\\)\|", line)
    return len(parts) - 2


class _CellCounter(HTMLParser):
    """Count th and td elements in an HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self.th_count = 0
        self.td_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "th":
            self.th_count += 1
        elif tag == "td":
            self.td_count += 1


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ALL_FORMATS)
@pytest.mark.parametrize(
    "char_id, char_value",
    SPECIAL_CHARS,
    ids=[cid for cid, _ in SPECIAL_CHARS],
)
def test_escaping_preserves_structure(fmt: str, char_id: str, char_value: str) -> None:
    """For every (format, special_char) combo, output must preserve table structure."""
    xfail_reason = _XFAIL_MAP.get((fmt, char_id))
    if xfail_reason:
        pytest.xfail(xfail_reason)

    rows = _make_rows(char_value)
    result = format_table(rows, fmt)  # type: ignore[arg-type]
    assert result, f"format_table returned empty for fmt={fmt}, char_id={char_id}"

    if fmt in ("markdown", "notion"):
        lines = result.strip().split("\n")
        assert len(lines) == 4, f"Expected 4 lines (hdr+sep+2 data), got {len(lines)}"
        for i, line in enumerate(lines):
            if i == 1:  # separator
                continue
            cols = _count_md_columns(line)
            assert cols == 3, f"Line {i} has {cols} cols, expected 3: {line}"

    elif fmt in ("jira", "confluence"):
        lines = result.strip().split("\n")
        assert len(lines) == 3, f"Expected 3 lines (hdr+2 data), got {len(lines)}"
        hdr_cols = _count_jira_header_columns(lines[0])
        assert hdr_cols == 3, f"Header has {hdr_cols} cols, expected 3: {lines[0]}"
        for i, line in enumerate(lines[1:], start=1):
            data_cols = _count_jira_data_columns(line)
            assert data_cols == 3, f"Data line {i} has {data_cols} cols, expected 3: {line}"

    elif fmt == "json":
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2  # 2 data rows (header becomes keys)
        for obj in data:
            assert len(obj) == 3, f"Expected 3 keys, got {len(obj)}: {obj}"

    elif fmt == "csv":
        reader = csv.reader(io.StringIO(result))
        csv_rows = list(reader)
        assert len(csv_rows) == 3  # header + 2 data
        for i, csv_row in enumerate(csv_rows):
            assert len(csv_row) == 3, f"CSV row {i} has {len(csv_row)} cols: {csv_row}"

    elif fmt == "html":
        counter = _CellCounter()
        counter.feed(result)
        assert counter.th_count == 3, f"Expected 3 <th>, got {counter.th_count}"
        assert counter.td_count == 6, f"Expected 6 <td>, got {counter.td_count}"

    elif fmt == "slack":
        header_line = result.split("\n")[0]
        bold_count = len(re.findall(r"\*[^*]+\*", header_line))
        assert bold_count == 3, f"Expected 3 bold headers, got {bold_count}: {header_line}"
        assert "```" in result


ROUND_TRIP_FORMATS: list[OutputFormat] = ["csv", "json"]


@pytest.mark.parametrize("fmt", ROUND_TRIP_FORMATS)
@pytest.mark.parametrize(
    "char_id, char_value",
    SPECIAL_CHARS,
    ids=[cid for cid, _ in SPECIAL_CHARS],
)
def test_escaping_round_trip(fmt: str, char_id: str, char_value: str) -> None:
    """For round-trippable formats (csv, json), verify the original value is recoverable."""

    xfail_reason = _XFAIL_MAP.get((fmt, char_id))
    if xfail_reason:
        pytest.xfail(xfail_reason)

    rows = _make_rows(char_value)
    result = format_table(rows, fmt)  # type: ignore[arg-type]

    if fmt == "json":
        data = json.loads(result)
        values = [v for obj in data for v in obj.values()]
        assert char_value in values, f"Value {char_value!r} not found in JSON output"

    elif fmt == "csv":
        reader = csv.reader(io.StringIO(result))
        all_values = [cell for row in reader for cell in row]
        assert char_value in all_values, f"Value {char_value!r} not found in CSV output"
