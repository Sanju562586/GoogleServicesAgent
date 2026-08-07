"""
Gmail MCP Server
----------------
Exposes Gmail operations as MCP tools:
  - gmail_list_emails    : Fetch recent emails from inbox
  - gmail_search_emails  : Search emails by query string
  - gmail_get_email      : Get full content of a single email
  - gmail_send_email     : Send a new email
  - gmail_reply_email    : Reply to an existing email
"""

import asyncio
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from src.tools.gmail import HANDLERS, TOOLS

app = Server("gmail-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    # Support both canonical name (gmail_list_emails) and legacy short name (list_emails)
    handler = HANDLERS.get(name) or HANDLERS.get(f"gmail_{name}")
    if handler is None:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        return await handler(arguments)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing {name}: {e}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
