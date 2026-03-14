# clipboard-mcp

An MCP (Model Context Protocol) server that reads and writes your system clipboard —
tables, plain text, code, JSON, URLs, images, and more. Preserves structure when
possible (e.g. spreadsheet row/column layout) and returns non-tabular content cleanly.

## The Problem

When you copy cells from Google Sheets or Excel and paste into Claude's chat input, the
tabular structure (rows and columns) is destroyed — it arrives as a flat string with no
delimiters. And for non-tabular content, there's no easy way to say "look at what I
copied" without manually pasting.

## The Solution

Instead of pasting, tell Claude to **"read my clipboard"**. This MCP server reads the
clipboard directly and handles any content type: spreadsheet tables (returned as
Markdown, JSON, or CSV), images (returned as image content), code snippets, JSON data,
URLs, rich HTML text, and plain text. It can also **write** to the clipboard, so Claude
can copy results back for you to paste elsewhere.

## Tools

| Tool | Description |
|------|-------------|
| `clipboard_paste` | **Primary tool.** Read any clipboard content — tables, text, code, JSON, URLs, images. Tables are formatted as Markdown/JSON/CSV; images are returned as image content; other content is returned with smart formatting. |
| `clipboard_copy` | Write text to the system clipboard |
| `clipboard_read_raw` | Return raw clipboard content for a given MIME type (diagnostic) |
| `clipboard_list_formats` | List what MIME types are currently on the clipboard |

## Setup

### Prerequisites

**Python 3.11+** and one of: [uv](https://docs.astral.sh/uv/) (recommended), [pipx](https://pipx.pypa.io/), or pip.

You also need a platform-specific clipboard tool:

| Platform | Tool | Install |
|----------|------|---------|
| **Fedora (Wayland)** | `wl-paste` | `sudo dnf install wl-clipboard` |
| **Ubuntu (Wayland)** | `wl-paste` | `sudo apt install wl-clipboard` |
| **Linux (X11)** | `xclip` | `sudo dnf install xclip` or `sudo apt install xclip` |
| **macOS** | Built-in | No install needed (`osascript` / `pbpaste`) |
| **Windows** | Built-in | No install needed (PowerShell) |

> **Platform status**: Linux with Wayland and X11 is tested.
> macOS and Windows implementations are complete but
> **untested on real hardware** — they should work but may have edge cases.
> Bug reports and PRs are very welcome.

### Configure Claude Desktop

Add one of the following to your Claude Desktop config file:

- **Linux**: `~/.config/Claude/claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### Option A: uvx — no clone needed (recommended)

Requires [uv](https://docs.astral.sh/uv/). Installs and runs directly from PyPI:

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uvx",
      "args": [
        "--from", "clipboard-mcp-server",
        "clipboard-mcp"
      ]
    }
  }
}
```

#### Option B: pipx — no clone needed

Requires [pipx](https://pipx.pypa.io/). Same idea, different tool manager:

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "pipx",
      "args": [
        "run", "--spec", "clipboard-mcp-server",
        "clipboard-mcp"
      ]
    }
  }
}
```

> **Note**: The PyPI package name is `clipboard-mcp-server` but the command it
> installs is `clipboard-mcp`.

#### Option C: Local clone with uv

```bash
git clone https://github.com/cmeans/clipboard-mcp.git
cd clipboard-mcp
uv sync
```

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/clipboard-mcp",
        "clipboard-mcp"
      ]
    }
  }
}
```

#### Option D: Local clone with pip

```bash
git clone https://github.com/cmeans/clipboard-mcp.git
cd clipboard-mcp
pip install -e .
```

```json
{
  "mcpServers": {
    "clipboard": {
      "command": "clipboard-mcp"
    }
  }
}
```

> **Note**: Option D depends on `clipboard-mcp` being on your PATH. Since Claude
> Desktop launches outside a shell, this may not work reliably. Prefer options A–C.

