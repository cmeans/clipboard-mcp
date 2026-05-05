<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-dark.svg" width="128">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-light.svg" width="128">
    <img src="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-light.svg" alt="mcp-clipboard logo" width="128">
  </picture>
</p>

# mcp-clipboard

[![PyPI version](https://img.shields.io/pypi/v/mcp-clipboard)](https://pypi.org/project/mcp-clipboard/)
[![Python versions](https://img.shields.io/pypi/pyversions/mcp-clipboard)](https://pypi.org/project/mcp-clipboard/)
[![License](https://img.shields.io/pypi/l/mcp-clipboard)](https://github.com/cmeans/mcp-clipboard/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/cmeans/mcp-clipboard/ci.yml?label=CI)](https://github.com/cmeans/mcp-clipboard/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/cmeans/mcp-clipboard/graph/badge.svg)](https://codecov.io/gh/cmeans/mcp-clipboard)
[![Downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Fdownloads-30d-non-ci.json)](https://github.com/cmeans/pypi-winnow-downloads)

[![pip downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-pip-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![pipenv downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-pipenv-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![pipx downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-pipx-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![uv downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-uv-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![poetry downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-poetry-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![pdm downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Finstaller-pdm-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)

[![linux downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Fos-linux-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![macos downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Fos-macos-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)
[![windows downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fpypi-badges.intfar.com%2Fmcp-clipboard%2Fos-windows-30d-non-ci.json)](https://pypi.org/project/mcp-clipboard/)

An MCP server that gives your AI assistant direct access to your system clipboard: read what you copied, or write clean text straight to it. Works with any MCP-compatible client, including Claude Code, Claude Desktop, Cursor, Windsurf, and others.

## Why This Exists

### Pasting loses structure

When you copy cells from Google Sheets or Excel and paste into a chat input, the tabular structure (rows and columns) is destroyed. It arrives as a flat string with no delimiters. The model has to guess where one cell ends and the next begins, and it often guesses wrong.

**mcp-clipboard preserves it.** Instead of pasting, tell your assistant to "read my clipboard." The server reads the clipboard directly, detects tabular data from the HTML that spreadsheet apps put on the clipboard, and returns it as a properly formatted Markdown table, JSON, or CSV. No structure lost, no guessing.

### Bonus: it also fixes copying from Claude Code

Claude Code's terminal renderer adds 2-character padding, hard line breaks at ~80 columns, and trailing whitespace to all output. When you select and copy text from the terminal, those artifacts come along for the ride:

```
  echo "this is a long command that wraps and
  breaks when you paste it because of the hard
  newlines and leading spaces"
```

This has been reported repeatedly on the claude-code repo (issues #4686, #6827, #7670, #13378, #15199, #25040, #25427, #26016) with dozens of upvotes and no fix shipped.

**mcp-clipboard sidesteps the problem entirely.** Instead of copying text from the terminal, ask Claude Code to put it on your clipboard:

> "Copy that command to my clipboard"

Claude Code calls `clipboard_copy`, writes the clean text directly to your system clipboard, and you paste it wherever you need it. No padding, no hard wraps, no cleanup.

**Tip:** To make this automatic, add a line to your project or global `CLAUDE.md`:

```
When you produce a shell command for the user to run, also copy it to the clipboard using clipboard_copy.
```

Claude Code will then copy every command it suggests without you having to ask.

## Tools

| Tool | Description |
| --- | --- |
| `clipboard_paste` | **Primary tool.** Read any clipboard content: tables, text, code, JSON, URLs, images. Tables are formatted as Markdown/JSON/CSV; pass `include_schema=true` to append inferred column types. Images are returned as image content the model can see. |
| `clipboard_copy` | Write text content to the system clipboard. Accepts an optional `mime_type` parameter (`text/plain` by default; also `text/html`, `text/rtf`, or any `text/*` on Wayland/X11). |
| `clipboard_copy_image` | Write a PNG or JPEG image to the system clipboard from base64-encoded bytes. Pass-through with no re-encoding; magic bytes are validated against the declared MIME. Use `clipboard_copy` for text. |
| `clipboard_list_formats` | List what MIME types are currently on the clipboard. |
| `clipboard_read_raw` | Return raw clipboard content for a given MIME type (diagnostic). Any non-binary type passes through; only `image/*`, `audio/*`, `video/*`, and `application/octet-stream` are rejected. Use `clipboard_paste` for images. |

## Setup

### Prerequisites

**Python 3.11+** and one of: [uv](https://docs.astral.sh/uv/) (recommended), [pipx](https://pipx.pypa.io/), or pip.

You also need a platform-specific clipboard tool:

| Platform | Tool | Install |
| --- | --- | --- |
| **Fedora / RHEL (Wayland)** | `wl-copy` / `wl-paste` | `sudo dnf install wl-clipboard` |
| **Ubuntu / Debian (Wayland)** | `wl-copy` / `wl-paste` | `sudo apt install wl-clipboard` |
| **Linux (X11)** | `xclip` | `sudo dnf install xclip` or `sudo apt install xclip` |
| **macOS** | Built-in | No install needed (`pbcopy` / `pbpaste`) |
| **Windows** | Built-in | No install needed (PowerShell) |

> **Platform status:** Linux with Wayland is tested and actively used. X11, macOS, and Windows implementations are complete but untested on real hardware. Bug reports and PRs are welcome.

### Claude Code

```bash
claude mcp add clipboard --scope user -- uvx mcp-clipboard
```

### Claude Desktop

Add to your Claude Desktop config:

- **Linux:** `~/.config/Claude/claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uvx",
      "args": ["mcp-clipboard"]
    }
  }
}
```

### Other MCP clients

Any client that supports MCP stdio servers can use mcp-clipboard. The simplest approach is `uvx mcp-clipboard`. Consult your client's documentation for how to register MCP servers.

### Installing from source

If you prefer a local clone instead of installing from PyPI:

```bash
git clone https://github.com/cmeans/mcp-clipboard.git
cd mcp-clipboard
uv sync
```

Then point your client at the local install:

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/mcp-clipboard",
        "mcp-clipboard"
      ]
    }
  }
}
```

### Environment variables

Environment variables can be passed via the `"env"` key in the config.

| Variable | Platform | Purpose | Default |
| --- | --- | --- | --- |
| `MCP_CLIPBOARD_DEBUG` | All | Enable debug logging (`1` to enable) | Off |
| `WAYLAND_DISPLAY` | Linux (Wayland) | Compositor socket name or absolute path | Auto-detected |
| `XDG_RUNTIME_DIR` | Linux (Wayland) | Directory containing the Wayland socket | `/run/user/<uid>` |
| `XDG_SESSION_TYPE` | Linux | Session type hint (`wayland` or `x11`) | Auto-detected via socket scan |

Most Linux users won't need to set any of these. Override if auto-detection fails (multiple compositors, non-standard socket path, or containerized environments).

## Usage

### Reading your clipboard

Copy anything (spreadsheet cells, code, text, a URL, JSON, an image), then:

* "Paste my clipboard"
* "Read my clipboard"
* "What's on my clipboard?"
* "I copied some data, take a look"

Your assistant calls `clipboard_paste` and returns the content with structure preserved.

### Writing to your clipboard

When your agent generates a command, code block, or any text you need to use elsewhere:

* "Copy that to my clipboard"
* "Put that command on my clipboard"
* "Copy that as HTML" (writes `text/html` so rich-text apps paste with formatting)

The agent calls `clipboard_copy` and the clean text goes straight to your system clipboard. No terminal rendering artifacts, just clean text. This is especially useful with Claude Code (see [above](#bonus-it-also-fixes-copying-from-claude-code)).

> **Tip: auto-copy behavior.** By default the agent only copies to the clipboard when you ask. If you want commands and code blocks copied automatically, add this to your system prompt (e.g. in a Claude Desktop project or Claude Code's CLAUDE.md):
>
> *When you output a command or code block that the user is likely to paste elsewhere, proactively copy it to the clipboard using clipboard_copy.*

### Table output formats

When the clipboard contains tabular data, `output_format` controls the format:

| Format | Destination | What you get |
|--------|-------------|--------------|
| `markdown` | Claude, GitHub, most tools | GFM pipe table (default) |
| `notion` | Notion | GFM pipe table (Notion renders these natively) |
| `slack` | Slack | `*bold*` header + space-aligned data in a monospace code block |
| `jira` | Jira | `\|\|Header\|\|` / `\|Cell\|` wiki markup |
| `confluence` | Confluence | same as `jira` (shared wiki syntax) |
| `html` | Email, web, rich-text editors | `<table>` with `<thead>`/`<th>`/`<tbody>`/`<td>` |
| `json` | APIs, code | Array of objects keyed by header row |
| `csv` | Excel, data tools | Comma-separated values |

**Examples:**
- "Read my clipboard as Slack" → `output_format=slack`
- "Convert my clipboard to Jira table" → `output_format=jira`
- "Give me that as HTML" → `output_format=html`

### Table schema inference

Add `include_schema=true` to get a column-type summary alongside the table:

> "Read my clipboard with schema"

Inferred types: **integer**, **float**, **currency**, **percentage**, **date**, **boolean**, **text**. Uses majority-wins per column — if no type accounts for more than half the non-empty cells, the column is typed as `text`. Empty cells are skipped; the header row is excluded from inference.

This is useful when handing tabular data to Claude for SQL `CREATE TABLE` statements, Pandas `dtype` mappings, or validation rules — Claude gets the types upfront instead of guessing from the data.

### Tips for reliable triggering

The server includes MCP instructions that tell the client when to use the clipboard tools, but results vary by model and client. If the agent doesn't pick up on your intent, be explicit: "copy that to my clipboard" or "read what I copied" work most reliably.

If you have access to a custom system prompt (e.g. in a Claude Desktop project or a custom agent), you can reinforce the behavior:

> When the user asks to copy output, use clipboard_copy to write it to the system clipboard. When the user references data not in the conversation, check the clipboard using clipboard_paste.

## Content handling

| Content type | What happens |
| --- | --- |
| Spreadsheet table | Parsed from HTML/TSV, returned in your choice of format (Markdown, JSON, CSV, Slack, Jira, HTML, Notion) |
| JSON | Pretty-printed in a JSON code block |
| Code | Returned in a fenced code block |
| URL | Returned cleanly as a URL |
| Rich HTML (no table) | HTML tags stripped, readable text returned |
| RTF | Returned in a fenced code block (macOS, Windows, and Wayland/X11 via pass-through) |
| Plain text | Returned as-is |
| Images (PNG, etc.) | Returned as an MCP image content block the model can see and analyze |
| SVG | Readable as text via `clipboard_read_raw` with `image/svg+xml`, or returned as image via `clipboard_paste` |
| Audio / video | Not supported; returns a message identifying the format |

## How It Works

1. **Platform detection:** At startup, the server detects your clipboard backend (Wayland, X11, macOS, or Windows) and selects the appropriate system commands.
2. **Reading (`clipboard_paste`):** Calls the platform's clipboard read command. Tries `text/html` first (Google Sheets and Excel put `<table>` markup on the clipboard), parses with Python's built-in `html.parser`. Falls back to `text/plain` tab-separated values, then `text/rtf`, then checks for images.
3. **Writing text (`clipboard_copy`):** Pipes text to the platform's clipboard write command (`wl-copy`, `xclip -selection clipboard`, `pbcopy`, or PowerShell `Set-Clipboard`). Supports a `mime_type` parameter for writing typed content (e.g. `text/html`, `text/rtf`).
4. **Writing images (`clipboard_copy_image`):** Decodes base64 PNG or JPEG bytes and writes them to the platform's clipboard via `wl-copy --type`, `xclip -target`, NSPasteboard `setData:forType:` (macOS), or `Clipboard::SetImage` (Windows). Magic bytes are validated against the declared MIME type before any subprocess runs.
5. **Image passthrough on read:** If the clipboard contains an image (PNG, etc.), it's returned as a base64-encoded MCP image content block that the model can see and analyze.
6. **Content classification:** Non-tabular text content is classified as JSON, URL, code, or plain text and returned with appropriate formatting (pretty-printed JSON, fenced code blocks, etc.).

## Limitations

* **Audio and video are not supported.** If the clipboard contains audio or video, the server reports the format but cannot return the content.
* **Image write supports PNG and JPEG only.** `clipboard_copy_image` is pass-through, no re-encoding. Other formats (GIF, WebP, TIFF, BMP, SVG) are not yet writable; SVG is text and round-trips today via `clipboard_paste` / `clipboard_read_raw`.
* **Writing multiple MIME types atomically is not supported** on Wayland/X11. For example, writing both `text/html` and `text/plain` in a single clipboard operation requires owning the clipboard selection across calls.
* **Text content is truncated at 50KB** to avoid overwhelming the model's context window.
* **X11, macOS, and Windows are untested** on real hardware. Implementations are complete and should work, but edge cases are possible. Bug reports and PRs are welcome.

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run the server directly (stdio mode)
uv run mcp-clipboard

# Run with debug logging
uv run mcp-clipboard --debug

# Test with MCP Inspector
uv run mcp dev src/mcp_clipboard/server.py
```

Debug logging can also be enabled via `MCP_CLIPBOARD_DEBUG=1`, which is useful when the server is launched by Claude Desktop or Claude Code.

## Project structure

```
mcp-clipboard/
├── src/mcp_clipboard/
│   ├── __init__.py          # Package version
│   ├── server.py            # MCP server, tool definitions, debug logging
│   ├── clipboard.py         # Platform-agnostic clipboard backend
│   ├── parser.py            # HTML table parser, formatters, content detection
│   ├── instructions/        # Tool and server descriptions (loaded at startup)
│   │   ├── server.md
│   │   ├── clipboard_copy.md
│   │   ├── clipboard_copy_image.md
│   │   ├── clipboard_paste.md
│   │   ├── clipboard_read_raw.md
│   │   └── clipboard_list_formats.md
│   └── icons/               # SVG icons for MCP client display (light/dark)
│       ├── mcp-clipboard-logo-light.svg
│       └── mcp-clipboard-logo-dark.svg
├── tests/
│   ├── test_parser.py       # Parser and formatter tests
│   └── test_server.py       # Server, backend, and Wayland detection tests
├── .github/
│   ├── workflows/
│   │   ├── publish.yml      # PyPI publish on v* tags (OIDC trusted publisher)
│   │   └── test-publish.yml # TestPyPI publish on test-v* tags
│   └── ISSUE_TEMPLATE/      # Bug report, feature request, platform test forms
├── pyproject.toml
├── CHANGELOG.md
├── CLAUDE.md                # Claude Code project guidance
├── LICENSE                  # Apache 2.0
└── README.md
```

## Acknowledgments

This project was designed and built in collaboration with
[Claude Code](https://claude.ai/code) (Anthropic's CLI for Claude). Architecture, design
decisions, and release management were driven by the human; implementation, testing, code
review, and documentation were delegated conversationally, with Claude writing code,
catching stale docs, and filling test coverage gaps across every commit.

## License

Apache 2.0. See [LICENSE](LICENSE).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-dark.svg" width="24">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-light.svg" width="24">
  <img src="https://raw.githubusercontent.com/cmeans/mcp-clipboard/main/src/mcp_clipboard/icons/mcp-clipboard-logo-light.svg" alt="" width="24" align="top">
</picture> © 2026 Chris Means
