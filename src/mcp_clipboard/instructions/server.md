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
text, code, JSON, URLs, images) and handles everything. Images on the clipboard
are returned directly as image content for visual analysis. Only use
`clipboard_read_raw` or `clipboard_list_formats` for diagnostic purposes.

Use `clipboard_copy` to write text to the clipboard when the user wants to copy
formatted output, cleaned-up data, or any text for use outside the conversation.

Use `clipboard_copy_image` to write a PNG or JPEG image to the clipboard. Pass
base64-encoded bytes (the same encoding `clipboard_paste` returns for image
content). Use this when the user has produced or fetched an image and wants to
paste it elsewhere; for text content, use `clipboard_copy` instead.

Use `clipboard_copy_markdown` when the user wants formatted output to paste
into a rich-text target (Slack, Gmail, Notion, Word, Google Docs, Discord) —
bulleted lists, headings, links, code, bold/italic. The markdown is rendered
to HTML and (on macOS/Windows) both formats land on the clipboard atomically
so each paste target picks the right one. On Wayland/X11 only `text/html`
is set due to a single-MIME-per-call limit; for plain-text paste on Linux,
call `clipboard_copy` with the markdown source directly.
