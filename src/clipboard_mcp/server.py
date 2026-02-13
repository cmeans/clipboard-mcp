"""Clipboard MCP Server.

Exposes tools to read content from the system clipboard — tables, text, code,
JSON, URLs, and more. Preserves structure when possible (e.g. spreadsheet
row/column layout) and returns non-tabular content cleanly.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .clipboard import ClipboardError, list_clipboard_formats, read_clipboard
from .parser import (
    detect_content_type,
    extract_html_text,
    format_table,
    parse_html_table,
    parse_tsv,
)

logger = logging.getLogger(__name__)


def _is_debug() -> bool:
    """Check if debug mode is enabled via --debug flag or CLIPBOARD_MCP_DEBUG env var."""
    return "--debug" in sys.argv or os.environ.get("CLIPBOARD_MCP_DEBUG", "") == "1"


def _configure_logging() -> None:
    """Configure root logging for the clipboard_mcp package."""
    level = logging.DEBUG if _is_debug() else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("clipboard_mcp").setLevel(level)


_configure_logging()

mcp = FastMCP(
    "clipboard_mcp",
    instructions=(
        "This server reads content from the user's system clipboard. "
        "When the user says 'paste', 'read my clipboard', 'what did I copy', "
        "'show clipboard data', 'I copied some data', or otherwise references "
        "clipboard content, call clipboard_paste. It handles any content type: "
        "tables, plain text, code, JSON, URLs, etc. "
        "If the clipboard contains a table and the user asks for a specific "
        "format (JSON, CSV, markdown), pass the output_format parameter."
    ),
)


_VALID_FORMATS = {"markdown", "json", "csv"}
_MAX_CONTENT_LEN = 50_000


async def _read_clipboard_content() -> tuple[list[list[str]], str, str]:
    """Read clipboard and attempt to extract tabular data.

    Returns (rows, html, text) where rows may be empty if no table found.
    html and text are the raw clipboard content (may be empty on error).
    """
    rows: list[list[str]] = []
    html = ""
    text = ""

    # Strategy 1: Try HTML clipboard (most reliable for spreadsheets)
    try:
        html = await read_clipboard("text/html")
        if html:
            rows = parse_html_table(html)
    except ClipboardError as e:
        logger.debug("HTML clipboard read failed: %s", e)

    # Strategy 2: Fall back to TSV in plain text
    if not rows:
        try:
            text = await read_clipboard("text/plain")
            if text:
                rows = parse_tsv(text)
        except ClipboardError as e:
            logger.debug("Plain text clipboard read failed: %s", e)

    return rows, html, text


def _format_non_tabular(text: str) -> str:
    """Format non-tabular text content with smart detection."""
    if not text.strip():
        return "Clipboard is empty."

    # Truncate large content
    truncated = False
    if len(text) > _MAX_CONTENT_LEN:
        text = text[:_MAX_CONTENT_LEN]
        truncated = True

    content_type = detect_content_type(text)
    logger.debug("Non-tabular content detected as: %s", content_type)

    if content_type == "json":
        # Pretty-print JSON
        try:
            parsed = json.loads(text.strip())
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            result = f"Clipboard contains JSON:\n\n```json\n{formatted}\n```"
        except (json.JSONDecodeError, ValueError):
            result = f"Clipboard content:\n\n{text}"
    elif content_type == "url":
        result = f"Clipboard contains URL:\n\n{text.strip()}"
    elif content_type == "code":
        result = f"Clipboard contains code:\n\n```\n{text.rstrip()}\n```"
    else:
        result = f"Clipboard content:\n\n{text}"

    if truncated:
        result += "\n\n... [truncated at 50KB]"

    return result


@mcp.tool(
    name="clipboard_paste",
    annotations={
        "title": "Paste Clipboard",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_paste(
    output_format: str = "markdown",
) -> str:
    """Read content from the system clipboard and return it.

    Call this tool when the user says "paste", "read my clipboard",
    "what's on my clipboard", "read what I copied", "I copied some data",
    "show me what I copied", or any reference to clipboard contents or pasted data.

    Handles any clipboard content: spreadsheet tables, plain text, code snippets,
    JSON, URLs, rich text, and more. If the clipboard contains a table (from
    Google Sheets, Excel, etc.), it will be parsed and returned in the requested
    output_format. For non-tabular content, it is returned with smart formatting.

    Args:
        output_format: Format for table data (case-insensitive). Only applies when
            the clipboard contains a table. Ignored for non-tabular content. Options:
            - "markdown" (default): GitHub-flavored Markdown table
            - "json": Array of objects keyed by header row
            - "csv": Comma-separated values

    Returns:
        The clipboard content, formatted appropriately for the content type.
    """
    output_format = output_format.strip().lower()
    if output_format not in _VALID_FORMATS:
        return (
            f"Unknown output_format: {output_format!r}. "
            f"Valid options: markdown, json, csv"
        )

    logger.debug("clipboard_paste called: output_format=%r", output_format)

    rows, html, text = await _read_clipboard_content()

    # If we found tabular data, format it
    if rows:
        row_count = len(rows)
        col_count = max(len(r) for r in rows) if rows else 0
        formatted = format_table(rows, output_format)
        return f"Found table: {row_count} rows × {col_count} columns\n\n{formatted}"

    # Non-tabular: prefer extracted HTML text if HTML was available
    content = ""
    if html:
        content = extract_html_text(html)
    if not content:
        content = text

    return _format_non_tabular(content)


@mcp.tool(
    name="clipboard_read_table",
    annotations={
        "title": "Read Clipboard Table",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_read_table(
    output_format: str = "markdown",
) -> str:
    """Read tabular data from the clipboard. Alias for clipboard_paste.

    Use clipboard_paste for general clipboard access. This tool is kept for
    backward compatibility and behaves identically.
    """
    return await clipboard_paste(output_format=output_format)


@mcp.tool(
    name="clipboard_read_raw",
    annotations={
        "title": "Read Raw Clipboard",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_read_raw(
    mime_type: str = "text/plain",
) -> str:
    """Read raw clipboard content in a specific MIME format. Diagnostic tool only.

    Use clipboard_paste instead for normal clipboard access. This tool returns
    the clipboard content as-is without any parsing or restructuring.
    Use clipboard_list_formats first to see what MIME types are available.

    Args:
        mime_type: The MIME type to read from the clipboard.
            Common values: "text/plain", "text/html"

    Returns:
        The raw clipboard content in the requested format, or an error message.
    """
    try:
        content = await read_clipboard(mime_type)
    except ClipboardError as e:
        return f"Error reading clipboard: {e}"

    if not content:
        return f"No content available for MIME type: {mime_type}"

    # Truncate very large content to avoid overwhelming the context
    if len(content) > _MAX_CONTENT_LEN:
        return (
            f"Content ({len(content)} chars, truncated to {_MAX_CONTENT_LEN}):\n\n"
            f"{content[:_MAX_CONTENT_LEN]}\n\n... [truncated]"
        )

    return f"Content ({len(content)} chars):\n\n{content}"


@mcp.tool(
    name="clipboard_list_formats",
    annotations={
        "title": "List Clipboard Formats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_list_formats() -> str:
    """List the MIME types / formats currently available on the system clipboard.

    Use clipboard_paste to actually read clipboard data. This diagnostic tool
    just lists what formats are present. For spreadsheet data, you want to see
    "text/html" (best) or "text/plain" (fallback with tab-separated values).

    Returns:
        A list of available clipboard formats.
    """
    try:
        formats = await list_clipboard_formats()
    except ClipboardError as e:
        return f"Error listing clipboard formats: {e}"

    if not formats:
        return "The clipboard appears to be empty (no formats available)."

    # Highlight useful formats
    highlights: list[str] = []
    if any("html" in f.lower() for f in formats):
        highlights.append("✓ HTML available — table structure should be preserved")
    if any("text/plain" in f.lower() or f == "UTF8_STRING" for f in formats):
        highlights.append("✓ Plain text available")

    result = f"Clipboard has {len(formats)} format(s):\n\n"
    result += "\n".join(f"  • {f}" for f in formats)
    if highlights:
        result += "\n\n" + "\n".join(highlights)

    return result


def main() -> None:
    """Entry point for the clipboard-mcp command."""
    # Strip --debug before FastMCP sees argv
    sys.argv = [a for a in sys.argv if a != "--debug"]
    mcp.run()


if __name__ == "__main__":
    main()
