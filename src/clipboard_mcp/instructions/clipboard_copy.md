Copy text to the user's system clipboard. Replaces whatever is currently
on the clipboard with the provided content.

WHEN TO CALL THIS TOOL:

Call this tool when the user says "copy this", "put this on my clipboard",
"copy to clipboard", "send to clipboard", or any phrase that implies writing
content to the clipboard.

Also call this tool when you have produced formatted output (cleaned-up JSON,
a markdown table, reformatted code, etc.) and the user wants to use it
outside the conversation — copying to clipboard lets them paste it elsewhere.

Args:
    content: The text to place on the clipboard. Any string is accepted.

Returns:
    A confirmation message with the number of characters copied.