Restart Claude Desktop after editing the config.

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
      "command": "uvx",
      "args": [
        "--from", "clipboard-mcp-server",
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

## Usage

1. **Copy anything** — spreadsheet cells, code, text, a URL, JSON, an image, etc.
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

**Writing to the clipboard** — Claude can also copy results back:
- "Copy that to my clipboard"
- "Put the cleaned-up JSON on my clipboard"
- "Copy just the SQL query"

### Tips for reliable triggering

The server includes instructions that tell Claude when to check the clipboard, but
host models vary in how consistently they follow MCP server instructions. If Claude
isn't picking up on your intent, try these approaches:

**Be explicit** — these phrases work most reliably:
- "Paste my clipboard"
- "Read what I copied"
- "What's on my clipboard?"

**Reference the clipboard when data is missing** — Claude is instructed to check the
clipboard when you refer to data that isn't in the conversation, but this doesn't
always fire. If Claude asks you to provide the data instead of reading it, nudge it:
- "It's on my clipboard — paste it"
- "Check my clipboard"

**Add a system prompt hint** — If you have access to a custom system prompt (e.g. in
a Claude Desktop project), you can reinforce the behavior:

> When the user references data not present in the conversation, check the clipboard
> using clipboard_paste before asking them to provide it.

### Content handling

| Content type | What happens |
|--------------|-------------|
| **Spreadsheet table** | Parsed from HTML/TSV, returned as Markdown, JSON, or CSV (controlled by `output_format`) |
| **JSON** | Pretty-printed in a JSON code block |
| **Code** | Returned in a fenced code block |
| **URL** | Returned cleanly as a URL |
| **Rich HTML** (no table) | HTML tags stripped, readable text returned |
| **Plain text** | Returned as-is |
| **Images** (PNG, etc.) | Returned as image content — Claude can see and analyze the image |
| **Audio / video** | Detected and reported, but content is not returned |

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
│   ├── parser.py            # HTML table parser, formatters, content detection
│   └── instructions/        # Tool & server descriptions (loaded at startup)
│       ├── server.md        # Server-level MCP instructions
│       ├── clipboard_paste.md
│       ├── clipboard_copy.md
│       ├── clipboard_read_raw.md
│       └── clipboard_list_formats.md
├── tests/
│   ├── test_parser.py       # Parser & formatter tests
│   └── test_server.py       # MCP server, clipboard backend & Wayland detection tests
├── pyproject.toml           # Project metadata, dependencies & pytest config
├── CLAUDE.md                # Claude Code guidance
├── LICENSE                  # MIT
└── README.md
```

## How It Works

### Reading (`clipboard_paste`)

1. **Clipboard read**: The server calls the platform's clipboard tool (`wl-paste`,
   `xclip`, `pbpaste`, or PowerShell) to read the clipboard.
2. **Table detection**: Tries `text/html` first — Google Sheets and Excel put `<table>`
   markup on the clipboard. Parsed with Python's built-in `html.parser` (no external
   dependencies). Falls back to `text/plain` tab-separated values.
3. **Table found?** Format as Markdown, JSON, or CSV (per `output_format`) and return.
4. **Non-tabular text**: If no table is found, the plain text (or HTML-extracted text)
   is classified as JSON, URL, code, or plain text and returned with appropriate
   formatting (pretty-printed JSON, fenced code blocks, etc.). Content is truncated
   at 50KB.
5. **No text content?** Check for image formats on the clipboard. If found, read the
   image data and return it as base64-encoded image content that Claude can see.
6. **Audio/video**: Detected and reported, but content is not returned.

### Writing (`clipboard_copy`)

The server writes text to the clipboard using the platform's clipboard tool
(`wl-copy`, `xclip`, `pbcopy`, or PowerShell). Currently supports text content only.

## Limitations

- **Audio and video are not supported.** If the clipboard contains audio or video,
  the server will report what format is present but cannot return the content.
- **Clipboard write is text-only.** `clipboard_copy` writes plain text. Writing images
  or other binary data is not yet supported.
- **Text content is truncated at 50KB** to avoid overwhelming the model's context
  window.
- **macOS and Windows are untested** (see [Platform status](#prerequisites)).
  Implementations are complete but may have edge cases on real hardware.

## License

MIT — see [LICENSE](LICENSE).
