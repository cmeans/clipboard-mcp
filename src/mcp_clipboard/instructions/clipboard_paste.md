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
code, JSON, URLs, rich text, and images. Tables are auto-detected and formatted
per output_format. Non-tabular content is returned with smart formatting.
Images on the clipboard are returned directly as image content.

Args:
    output_format: Format for table data (case-insensitive). Only applies when
        the clipboard contains a table. Ignored for non-tabular content. Options:
        - "markdown" (default): GitHub-flavored Markdown table
        - "json": Array of objects keyed by header row
        - "csv": Comma-separated values
        - "slack": monospace code block with dashed-underline header row (avoids Slack mrkdwn escaping issues)
        - "jira": ||Header|| / |Cell| wiki markup (also works for Confluence)
        - "confluence": same as jira
        - "html": <table> with <thead>/<th>/<tbody>/<td>
        - "notion": GFM pipe table (Notion renders these natively)
    include_schema: When True and the clipboard contains a table, append a
        column-type schema table after the data. Inferred types: integer, float,
        currency, percentage, date, boolean, text. Defaults to False.
    selection: Which buffer to read. Defaults to "clipboard" (the standard
        Ctrl-C / Cmd-C clipboard). Pass "primary" to read the X11 PRIMARY
        selection (middle-click / select-text-to-paste buffer) or the
        analogous Wayland primary selection. macOS and Windows have no
        PRIMARY analog and will return an error if "primary" is passed.

Returns:
    The clipboard content, formatted appropriately for the content type.
    Images are returned as image content (base64-encoded) for visual analysis.
