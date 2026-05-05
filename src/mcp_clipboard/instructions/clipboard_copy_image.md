Write an image to the user's system clipboard. Replaces whatever is
currently on the clipboard with the provided image so it can be pasted
into other applications (Slack, Gmail, Figma, image editors, etc.).

WHEN TO CALL THIS TOOL:

Call this tool when the user says "copy this image", "put this on my
clipboard", or any phrase that implies writing an image to the clipboard.

Also call it when you have produced or fetched an image (a chart, a
screenshot, a generated image) and the user wants to paste it elsewhere.
For text content, use `clipboard_copy` instead.

Args:
    image_data: Base64-encoded image bytes. The same encoding that
        `clipboard_paste` returns for image content can be passed back in.
    mime_type: Either "image/png" or "image/jpeg". Pass-through, no
        re-encoding. The image header is verified against the declared
        MIME type to catch mismatches.

Returns:
    A confirmation message with the byte count and the MIME type written.

Limits:
    The image must not exceed `MCP_CLIPBOARD_MAX_IMAGE_BYTES` (default
    10 MB). Set the env var to raise the limit.
