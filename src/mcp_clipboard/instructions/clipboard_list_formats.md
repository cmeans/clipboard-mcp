List the MIME types / formats currently on the system clipboard. Diagnostic
tool — use clipboard_paste to actually read and return clipboard content.

Lists what formats are present. For spreadsheet data, you want to see
"text/html" (best) or "text/plain" (fallback with tab-separated values).

Args:
    selection: Which buffer to list. Defaults to "clipboard". Pass
        "primary" to list formats on the X11/Wayland PRIMARY selection.
        macOS and Windows have no PRIMARY analog and will return an
        error if "primary" is passed.

Returns:
    A list of available clipboard formats.
