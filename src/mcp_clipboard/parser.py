"""Parse clipboard content: HTML tables, plain text, and content-type detection.

Uses only the Python standard library (html.parser). Designed to handle the HTML
that Google Sheets and Excel place on the clipboard when cells are copied, as well
as arbitrary non-tabular content (plain text, code, JSON, URLs).
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Literal


class _TableExtractor(HTMLParser):
    """Extract rows/cells from the first <table> in an HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_table = False
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if not self._in_table:
                self._in_table = True
        elif self._in_table and self._table_depth == 1:
            if tag == "tr":
                self._current_row = []
            elif tag in ("td", "th"):
                self._current_cell = []
            elif tag == "br" and self._current_cell is not None:
                self._current_cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_table = False
        elif self._in_table and self._table_depth == 1:
            if tag in ("td", "th") and self._current_cell is not None:
                text = "".join(self._current_cell).strip()
                if self._current_row is not None:
                    self._current_row.append(text)
                self._current_cell = None
            elif tag == "tr" and self._current_row is not None:
                self.rows.append(self._current_row)
                self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)


def parse_html_table(html: str) -> list[list[str]]:
    """Extract the first table from an HTML string as a list of rows.

    Returns an empty list if no table is found.
    """
    parser = _TableExtractor()
    parser.feed(html)
    return parser.rows


