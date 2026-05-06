Render markdown to HTML and place both formats on the system clipboard so
the user can paste rich text into apps that prefer formatted content
(Slack, Gmail, Notion, Word, Google Docs, Discord) AND plain markdown
into apps that prefer source (text editors, terminals).

WHEN TO CALL THIS TOOL:

Call this tool when the user wants formatted output to paste into a
rich-text target — bulleted lists, headings, links, code, bold/italic
emphasis. Examples: "summarize these emails as a list and copy it",
"copy this as formatted text", "put this on my clipboard so I can paste
it into Slack with formatting", "give me a markdown bullet list and
copy it."

For plain text without formatting intent, use `clipboard_copy` instead.

Args:
    text: Markdown source. Standard CommonMark syntax (headings, lists,
        emphasis, code blocks, links, etc.) is rendered to HTML. Raw
        HTML tags in the source are escaped, not passed through — if
        you need to write hand-crafted HTML, call `clipboard_copy` with
        `mime_type="text/html"` instead.

Returns:
    A confirmation message with the input character count and the
    rendered HTML byte count.

Platform behavior:
    - macOS and Windows: both `text/html` and `text/plain` (the markdown
      source) land on the clipboard atomically. Each paste target picks
      the format it prefers — Slack/Gmail/Notion get the rendered HTML;
      vim/terminal/text editors get the markdown source.
    - Wayland and X11: the underlying `wl-copy` and `xclip` tools only
      carry one MIME per invocation, so only `text/html` is set. Apps
      that consume HTML (Slack, Gmail, Discord, browsers) render it;
      apps that only read `text/plain` (terminals, vim, basic editors)
      will see an empty clipboard. For a plain-text paste on Linux,
      call `clipboard_copy` with the markdown source directly.
