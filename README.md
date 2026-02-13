# clipboard-mcp

An MCP (Model Context Protocol) server that reads content from your system clipboard —
tables, plain text, code, JSON, URLs, and more. Preserves structure when possible
(e.g. spreadsheet row/column layout) and returns non-tabular content cleanly.

## The Problem

When you copy cells from Google Sheets or Excel and paste into Claude's chat input, the
tabular structure (rows and columns) is destroyed — it arrives as a flat string with no
delimiters. And for non-tabular content, there's no easy way to say "look at what I
copied" without manually pasting.

## The Solution

Instead of pasting, tell Claude to **"read my clipboard"**. This MCP server reads the
clipboard directly and handles any content type: spreadsheet tables (returned as
Markdown, JSON, or CSV), code snippets, JSON data, URLs, rich HTML text, and plain text.

## Tools

| Tool | Description |
|------|-------------|
| `clipboard_paste` | **Primary tool.** Read any clipboard content — tables, text, code, JSON, URLs. Tables are formatted as Markdown/JSON/CSV; other content is returned with smart formatting. |
| `clipboard_read_table` | Alias for `clipboard_paste` (backward compatibility) |
| `clipboard_read_raw` | Return raw clipboard content for a given MIME type (diagnostic) |
| `clipboard_list_formats` | List what MIME types are currently on the clipboard |

## Setup

### Prerequisites

**Python 3.11+** and [uv](https://docs.astral.sh/uv/) (recommended) or pip.

You also need a platform-specific clipboard tool:

| Platform | Tool | Install |
|----------|------|---------|
| **Fedora (Wayland)** | `wl-paste` | `sudo dnf install wl-clipboard` |
| **Ubuntu (Wayland)** | `wl-paste` | `sudo apt install wl-clipboard` |
| **Linux (X11)** | `xclip` | `sudo dnf install xclip` or `sudo apt install xclip` |
| **macOS** | Built-in | No install needed (`osascript` / `pbpaste`) |
| **Windows** | Built-in | No install needed (PowerShell) |

### Install

```bash
# Clone
git clone https://github.com/cmeans/clipboard-mcp.git
cd clipboard-mcp

# Install with uv
uv sync

# Or with pip
pip install -e .
```

### Configure Claude Desktop

Add the following to your Claude Desktop config file:

**Linux**: `~/.config/Claude/claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### Option A: Using uv (recommended)

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/home/cmeans/github.com/cmeans/clipboard-mcp",
        "clipboard-mcp"
      ]
    }
  }
}
```

#### Option B: Direct Python

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "/home/cmeans/github.com/cmeans/clipboard-mcp/.venv/bin/clipboard-mcp"
    }
  }
}
```

#### Environment variables

Environment variables can be passed via the `"env"` key in the Claude Desktop config.

| Variable | Platform | Purpose | Default |
|----------|----------|---------|---------|
| `CLIPBOARD_MCP_DEBUG` | All | Enable debug logging (`1` to enable) | Off |
| `WAYLAND_DISPLAY` | Linux (Wayland) | Compositor socket name (e.g. `wayland-0`) or absolute path | Auto-detected from `$XDG_RUNTIME_DIR` |
| `XDG_RUNTIME_DIR` | Linux (Wayland) | Directory containing the Wayland socket | Auto-detected as `/run/user/<uid>` |
| `XDG_SESSION_TYPE` | Linux | Session type hint (`wayland` or `x11`) | Not required — socket scan is used as fallback |

**Wayland auto-detection**: The server scans for `wayland-*` sockets in
`$XDG_RUNTIME_DIR` (itself falling back to `/run/user/<uid>`). Neither
`WAYLAND_DISPLAY` nor `XDG_RUNTIME_DIR` need to be set manually in most cases.
Override them if auto-detection doesn't work (e.g. multiple compositors,
non-standard socket path, or a containerized environment):

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/clipboard-mcp",
        "clipboard-mcp"
      ],
      "env": {
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_RUNTIME_DIR": "/run/user/1000"
      }
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Usage

1. **Copy anything** — spreadsheet cells, code, text, a URL, JSON, etc.
2. In Claude, say something like:
   - "Paste my clipboard"
   - "Read my clipboard"
   - "What's on my clipboard?"
   - "Read what I copied"
   - "I copied some data, take a look"
   - "Show me the table I copied"
   - "Give me that data as JSON" (uses `output_format=json`)
   - "Convert my clipboard to CSV" (uses `output_format=csv`)
3. Claude will call `clipboard_paste` and return the content.

### Content handling

| Content type | What happens |
|--------------|-------------|
| **Spreadsheet table** | Parsed from HTML/TSV, returned as Markdown, JSON, or CSV (controlled by `output_format`) |
| **JSON** | Pretty-printed in a JSON code block |
| **Code** | Returned in a fenced code block |
| **URL** | Returned cleanly as a URL |
| **Rich HTML** (no table) | HTML tags stripped, readable text returned |
| **Plain text** | Returned as-is |

### Table output formats

When the clipboard contains tabular data, `output_format` controls the format:

- **Markdown** (default) — renders as a table in the conversation
- **JSON** — array of objects keyed by the header row (single-column: flat array)
- **CSV** — comma-separated values

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run the server directly (stdio mode)
uv run clipboard-mcp

# Run with debug logging (logs backend detection, tool parameters, clipboard reads)
uv run clipboard-mcp --debug

# Test with MCP Inspector
uv run mcp dev src/clipboard_mcp/server.py
```

Debug logging can also be enabled via the `CLIPBOARD_MCP_DEBUG=1` environment
variable, which is useful when the server is launched by Claude Desktop (see
[Environment variables](#environment-variables)).

### Project Structure

```
clipboard-mcp/
├── src/clipboard_mcp/
│   ├── __init__.py          # Package version
│   ├── server.py            # MCP server, tool definitions & debug logging setup
│   ├── clipboard.py         # Platform-agnostic clipboard backend (Wayland auto-detection)
│   └── parser.py            # HTML table parser, formatters, content detection
├── tests/
│   ├── test_parser.py       # Parser & formatter tests
│   └── test_server.py       # MCP server, clipboard backend & Wayland detection tests
├── pyproject.toml           # Project metadata & dependencies
├── pytest.ini               # Pytest config (pythonpath, asyncio_mode)
├── CLAUDE.md                # Claude Code guidance
├── LICENSE                  # MIT
└── README.md
```

## How It Works

1. **Clipboard read**: The server calls the platform's clipboard tool (`wl-paste`,
   `xclip`, `pbpaste`, or PowerShell) to read the clipboard.
2. **Table detection**: Tries `text/html` first — Google Sheets and Excel put `<table>`
   markup on the clipboard. Parsed with Python's built-in `html.parser` (no external
   dependencies). Falls back to `text/plain` tab-separated values.
3. **Table found?** Format as Markdown, JSON, or CSV (per `output_format`) and return.
4. **Non-tabular content**: If no table is found, the plain text (or HTML-extracted text)
   is classified as JSON, URL, code, or plain text and returned with appropriate
   formatting (pretty-printed JSON, fenced code blocks, etc.). Content is truncated
   at 50KB.

## License

MIT — see [LICENSE](LICENSE).
