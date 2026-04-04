Copy text to the user's system clipboard. Replaces whatever is currently
on the clipboard with the provided content.

WHEN TO CALL THIS TOOL:

Call this tool when the user says "copy this", "put this on my clipboard",
"copy to clipboard", "send to clipboard", or any phrase that implies writing
content to the clipboard.

Also call this tool when you have produced formatted output (cleaned-up JSON,
a markdown table, reformatted code, an HTML table, etc.) and the user wants
to use it outside the conversation — copying to clipboard lets them paste it
elsewhere.

Args:
    content: The text to place on the clipboard. Any string is accepted.
    mime_type: MIME type for the clipboard content (default: "text/plain").
        Use "text/html" to write HTML that applications can paste as rich
        text. Use "text/rtf" to write RTF content. Binary MIME types
        (image/*, audio/*, video/*) are rejected.
        Note: On Wayland and X11, any text/* MIME type is accepted. On
        macOS and Windows, only text/plain, text/html, and text/rtf are
        supported.

Returns:
    A confirmation message with the number of characters copied and the
    MIME type written.
