"""Clipboard MCP Server.

MCP server that reads and writes the system clipboard — tables, text, code,
JSON, URLs, images, and more. Preserves structure when possible (e.g.
spreadsheet row/column layout) and returns non-tabular content cleanly.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from .clipboard import (
    ClipboardError,
    base_mime_type,
    list_clipboard_formats,
    read_clipboard,
    read_clipboard_image,
    write_clipboard,
)
from .parser import (
    detect_content_type,
    extract_html_text,
    format_table,
    infer_column_types,
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


_INSTRUCTIONS_DIR = Path(__file__).parent / "instructions"


def _load_instruction(name: str) -> str:
    """Load an instruction file from the instructions/ directory."""
    path = _INSTRUCTIONS_DIR / f"{name}.md"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"Missing instruction file: {path}. "
            "The clipboard-mcp package may be installed incorrectly."
        ) from None


mcp = FastMCP(
    "clipboard_mcp",
    instructions=_load_instruction("server"),
)


_VALID_FORMATS = {"markdown", "json", "csv", "slack", "jira", "confluence", "html", "notion"}
_MAX_CONTENT_LEN = 50_000
_BINARY_MIME_PREFIXES = ("image/", "audio/", "video/")
_BINARY_MIME_EXACT = frozenset({"application/octet-stream"})

# image/* entries that are text-readable (not actual binary).
_TEXT_READABLE_MIMES = frozenset({"image/svg+xml"})

# Basic MIME type validation: type/subtype with optional parameters.
_MIME_RE = re.compile(r"^[\w.+\-]+/[\w.+\-]+(;[\w.+\-=]+)*$")


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
    description=_load_instruction("clipboard_paste"),
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
    include_schema: bool = False,
):
    # NOTE: No return type annotation here by design.  The true type is
    # `str | Image`, but annotating it that way causes FastMCP to call
    # Pydantic's `create_model()` on the union, which fails because
    # `mcp.server.fastmcp.utilities.types.Image` has no Pydantic schema.
    # When/if FastMCP adds native Image support in its output schema path,
    # add `-> str | Image` and remove this comment.
    output_format = output_format.strip().lower()
    if output_format not in _VALID_FORMATS:
        return (
            f"Unknown output_format: {output_format!r}. "
            f"Valid options: markdown, json, csv, slack, jira, confluence, html, notion"
        )

    logger.debug(
        "clipboard_paste called: output_format=%r include_schema=%r",
        output_format,
        include_schema,
    )

    rows, html, text = await _read_clipboard_content()

    # If we found tabular data, format it
    if rows:
        row_count = len(rows)
        col_count = max(len(r) for r in rows) if rows else 0
        formatted = format_table(rows, output_format)
        result = f"Found table: {row_count} rows × {col_count} columns\n\n{formatted}"

        if include_schema:
            types = infer_column_types(rows)
            if types:
                headers = list(rows[0]) if rows else []
                # Pad headers if table is wider than the header row
                while len(headers) < len(types):
                    headers.append(f"Col {len(headers) + 1}")
                schema_rows = [["Column", "Type"]] + [
                    [h, t] for h, t in zip(headers, types)
                ]
                schema_table = format_table(schema_rows, "markdown")
                result += f"\n\n**Column types:**\n\n{schema_table}"

        return result

    # Non-tabular: prefer extracted HTML text if HTML was available
    content = ""
    if html:
        content = extract_html_text(html)
    if not content:
        content = text

    # Strategy 3: RTF fallback — try text/rtf when HTML and plain text are empty
    if not content.strip():
        try:
            rtf = await read_clipboard("text/rtf")
            if rtf.strip():
                truncated = len(rtf) > _MAX_CONTENT_LEN
                display = rtf[:_MAX_CONTENT_LEN]
                result = f"Clipboard contains rich text (RTF):\n\n```\n{display}\n```"
                if truncated:
                    result += "\n\n... [truncated at 50KB]"
                return result
        except ClipboardError as e:
            logger.debug("RTF clipboard read failed: %s", e)

    # If no text content at all, check whether the clipboard holds binary data
    if not content.strip():
        try:
            formats = await list_clipboard_formats()
            image_formats = [f for f in formats if f.startswith("image/")]
            if image_formats:
                # Prefer PNG (match by base type to handle parameter suffixes)
                mime = next(
                    (f for f in image_formats if base_mime_type(f) == "image/png"),
                    image_formats[0],
                )
                try:
                    data = await read_clipboard_image(mime)
                    if data:
                        fmt = base_mime_type(mime).split("/", 1)[1]
                        return Image(data=data, format=fmt)
                except ClipboardError as e:
                    logger.debug("Image read failed: %s", e)
            # Non-image binary (audio/video) — report but can't return
            binary = [
                f for f in formats
                if (f.startswith(_BINARY_MIME_PREFIXES) or f in _BINARY_MIME_EXACT)
                and not f.startswith("image/")
            ]
            if binary:
                fmt_list = ", ".join(binary)
                return (
                    f"Clipboard contains binary data ({fmt_list}) which cannot be "
                    f"returned as text. Audio and video are not supported."
                )
        except ClipboardError:
            pass

    return _format_non_tabular(content)


@mcp.tool(
    name="clipboard_read_raw",
    description=_load_instruction("clipboard_read_raw"),
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
    base_type = base_mime_type(mime_type)
    if not _MIME_RE.match(base_type):
        return (
            f"Invalid MIME type: {mime_type!r}. "
            f"Expected format: type/subtype (e.g. text/plain, image/png)."
        )
    if (
        base_type.startswith(_BINARY_MIME_PREFIXES) or base_type in _BINARY_MIME_EXACT
    ) and base_type not in _TEXT_READABLE_MIMES:
        return (
            f"Cannot read binary MIME type '{mime_type}'. "
            f"This tool only supports text-based formats (e.g. text/plain, text/html, "
            f"image/svg+xml, application/json)."
        )

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
    description=_load_instruction("clipboard_list_formats"),
    annotations={
        "title": "List Clipboard Formats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_list_formats() -> str:
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


@mcp.tool(
    name="clipboard_copy",
    description=_load_instruction("clipboard_copy"),
    annotations={
        "title": "Copy to Clipboard",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def clipboard_copy(
    content: str,
) -> str:
    try:
        await write_clipboard(content)
    except ClipboardError as e:
        return f"Error writing to clipboard: {e}"

    return f"Copied {len(content)} characters to clipboard."


def main() -> None:
    """Entry point for the clipboard-mcp command."""
    _configure_logging()
    # Strip --debug before FastMCP sees argv
    sys.argv = [a for a in sys.argv if a != "--debug"]
    mcp.run()


if __name__ == "__main__":
    main()
