List the MIME types / formats currently on the system clipboard. Diagnostic
tool — use clipboard_paste to actually read and return clipboard content.

Lists what formats are present. For spreadsheet data, you want to see
"text/html" (best) or "text/plain" (fallback with tab-separated values).

Returns:
    A list of available clipboard formats.
