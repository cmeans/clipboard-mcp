Read raw clipboard content in a specific MIME format. Diagnostic tool only —
use clipboard_paste instead for normal clipboard access.

This tool returns the clipboard content as-is without any parsing or
restructuring. Use clipboard_list_formats first to see what MIME types are
available.

Supports any non-binary MIME type. The most common values are text/*
types, plus image/svg+xml (text-readable despite the image/ prefix).
application/* types pass through as well (application/json,
application/xml, application/xhtml+xml, etc.) because the only blocked
prefixes are image/, audio/, video/, and the exact type
application/octet-stream. Binary MIME types are rejected; use
clipboard_paste for images.

Args:
    mime_type: The MIME type to read from the clipboard.
        Common values: "text/plain", "text/html", "image/svg+xml",
        "application/json"

Returns:
    The raw clipboard content in the requested format, or an error message.
