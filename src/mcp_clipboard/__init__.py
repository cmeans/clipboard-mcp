"""MCP server for reading and writing the system clipboard."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcp-clipboard")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"
