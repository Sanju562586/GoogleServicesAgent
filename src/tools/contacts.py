"""
Google Contacts Tool Handlers
------------------------------
Exposes 2 Contacts MCP tools:
  contacts_list, contacts_search
"""

from __future__ import annotations

import json
from typing import Any, Callable

from mcp import types

from src.gmail_auth import get_people_service
from src.schemas import TOOL_INPUT_SCHEMAS

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="contacts_list",
        description="List contacts from Google Contacts.",
        inputSchema=TOOL_INPUT_SCHEMAS["contacts_list"],
    ),
    types.Tool(
        name="contacts_search",
        description="Search Google Contacts by name or email address.",
        inputSchema=TOOL_INPUT_SCHEMAS["contacts_search"],
    ),
]


# ── Private helpers ────────────────────────────────────────────────────────────

def _format_person(p: dict) -> dict:
    names = p.get("names", [{}])
    emails = p.get("emailAddresses", [{}])
    phones = p.get("phoneNumbers", [{}])
    return {
        "resourceName": p.get("resourceName"),
        "name": names[0].get("displayName", "") if names else "",
        "emails": [e.get("value") for e in emails if e.get("value")],
        "phones": [ph.get("value") for ph in phones if ph.get("value")],
    }


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _contacts_list(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_people_service()
    max_results = min(args.get("max_results", 20), 100)
    result = service.people().connections().list(
        resourceName="people/me",
        pageSize=max_results,
        personFields="names,emailAddresses,phoneNumbers",
    ).execute()
    contacts = result.get("connections", [])
    if not contacts:
        return [types.TextContent(type="text", text="No contacts found.")]
    return [types.TextContent(type="text", text=json.dumps([_format_person(c) for c in contacts], indent=2))]


async def _contacts_search(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_people_service()
    result = service.people().searchContacts(
        query=args["query"],
        readMask="names,emailAddresses,phoneNumbers",
        pageSize=10,
    ).execute()
    results = result.get("results", [])
    if not results:
        return [types.TextContent(type="text", text=f"No contacts found for '{args['query']}'.")]
    contacts = [_format_person(r.get("person", {})) for r in results]
    return [types.TextContent(type="text", text=json.dumps(contacts, indent=2))]


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "contacts_list": _contacts_list,
    "contacts_search": _contacts_search,
}
