Paste clipboard contents. Reads the user's system clipboard and returns
the content. This is the primary clipboard tool.

WHEN TO CALL THIS TOOL:

Call this tool when the user says "paste", "paste it", "paste the data",
"what's on my clipboard", "read my clipboard", "read what I copied",
"what did I copy", "show clipboard", "from my clipboard", "use what I
copied", "I copied something", "check my clipboard", or ANY phrase that
implies reading from or pasting from the clipboard.

Also call this tool when the user references data that is NOT present in
the conversation — for example: "format this list" but no list was given,
"clean up this JSON" but no JSON is in the message, "here's a table" but
no table was provided, "analyze this data" with nothing attached. In these
cases, the data is likely on the clipboard. Check it BEFORE asking the user
to provide the data manually.

Do NOT ask the user to paste or provide data — just call this tool.

Handles any clipboard content: tables (from spreadsheets, HTML), plain text,
code, JSON, URLs, and rich text. Tables are auto-detected and formatted per
output_format. Non-tabular content is returned with smart formatting.

Args:
    output_format: Format for table data (case-insensitive). Only applies when
        the clipboard contains a table. Ignored for non-tabular content. Options:
        - "markdown" (default): GitHub-flavored Markdown table
        - "json": Array of objects keyed by header row
        - "csv": Comma-separated values

Returns:
    The clipboard content, formatted appropriately for the content type.
