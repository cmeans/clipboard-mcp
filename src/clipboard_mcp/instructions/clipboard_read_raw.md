Read raw clipboard content in a specific MIME format. Diagnostic tool only —
use clipboard_paste instead for normal clipboard access.

This tool returns the clipboard content as-is without any parsing or
restructuring. Use clipboard_list_formats first to see what MIME types are
available.

Args:
    mime_type: The MIME type to read from the clipboard.
        Common values: "text/plain", "text/html"

Returns:
    The raw clipboard content in the requested format, or an error message.
