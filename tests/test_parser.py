"""Tests for the HTML/TSV parser, formatters, and content detection."""

from clipboard_mcp.parser import (
    detect_content_type,
    extract_html_text,
    format_table,
    infer_column_types,
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


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------


def test_infer_integer_column():
    rows = [["Count"], ["1"], ["42"], ["1,000"], ["99"]]
    assert infer_column_types(rows) == ["integer"]


def test_infer_float_column():
    rows = [["Score"], ["3.14"], ["2.71"], ["0.5"]]
    assert infer_column_types(rows) == ["float"]


def test_infer_currency_column():
    rows = [["Price"], ["$1.99"], ["$10.00"], ["$1,234.56"]]
    assert infer_column_types(rows) == ["currency"]


def test_infer_currency_other_symbols():
    rows = [["Amount"], ["£9.99"], ["€100"], ["¥1,000"]]
    assert infer_column_types(rows) == ["currency"]


def test_infer_percentage_column():
    rows = [["Rate"], ["10%"], ["3.5%"], ["100%"]]
    assert infer_column_types(rows) == ["percentage"]


def test_infer_date_iso():
    rows = [["Date"], ["2024-01-15"], ["2024-06-30"], ["2023-12-01"]]
    assert infer_column_types(rows) == ["date"]


def test_infer_date_us_format():
    rows = [["Date"], ["01/15/2024"], ["06/30/2024"], ["12/01/2023"]]
    assert infer_column_types(rows) == ["date"]


def test_infer_date_long_format():
    rows = [["Date"], ["January 15, 2024"], ["June 30, 2024"]]
    assert infer_column_types(rows) == ["date"]


def test_infer_boolean_column():
    rows = [["Active"], ["true"], ["false"], ["true"]]
    assert infer_column_types(rows) == ["boolean"]


def test_infer_boolean_yes_no():
    rows = [["Enabled"], ["yes"], ["no"], ["yes"]]
    assert infer_column_types(rows) == ["boolean"]


def test_infer_text_column():
    rows = [["Name"], ["Alice"], ["Bob"], ["Carol"]]
    assert infer_column_types(rows) == ["text"]


def test_infer_multiple_columns():
    rows = [
        ["Name", "Age", "Salary", "Active", "Score", "Join Date"],
        ["Alice", "30", "$75,000", "true", "9.5", "2020-01-15"],
        ["Bob", "25", "$60,000", "false", "8.2", "2021-06-30"],
        ["Carol", "35", "$90,000", "true", "9.8", "2019-03-10"],
    ]
    types = infer_column_types(rows)
    assert types == ["text", "integer", "currency", "boolean", "float", "date"]


def test_infer_empty_cells_skipped():
    """Empty cells should not affect type inference."""
    rows = [["Val"], ["42"], [""], ["17"], [""]]
    assert infer_column_types(rows) == ["integer"]


def test_infer_header_excluded():
    """Header row must not influence type inference."""
    # Header looks like text, data is all integers — should infer integer
    rows = [["Count of Items"], ["10"], ["20"], ["30"]]
    assert infer_column_types(rows) == ["integer"]


def test_infer_no_data_rows():
    """Header-only table returns empty list."""
    rows = [["Name", "Age"]]
    assert infer_column_types(rows) == []


def test_infer_empty_rows():
    assert infer_column_types([]) == []


def test_infer_majority_wins():
    """Mixed column where one type wins majority."""
    rows = [["Val"], ["42"], ["99"], ["hello"], ["17"]]
    # 3 integers, 1 text → integer wins
    assert infer_column_types(rows) == ["integer"]


def test_infer_no_majority_falls_back_to_text():
    """No type wins majority → text."""
    rows = [["Val"], ["42"], ["hello"], ["3.14"], ["world"]]
    # 1 integer, 1 text, 1 float, 1 text → text has 2, float and integer have 1 each
    # text wins majority (2/4 = 50%, not strictly > 50%) → falls back to text
    assert infer_column_types(rows) == ["text"]


def test_infer_all_empty_column():
    """A column with all empty cells returns text."""
    rows = [["A", "B"], ["1", ""], ["2", ""], ["3", ""]]
    assert infer_column_types(rows) == ["integer", "text"]


# ---------------------------------------------------------------------------
# Destination-aware formatters
# ---------------------------------------------------------------------------

_ROWS = [["Name", "Age", "City"], ["Alice", "30", "Portland"], ["Bob", "25", "Seattle"]]


def test_format_slack_code_block():
    result = format_table(_ROWS, "slack")
    assert result.startswith("```")
    assert result.endswith("```")


def test_format_slack_header_and_separator():
    result = format_table(_ROWS, "slack")
    lines = result.strip().split("\n")
    # lines[0] = opening ```, lines[1] = header, lines[2] = separator, lines[-1] = closing ```
    assert lines[1].startswith("Name")
    assert set(lines[2].replace(" ", "")) == {"-"}  # separator is all dashes


def test_format_slack_no_bold_markers():
    """Header should not use *bold* markers — they don't render when pasted."""
    result = format_table(_ROWS, "slack")
    assert "*Name*" not in result


def test_format_slack_no_pipes():
    result = format_table(_ROWS, "slack")
    assert "|" not in result


def test_format_slack_data_present():
    result = format_table(_ROWS, "slack")
    assert "Alice" in result
    assert "Bob" in result


def test_format_jira_header_syntax():
    result = format_table(_ROWS, "jira")
    assert result.startswith("||Name||")
    assert "||Age||" in result
    assert "||City||" in result


def test_format_jira_data_syntax():
    result = format_table(_ROWS, "jira")
    assert "|Alice|30|Portland|" in result
    assert "|Bob|25|Seattle|" in result


def test_format_confluence_same_as_jira():
    assert format_table(_ROWS, "confluence") == format_table(_ROWS, "jira")


def test_format_html_structure():
    result = format_table(_ROWS, "html")
    assert "<table>" in result
    assert "<thead>" in result
    assert "<th>Name</th>" in result
    assert "<th>Age</th>" in result
    assert "<tbody>" in result
    assert "<td>Alice</td>" in result
    assert "<td>30</td>" in result
    assert "</table>" in result


def test_format_html_row_count():
    result = format_table(_ROWS, "html")
    assert result.count("<tr>") == 3  # 1 header + 2 data rows


def test_format_notion_is_gfm():
    """Notion uses standard GFM pipe tables."""
    assert format_table(_ROWS, "notion") == format_table(_ROWS, "markdown")


def test_format_destination_empty():
    for fmt in ("slack", "jira", "confluence", "html", "notion"):
        assert format_table([], fmt) == ""


def test_format_destination_ragged_rows():
    """Ragged rows are padded for all destination formats."""
    rows = [["A", "B", "C"], ["1", "2"]]
    for fmt in ("slack", "jira", "confluence", "html"):
        result = format_table(rows, fmt)
        assert result  # non-empty
