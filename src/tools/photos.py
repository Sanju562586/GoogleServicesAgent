"""
Google Photos Tool Handlers
----------------------------
Exposes 3 Photos MCP tools:
  photos_list_albums, photos_list_photos, photos_search_photos
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import requests
from mcp import types

from src.gmail_auth import get_credentials
from src.schemas import TOOL_INPUT_SCHEMAS

PHOTOS_BASE = "https://photoslibrary.googleapis.com/v1"

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="photos_list_albums",
        description="List albums in Google Photos.",
        inputSchema=TOOL_INPUT_SCHEMAS["photos_list_albums"],
    ),
    types.Tool(
        name="photos_list_photos",
        description="List photos/media items, optionally filtered by album.",
        inputSchema=TOOL_INPUT_SCHEMAS["photos_list_photos"],
    ),
    types.Tool(
        name="photos_search_photos",
        description="Search Google Photos by date range or content category.",
        inputSchema=TOOL_INPUT_SCHEMAS["photos_search_photos"],
    ),
]


# ── Private helpers ────────────────────────────────────────────────────────────

def _photos_headers() -> dict:
    """Return an Authorization header with a fresh bearer token."""
    creds = get_credentials()
    if creds.expired:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        # Persist the refreshed token so future calls don't re-trigger a refresh.
        token_file = Path(__file__).resolve().parent.parent.parent / "config" / "token.json"
        token_file.write_text(creds.to_json())
    return {"Authorization": f"Bearer {creds.token}"}


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _photos_list_albums(args: dict[str, Any]) -> list[types.TextContent]:
    max_results = max(1, min(int(args.get("max_results", 20)), 50))
    # requests.get is blocking I/O — run in a thread to avoid stalling the event loop.
    resp = await asyncio.to_thread(
        requests.get,
        f"{PHOTOS_BASE}/albums",
        headers=_photos_headers(),
        params={"pageSize": max_results},
        timeout=15,
    )
    if not resp.ok:
        return [types.TextContent(type="text", text=(
            f"Photos API HTTP {resp.status_code} error:\n{resp.text}\n\n"
            "Fix: In Google Cloud Console → APIs & Services → OAuth consent screen → "
            "Edit App → Scopes → Add 'photoslibrary.readonly', then delete config/token.json and re-run."
        ))]
    albums = resp.json().get("albums", [])
    if not albums:
        return [types.TextContent(type="text", text="No albums found.")]
    formatted = [
        {
            "id": a["id"],
            "title": a.get("title", "(untitled)"),
            "itemCount": a.get("mediaItemsCount", 0),
            "link": a.get("productUrl", ""),
        }
        for a in albums
    ]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _photos_list_photos(args: dict[str, Any]) -> list[types.TextContent]:
    max_results = max(1, min(int(args.get("max_results", 20)), 50))
    headers = _photos_headers()
    body: dict = {"pageSize": max_results}
    if args.get("album_id"):
        body["albumId"] = args["album_id"]
    # requests.post is blocking I/O — run in a thread to avoid stalling the event loop.
    resp = await asyncio.to_thread(
        requests.post,
        f"{PHOTOS_BASE}/mediaItems:search",
        headers=headers,
        json=body,
        timeout=15,
    )
    if not resp.ok:
        return [types.TextContent(type="text", text=f"Photos API HTTP {resp.status_code} error:\n{resp.text}")]
    items = resp.json().get("mediaItems", [])
    if not items:
        return [types.TextContent(type="text", text="No photos found.")]
    formatted = [
        {
            "id": i["id"],
            "filename": i.get("filename"),
            "description": i.get("description", ""),
            "creationTime": i.get("mediaMetadata", {}).get("creationTime"),
            "url": i.get("productUrl"),
        }
        for i in items
    ]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _photos_search_photos(args: dict[str, Any]) -> list[types.TextContent]:
    max_results = max(1, min(int(args.get("max_results", 20)), 50))
    filters: dict = {}
    if args.get("start_date") or args.get("end_date"):
        date_filter: dict = {}
        if args.get("start_date"):
            y, mo, d = args["start_date"].split("-")
            date_filter["startDate"] = {"year": int(y), "month": int(mo), "day": int(d)}
        if args.get("end_date"):
            y, mo, d = args["end_date"].split("-")
            date_filter["endDate"] = {"year": int(y), "month": int(mo), "day": int(d)}
        filters["dateFilter"] = {"ranges": [date_filter]}
    if args.get("category"):
        filters["contentFilter"] = {"includedContentCategories": [args["category"]]}
    body: dict = {"pageSize": max_results}
    if filters:
        body["filters"] = filters
    # requests.post is blocking I/O — run in a thread to avoid stalling the event loop.
    resp = await asyncio.to_thread(
        requests.post,
        f"{PHOTOS_BASE}/mediaItems:search",
        headers=_photos_headers(),
        json=body,
        timeout=15,
    )
    if not resp.ok:
        return [types.TextContent(type="text", text=f"Photos API error: {resp.text}")]
    items = resp.json().get("mediaItems", [])
    if not items:
        return [types.TextContent(type="text", text="No photos found matching your search.")]
    formatted = [
        {
            "id": i["id"],
            "filename": i.get("filename"),
            "creationTime": i.get("mediaMetadata", {}).get("creationTime"),
            "url": i.get("productUrl"),
        }
        for i in items
    ]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "photos_list_albums": _photos_list_albums,
    "photos_list_photos": _photos_list_photos,
    "photos_search_photos": _photos_search_photos,
}
