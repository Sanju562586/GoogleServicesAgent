"""
Google Services MCP Server
---------------------------
Unified MCP server exposing tools for:
  Gmail     — list, search, read, send, reply emails
  Drive     — list, search, read, create files/folders
  Calendar  — list, create, update, delete events
  Photos    — list albums, list/search photos
  Tasks     — list task lists, list/create/complete tasks
  Contacts  — list and search contacts

This module is intentionally thin: all tool definitions and handler logic
live in ``src/tools/`` (one module per Google service). Schemas live in
``src/schemas.py``. This file simply wires them together via the MCP Server.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from typing import Any

from src.tools import ALL_TOOLS, TOOL_REGISTRY

app = Server("google-all-mcp")


# ── Tool registration ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return all available Google service tools."""
    return ALL_TOOLS


# ── Tool dispatch ──────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Dispatch a tool call to the appropriate service handler."""
    handler = TOOL_REGISTRY.get(name)
    if handler is None:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        return await handler(arguments)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error in {name}: {e}")]


# ── Entry point ────────────────────────────────────────────────────────────────

async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
