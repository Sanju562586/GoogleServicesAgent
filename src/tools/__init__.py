"""
Tools Package
-------------
Aggregates all per-service MCP tool definitions and handler registries.

Exports:
  ALL_TOOLS      — flat list of types.Tool for MCP list_tools()
  TOOL_REGISTRY  — dict[tool_name, async_handler] for MCP call_tool()
"""

from __future__ import annotations

from typing import Any, Callable

from mcp import types

from src.tools import calendar, contacts, drive, gmail, photos, tasks

# Flat list of all MCP Tool objects — returned by list_tools()
ALL_TOOLS: list[types.Tool] = (
    gmail.TOOLS
    + drive.TOOLS
    + calendar.TOOLS
    + photos.TOOLS
    + tasks.TOOLS
    + contacts.TOOLS
)

# Unified dispatch table — maps tool name → async handler function
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    **gmail.HANDLERS,
    **drive.HANDLERS,
    **calendar.HANDLERS,
    **photos.HANDLERS,
    **tasks.HANDLERS,
    **contacts.HANDLERS,
}

__all__ = ["ALL_TOOLS", "TOOL_REGISTRY"]
