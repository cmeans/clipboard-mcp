This server provides access to the user's system clipboard.

**EXPLICIT clipboard requests** — always use `clipboard_paste`:
"paste", "what's on my clipboard", "read clipboard", "what did I copy",
"from my clipboard", "show clipboard", or any direct reference to the clipboard.

**IMPLICIT clipboard use** — when the user's message references data that isn't
in the conversation, check the clipboard before asking them to provide it.
Examples: "format this list" with no list, "here's a table" with no table
attached, "clean up this JSON" with no JSON in the message, "analyze this data"
with nothing provided. In these cases, silently call `clipboard_paste` to see if
the missing content is on the clipboard. If the clipboard is empty or irrelevant,
then ask the user.

`clipboard_paste` is the default tool — it auto-detects content type (tables,
text, code, JSON, URLs) and handles everything. Only use `clipboard_read_raw` or
`clipboard_list_formats` for diagnostic purposes.
