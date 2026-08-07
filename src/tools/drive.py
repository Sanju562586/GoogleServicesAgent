"""
Google Drive Tool Handlers
---------------------------
Exposes 5 Drive MCP tools:
  drive_list_files, drive_search_files, drive_get_file,
  drive_read_file, drive_create_folder
"""

from __future__ import annotations

import json
from typing import Any, Callable

from mcp import types

from src.gmail_auth import get_drive_service
from src.schemas import TOOL_INPUT_SCHEMAS

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="drive_list_files",
        description="List files and folders in Google Drive, sorted by most recently modified.",
        inputSchema=TOOL_INPUT_SCHEMAS["drive_list_files"],
    ),
    types.Tool(
        name="drive_search_files",
        description="Search Google Drive files by name, type, or content query.",
        inputSchema=TOOL_INPUT_SCHEMAS["drive_search_files"],
    ),
    types.Tool(
        name="drive_get_file",
        description="Get metadata (name, type, size, link, owner) for a specific Drive file by its ID.",
        inputSchema=TOOL_INPUT_SCHEMAS["drive_get_file"],
    ),
    types.Tool(
        name="drive_read_file",
        description=(
            "Read the text content of a Google Docs, Sheets (as CSV), "
            "or plain text file from Drive."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["drive_read_file"],
    ),
    types.Tool(
        name="drive_create_folder",
        description="Create a new folder in Google Drive.",
        inputSchema=TOOL_INPUT_SCHEMAS["drive_create_folder"],
    ),
]


# ── Private helpers ────────────────────────────────────────────────────────────

def _format_drive_file(f: dict) -> dict:
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mimeType": f.get("mimeType"),
        "size": f.get("size"),
        "modifiedTime": f.get("modifiedTime"),
        "webViewLink": f.get("webViewLink"),
        "owners": [o.get("displayName") for o in f.get("owners", [])],
    }


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _drive_list_files(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_drive_service()
    max_results = min(args.get("max_results", 20), 50)
    folder_id = args.get("folder_id")
    q = f"'{folder_id}' in parents and trashed=false" if folder_id else "trashed=false"
    result = service.files().list(
        q=q,
        pageSize=max_results,
        fields="files(id,name,mimeType,size,modifiedTime,webViewLink,owners)",
        orderBy="modifiedTime desc",
    ).execute()
    files = result.get("files", [])
    if not files:
        return [types.TextContent(type="text", text="No files found.")]
    return [types.TextContent(type="text", text=json.dumps([_format_drive_file(f) for f in files], indent=2))]


async def _drive_search_files(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_drive_service()
    query = args["query"]
    max_results = min(args.get("max_results", 20), 50)
    # If query is plain text (no operators), wrap it as name contains
    if "=" not in query and "contains" not in query and "in" not in query:
        query = f"name contains '{query}' and trashed=false"
    elif "trashed" not in query:
        # User provided a structured query but forgot to exclude trash
        query = f"({query}) and trashed=false"
    result = service.files().list(
        q=query,
        pageSize=max_results,
        fields="files(id,name,mimeType,size,modifiedTime,webViewLink,owners)",
        orderBy="modifiedTime desc",
    ).execute()
    files = result.get("files", [])
    if not files:
        return [types.TextContent(type="text", text="No files found.")]
    return [types.TextContent(type="text", text=json.dumps([_format_drive_file(f) for f in files], indent=2))]


async def _drive_get_file(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_drive_service()
    f = service.files().get(
        fileId=args["file_id"],
        fields="id,name,mimeType,size,modifiedTime,webViewLink,description,owners,parents"
    ).execute()
    return [types.TextContent(type="text", text=json.dumps(f, indent=2))]


async def _drive_read_file(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_drive_service()
    file_id = args["file_id"]
    max_chars = args.get("max_chars", 4000)
    meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime = meta.get("mimeType", "")
    # Google Docs → export as plain text
    if mime == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    # Google Sheets → export as CSV
    elif mime == "application/vnd.google-apps.spreadsheet":
        content = service.files().export(fileId=file_id, mimeType="text/csv").execute()
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    # Google Slides → export as plain text
    elif mime == "application/vnd.google-apps.presentation":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    # Plain text / other downloadable files
    else:
        content = service.files().get_media(fileId=file_id).execute()
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    text = text[:max_chars]
    return [types.TextContent(type="text", text=f"File: {meta['name']}\n\n{text}")]


async def _drive_create_folder(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_drive_service()
    metadata: dict = {
        "name": args["name"],
        "mimeType": "application/vnd.google-apps.folder",
    }
    if args.get("parent_folder_id"):
        metadata["parents"] = [args["parent_folder_id"]]
    folder = service.files().create(body=metadata, fields="id,name,webViewLink").execute()
    return [types.TextContent(type="text", text=(
        f"Folder created: {folder['name']} (ID: {folder['id']})\n"
        f"Link: {folder.get('webViewLink', '')}"
    ))]


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "drive_list_files": _drive_list_files,
    "drive_search_files": _drive_search_files,
    "drive_get_file": _drive_get_file,
    "drive_read_file": _drive_read_file,
    "drive_create_folder": _drive_create_folder,
}