def parse_tsv(text: str) -> list[list[str]]:
    """Parse tab-separated text into rows.

    Returns an empty list if the text doesn't appear to be tabular
    (i.e., has no tabs or only a single cell).

    Handles RFC 4180-style quoting so that fields containing embedded
    tabs or newlines are kept intact when wrapped in double quotes.
    """
    if "\t" not in text:
        return []

    rows: list[list[str]] = []
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    for row in reader:
        if any(cell.strip() for cell in row):
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# HTML-to-text extraction (for non-table HTML)
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract readable text."""

    # Tags that should insert a newline when opened
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            self._skip = True
        elif tag in self._BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._pieces.append(data)


def extract_html_text(html: str) -> str:
    """Strip HTML tags and return readable plain text.

    Inserts newlines at block boundaries (p, div, br, li, etc.).
    Strips script/style content. Returns empty string for empty input.
    """
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    # Collapse multiple blank lines, strip leading/trailing whitespace
    text = "".join(parser._pieces)
    lines = [line.strip() for line in text.splitlines()]
    # Remove consecutive empty lines
    result: list[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return "\n".join(result).strip()


# ---------------------------------------------------------------------------
# Content-type detection (for non-tabular text)
# ---------------------------------------------------------------------------

ContentType = Literal["json", "url", "code", "text"]

# Code indicators: patterns that suggest the text is source code
_CODE_PATTERNS = (
    "def ", "class ", "import ", "from ", "return ",   # Python
    "function ", "const ", "let ", "var ",              # JavaScript
    "func ", "package ",                                # Go
    "public ", "private ", "protected ",                # Java/C#
    "fn ", "pub ", "mod ",                               # Rust
    "=>", "->", "::","&&", "||",                        # Operators
    "if (", "for (", "while (",                         # Control flow
    "#!/",                                              # Shebang
)


def detect_content_type(text: str) -> ContentType:
    """Classify plain text content as json, url, code, or text."""
    stripped = text.strip()
    if not stripped:
        return "text"

    # JSON: starts with { or [ and parses successfully
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass

    # URL: single line, starts with http:// or https://
    lines = stripped.splitlines()
    if len(lines) == 1 and (stripped.startswith("http://") or stripped.startswith("https://")):
        return "url"

    # Code: check for common patterns
    for pattern in _CODE_PATTERNS:
        if pattern in stripped:
            return "code"

    # Code: significant indentation (4+ spaces or tabs at start of lines)
    indented_lines = sum(1 for line in lines if line.startswith("    ") or line.startswith("\t"))
    if len(lines) > 2 and indented_lines / len(lines) > 0.3:
        return "code"

    return "text"


# ---------------------------------------------------------------------------
# Table schema inference
# ---------------------------------------------------------------------------

ColumnType = Literal["integer", "float", "currency", "percentage", "date", "boolean", "text"]

_BOOLEAN_VALUES = frozenset({"true", "false", "yes", "no"})
_INTEGER_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})*|\d+)$")
_FLOAT_RE = re.compile(r"^[+-]?\d*\.\d+$|^[+-]?\d+\.\d+$")
_CURRENCY_RE = re.compile(
    r"^[£$€¥]\s*-?\d{1,3}(,\d{3})*(\.\d{1,2})?$"
    r"|^-?\d{1,3}(,\d{3})*(\.\d{1,2})?\s*[£$€¥]$"
)
_PERCENTAGE_RE = re.compile(r"^-?\d+(\.\d+)?%$")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


def _classify_cell(value: str) -> ColumnType:
    """Classify a single non-empty cell value as the most specific type."""
    v = value.strip()

    if v.lower() in _BOOLEAN_VALUES:
        return "boolean"

    # Percentage before float/integer (ends with %)
    if _PERCENTAGE_RE.match(v):
        return "percentage"

    # Currency before integer/float (starts/ends with symbol)
    if _CURRENCY_RE.match(v):
        return "currency"

    # Integer before float (no decimal point)
    if _INTEGER_RE.match(v):
        return "integer"

    if _FLOAT_RE.match(v):
        return "float"

    # Date: ISO format first, then common regional formats
    try:
        datetime.fromisoformat(v)
        return "date"
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(v, fmt)
            return "date"
        except ValueError:
            continue

    return "text"


def infer_column_types(rows: list[list[str]]) -> list[ColumnType]:
    """Infer the data type of each column from a table.

    The first row is treated as a header and excluded from inference.
    Empty cells are skipped. Majority-wins: if more than half of the
    non-empty cells in a column match a specific type, that type is
    used; otherwise the column is typed as ``text``.

    Returns one :data:`ColumnType` per column (based on the widest row),
    or an empty list when there are fewer than 2 rows (no data to infer from).
    """
    if len(rows) < 2:
        return []

    data_rows = rows[1:]
    num_cols = max(len(row) for row in rows)

    result: list[ColumnType] = []
    for col_idx in range(num_cols):
        type_counts: dict[str, int] = {}
        non_empty = 0

        for row in data_rows:
            if col_idx >= len(row):
                continue
            cell = row[col_idx].strip()
            if not cell:
                continue
            non_empty += 1
            col_type = _classify_cell(cell)
            type_counts[col_type] = type_counts.get(col_type, 0) + 1

        if not non_empty:
            result.append("text")
            continue

        best_type = max(type_counts, key=lambda t: type_counts[t])
        if type_counts[best_type] > non_empty / 2:
            result.append(best_type)  # type: ignore[arg-type]
        else:
            result.append("text")

    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

OutputFormat = Literal["markdown", "json", "csv", "slack", "jira", "confluence", "html", "notion"]


def format_table(rows: list[list[str]], fmt: OutputFormat = "markdown") -> str:
    """Format parsed rows into the requested output format.

    For JSON output: single-column tables produce a flat array of values;
    multi-column tables use the first row as object keys.
    """
    if not rows:
        return ""

    if fmt == "json":
        max_cols = max(len(r) for r in rows)
        if max_cols == 1:
            # Single-column: flat array of values
            data: list = [row[0] for row in rows]
        elif len(rows) > 1:
            # Multi-column: use first row as header keys
            header = rows[0]
            data = [dict(zip(header, row)) for row in rows[1:]]
        else:
            # Single row, multiple columns
            data = [{"values": row} for row in rows]
        return json.dumps(data, indent=2, ensure_ascii=False)

    elif fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
        writer.writerows(rows)
        return buf.getvalue()

    elif fmt == "slack":
        return _format_slack(rows)

    elif fmt in ("jira", "confluence"):
        return _format_jira(rows)

    elif fmt == "html":
        return _format_html(rows)

    elif fmt == "notion":
        return _format_markdown(rows)  # Notion renders standard GFM pipe tables natively

    else:  # markdown
        return _format_markdown(rows)


def _escape_md_cell(cell: str) -> str:
    """Escape characters that break GFM pipe tables."""
    return cell.replace("\\", "\\\\").replace("|", "\\|")


def _format_markdown(rows: list[list[str]]) -> str:
    """Render rows as a GitHub-flavored Markdown table."""
    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    # Escape cells, then calculate widths from escaped values
    escaped = [[_escape_md_cell(cell) for cell in row] for row in normalized]

    widths = [
        max(len(escaped[r][c]) for r in range(len(escaped)))
        for c in range(max_cols)
    ]
    # Minimum width of 3 for the separator
    widths = [max(w, 3) for w in widths]

    lines: list[str] = []
    # Header
    header = "| " + " | ".join(
        escaped[0][c].ljust(widths[c]) for c in range(max_cols)
    ) + " |"
    lines.append(header)

    # Separator
    sep = "| " + " | ".join("-" * widths[c] for c in range(max_cols)) + " |"
    lines.append(sep)

    # Data rows
    for row in escaped[1:]:
        line = "| " + " | ".join(
            row[c].ljust(widths[c]) for c in range(max_cols)
        ) + " |"
        lines.append(line)

    return "\n".join(lines)


def _format_slack(rows: list[list[str]]) -> str:
    """Render rows for Slack: *bold* header followed by space-aligned data in a code block.

    On first paste into Slack, a one-time "Apply formatting" prompt appears.
    After accepting (or clicking "Don't ask again"), subsequent pastes apply
    the bold and code block formatting automatically.
    """
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    widths = [
        max(len(normalized[r][c]) for r in range(len(normalized)))
        for c in range(max_cols)
    ]
    widths = [max(w, 1) for w in widths]

    # Header: *bold* cells (outside the code block so Slack renders the markup)
    header = "  ".join(f"*{normalized[0][c]}*" for c in range(max_cols))

    # Data rows: space-aligned inside a monospace code block
    data_lines = [
        "  ".join(row[c].ljust(widths[c]) for c in range(max_cols)).rstrip()
        for row in normalized[1:]
    ]

    return f"{header}\n```\n" + "\n".join(data_lines) + "\n```"


def _escape_jira_cell(cell: str) -> str:
    """Escape characters that break Jira/Confluence wiki markup tables."""
    return cell.replace("\\", "\\\\").replace("|", "\\|")


def _format_jira(rows: list[list[str]]) -> str:
    """Render rows as Jira/Confluence wiki markup: ||Header|| / |Cell| syntax."""
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    escaped = [[_escape_jira_cell(cell) for cell in row] for row in normalized]

    lines = ["||" + "||".join(escaped[0]) + "||"]
    for row in escaped[1:]:
        lines.append("|" + "|".join(row) + "|")

    return "\n".join(lines)


def _format_html(rows: list[list[str]]) -> str:
    """Render rows as an HTML table with thead/tbody."""
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    lines = ["<table>", "  <thead>"]
    lines.append("    <tr>" + "".join(f"<th>{cell}</th>" for cell in normalized[0]) + "</tr>")
    lines.append("  </thead>")
    lines.append("  <tbody>")
    for row in normalized[1:]:
        lines.append("    <tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    lines.append("  </tbody>")
    lines.append("</table>")

    return "\n".join(lines)
