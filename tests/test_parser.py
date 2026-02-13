"""Tests for the HTML/TSV parser, formatters, and content detection."""

from clipboard_mcp.parser import (
    detect_content_type,
    extract_html_text,
    format_table,
    parse_html_table,
    parse_tsv,
)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


GOOGLE_SHEETS_HTML = """
<meta charset='utf-8'>
<google-sheets-html-origin>
<style type="text/css"><!--td {border: 1px solid #ccc;}--></style>
<table xmlns="http://www.w3.org/1999/xhtml" cellspacing="0" cellpadding="0" dir="ltr"
       border="1" style="table-layout:fixed;font-size:10pt;font-family:Arial;">
  <colgroup><col width="100"/><col width="100"/><col width="100"/></colgroup>
  <tbody>
    <tr style="height:21px;">
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Name"}'>Name</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Age"}'>Age</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"City"}'>City</td>
    </tr>
    <tr style="height:21px;">
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Alice"}'>Alice</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":3,"3":30}'>30</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Portland"}'>Portland</td>
    </tr>
    <tr style="height:21px;">
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Bob"}'>Bob</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":3,"3":25}'>25</td>
      <td style="padding:2px 3px;" data-sheets-value='{"1":2,"2":"Seattle"}'>Seattle</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_google_sheets_html():
    rows = parse_html_table(GOOGLE_SHEETS_HTML)
    assert len(rows) == 3
    assert rows[0] == ["Name", "Age", "City"]
    assert rows[1] == ["Alice", "30", "Portland"]
    assert rows[2] == ["Bob", "25", "Seattle"]


SIMPLE_HTML = """
<table>
<tr><th>Col A</th><th>Col B</th></tr>
<tr><td>1</td><td>2</td></tr>
</table>
"""


def test_parse_simple_html():
    rows = parse_html_table(SIMPLE_HTML)
    assert len(rows) == 2
    assert rows[0] == ["Col A", "Col B"]
    assert rows[1] == ["1", "2"]


def test_parse_html_no_table():
    rows = parse_html_table("<p>No table here</p>")
    assert rows == []


def test_parse_html_empty():
    rows = parse_html_table("")
    assert rows == []


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------


def test_parse_tsv_basic():
    text = "Name\tAge\tCity\nAlice\t30\tPortland\nBob\t25\tSeattle"
    rows = parse_tsv(text)
    assert len(rows) == 3
    assert rows[0] == ["Name", "Age", "City"]
    assert rows[1] == ["Alice", "30", "Portland"]


def test_parse_tsv_no_tabs():
    rows = parse_tsv("just plain text with no tabs")
    assert rows == []


def test_parse_tsv_single_column():
    # No tabs means not tabular
    rows = parse_tsv("line1\nline2\nline3")
    assert rows == []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_markdown():
    rows = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]
    md = format_table(rows, "markdown")
    assert "| Name" in md
    assert "| ---" in md
    assert "| Alice" in md


def test_format_json():
    rows = [["Name", "Age"], ["Alice", "30"]]
    result = format_table(rows, "json")
    import json
    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["Name"] == "Alice"
    assert data[0]["Age"] == "30"


def test_format_json_single_column():
    """Single-column JSON should be a flat array of values."""
    import json
    rows = [["821 W Gunnison St"], ["1283 W Victoria St"], ["5533 N Glenwood Ave"]]
    result = format_table(rows, "json")
    data = json.loads(result)
    assert data == ["821 W Gunnison St", "1283 W Victoria St", "5533 N Glenwood Ave"]


def test_format_csv():
    rows = [["A", "B"], ["1", "2"]]
    result = format_table(rows, "csv")
    assert '"A","B"' in result
    assert '"1","2"' in result


def test_format_csv_single_column():
    """Single-column CSV should still look like CSV (quoted values)."""
    rows = [["Address"], ["123 Main St"], ["456 Oak Ave"]]
    result = format_table(rows, "csv")
    assert '"Address"' in result
    assert '"123 Main St"' in result
    assert '"456 Oak Ave"' in result


def test_format_empty():
    assert format_table([], "markdown") == ""
    assert format_table([], "json") == ""
    assert format_table([], "csv") == ""


def test_format_ragged_rows_markdown():
    """Rows with different column counts should be padded."""
    rows = [["A", "B", "C"], ["1", "2"]]
    md = format_table(rows, "markdown")
    # The second row should be padded to 3 columns
    lines = md.strip().split("\n")
    assert len(lines) == 3  # header + separator + 1 data row
    # Count pipes in each line — should be consistent
    assert lines[0].count("|") == lines[2].count("|")


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


def test_extract_html_text_paragraphs():
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    text = extract_html_text(html)
    assert "First paragraph." in text
    assert "Second paragraph." in text
    # Paragraphs should be on separate lines
    assert "\n" in text


def test_extract_html_text_with_tags():
    html = "<b>Bold</b> and <i>italic</i> text"
    text = extract_html_text(html)
    assert text == "Bold and italic text"


def test_extract_html_text_strips_script_style():
    html = "<style>body { color: red; }</style><p>Visible</p><script>alert('x')</script>"
    text = extract_html_text(html)
    assert "Visible" in text
    assert "color" not in text
    assert "alert" not in text


def test_extract_html_text_br_newlines():
    html = "Line one<br>Line two<br/>Line three"
    text = extract_html_text(html)
    assert "Line one" in text
    assert "Line two" in text
    assert "Line three" in text


def test_extract_html_text_list_items():
    html = "<ul><li>Item 1</li><li>Item 2</li><li>Item 3</li></ul>"
    text = extract_html_text(html)
    assert "Item 1" in text
    assert "Item 2" in text
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) >= 3


def test_extract_html_text_empty():
    assert extract_html_text("") == ""


# ---------------------------------------------------------------------------
# Content-type detection
# ---------------------------------------------------------------------------


def test_detect_json_object():
    assert detect_content_type('{"name": "Alice", "age": 30}') == "json"


def test_detect_json_array():
    assert detect_content_type('[1, 2, 3]') == "json"


def test_detect_json_invalid():
    """Starts with { but isn't valid JSON — should not be detected as JSON."""
    assert detect_content_type("{this is not json}") != "json"


def test_detect_url_https():
    assert detect_content_type("https://example.com/path?q=1") == "url"


def test_detect_url_http():
    assert detect_content_type("http://example.com") == "url"


def test_detect_url_multiline_not_url():
    """Multiple lines starting with URL should not be detected as url."""
    text = "https://example.com\nhttps://other.com"
    assert detect_content_type(text) != "url"


def test_detect_code_python():
    code = "def hello():\n    print('hello world')\n\nhello()"
    assert detect_content_type(code) == "code"


def test_detect_code_javascript():
    code = "const x = 42;\nfunction add(a, b) { return a + b; }"
    assert detect_content_type(code) == "code"


def test_detect_code_indented():
    """Heavily indented text should be detected as code."""
    code = "main:\n    step 1\n    step 2\n    step 3\n    step 4"
    assert detect_content_type(code) == "code"


def test_detect_plain_text():
    assert detect_content_type("Hello, this is just a plain sentence.") == "text"


def test_detect_empty():
    assert detect_content_type("") == "text"
    assert detect_content_type("   ") == "text"
