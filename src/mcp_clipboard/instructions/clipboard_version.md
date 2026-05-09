Return the version of mcp-clipboard currently running.

Use this when you need to record or report which mcp-clipboard build is
serving the current MCP session — for example, in test harnesses,
diagnostic dumps, or when the user asks which version is installed. The
version is read from the package metadata at runtime, so it always
matches the wheel actually serving the call.

Returns:
    A dict with keys "name" (always "mcp-clipboard") and "version" (the
    installed version string, e.g. "2.6.1"). If the package metadata
    cannot be located (uninstalled source checkout), returns
    "0.0.0+dev" as the version.
