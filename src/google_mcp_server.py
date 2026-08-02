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
"""

import json
import base64
import asyncio
import os
import requests
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from src.gmail_auth import (
    get_gmail_service,
    get_drive_service,
    get_calendar_service,
    get_people_service,
    get_tasks_service,
    get_credentials,
)

app = Server("google-all-mcp")
PHOTOS_BASE = "https://photoslibrary.googleapis.com/v1"

# IST offset constant (UTC+05:30)
_IST = timezone(timedelta(hours=5, minutes=30))


def _normalize_datetime_ist(dt_str: str) -> str:
    """
    Ensure a datetime string is treated as IST (+05:30).

    STRATEGY: The LLM is always instructed to output the literal IST clock
    values (e.g. '14:00' for 2 PM IST). We therefore STRIP any existing
    timezone suffix and RE-APPLY +05:30. This prevents double-conversion bugs
    where the LLM outputs '08:30Z' thinking it's UTC-equivalent of 2 PM IST,
    and we accidentally re-convert to 19:30 IST.

    Examples:
      '2026-08-03T14:00:00+05:30'  -> '2026-08-03T14:00:00+05:30' (unchanged)
      '2026-08-03T14:00:00Z'       -> '2026-08-03T14:00:00+05:30' (strip Z, add IST)
      '2026-08-03T14:00:00+00:00'  -> '2026-08-03T14:00:00+05:30' (strip UTC, add IST)
      '2026-08-03T14:00:00'        -> '2026-08-03T14:00:00+05:30' (bare, add IST)
      '2026-08-03'                 -> '2026-08-03T00:00:00+05:30' (date-only)
      '08:30 AM'                   -> graceful fallback
    """
    if not dt_str:
        return dt_str
    dt_str = dt_str.strip()
    try:
        # Date-only — add midnight IST
        if len(dt_str) == 10 and 'T' not in dt_str:
            return f"{dt_str}T00:00:00+05:30"

        # Already correct IST — return as-is
        if dt_str.endswith('+05:30'):
            return dt_str

        # Strip any timezone suffix to get the bare local datetime string.
        # We treat whatever hours the LLM wrote as IST clock hours.
        bare = dt_str
        # Remove Z / +00:00 / +05:00 / -05:30 etc.
        for suffix in ('+00:00', '+05:00', '+05:30', '-05:30', '-08:00'):
            if bare.endswith(suffix):
                bare = bare[:-len(suffix)]
                break
        bare = bare.rstrip('Z')

        # Validate the bare string is parseable
        datetime.fromisoformat(bare)  # raises ValueError if malformed
        return f"{bare}+05:30"
    except Exception:
        pass
    # Fallback: return as-is and let Google API handle/reject
    return dt_str


def _validate_ist_time(label: str, dt_str: str) -> None:
    """
    Debug helper: print the datetime string being sent to Google Calendar.
    Writes to STDERR so it does NOT corrupt the MCP JSON-RPC stdout stream.
    """
    import sys
    print(f"[CALENDAR DEBUG] {label}: '{dt_str}'", file=sys.stderr, flush=True)


def _shift_ist_hours(dt_str: str, hours: float = 5.5) -> str:
    """
    Shift a normalized IST datetime string by `hours`.
    Returns the shifted datetime string with +05:30 suffix preserved.
    If parsing fails the original string is returned unchanged.

    Default: +5.5 hours (+5h 30m).
    Example:
      '2026-08-03T02:30:00+05:30' + 5.5h -> '2026-08-03T08:00:00+05:30'
      '2026-08-03T09:30:00+05:30' + 5.5h -> '2026-08-03T15:00:00+05:30'
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        dt_shifted = dt + timedelta(hours=hours)
        return dt_shifted.strftime('%Y-%m-%dT%H:%M:%S+05:30')
    except Exception:
        return dt_str                                # fallback: return unchanged



# ── Tool Definitions ───────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        # ── Gmail ──────────────────────────────────────────────────────────────
        types.Tool(
            name="gmail_list_emails",
            description="List recent emails from Gmail inbox or a specific label. Use when asked to show, list, or check recent emails.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 10, "description": "Number of emails to fetch (max 50)."},
                    "label": {"type": "string", "default": "INBOX", "description": "Gmail label: INBOX, SENT, UNREAD, SPAM, etc."},
                },
            },
        ),
        types.Tool(
            name="gmail_search_emails",
            description="Search Gmail emails using query syntax (e.g. 'from:boss@company.com', 'is:unread', 'subject:invoice', 'newer_than:1d').",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query string."},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="gmail_get_email",
            description="Read the full body and details of a single Gmail email by its message ID.",
            inputSchema={
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        ),
        types.Tool(
            name="gmail_send_email",
            description="Send a new email via Gmail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string", "description": "Comma-separated CC addresses (optional)."},
                },
                "required": ["to", "subject", "body"],
            },
        ),
        types.Tool(
            name="gmail_reply_email",
            description="Reply to an existing Gmail email thread by message ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["message_id", "body"],
            },
        ),
        # ── Google Drive ───────────────────────────────────────────────────────
        types.Tool(
            name="drive_list_files",
            description="List files and folders in Google Drive, sorted by most recently modified.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 20},
                    "folder_id": {"type": "string", "description": "List files inside a specific folder ID (optional). Use 'root' for root folder."},
                },
            },
        ),
        types.Tool(
            name="drive_search_files",
            description="Search Google Drive files by name, type, or content query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Drive query string e.g. \"name contains 'budget'\" or \"mimeType='application/pdf'\"."},
                    "max_results": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="drive_get_file",
            description="Get metadata (name, type, size, link, owner) for a specific Drive file by its ID.",
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "string"}},
                "required": ["file_id"],
            },
        ),
        types.Tool(
            name="drive_read_file",
            description="Read the text content of a Google Docs, Sheets (as CSV), or plain text file from Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 4000, "description": "Maximum characters to return."},
                },
                "required": ["file_id"],
            },
        ),
        types.Tool(
            name="drive_create_folder",
            description="Create a new folder in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "parent_folder_id": {"type": "string", "description": "Parent folder ID (optional, defaults to root)."},
                },
                "required": ["name"],
            },
        ),
        # ── Google Calendar ────────────────────────────────────────────────────
        types.Tool(
            name="calendar_list_events",
            description="List upcoming calendar events within a time window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 7, "description": "How many days ahead to look."},
                    "max_results": {"type": "integer", "default": 15},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
            },
        ),
        types.Tool(
            name="calendar_search_events",
            description="Search calendar events by keyword in title or description.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 15},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="calendar_create_event",
            description="Create a new event on Google Calendar. Always provide start and end times in IST (India Standard Time, UTC+05:30) using ISO 8601 format. Example: '2025-08-10T10:00:00+05:30'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "Start datetime in IST ISO 8601 format e.g. '2025-08-10T10:00:00+05:30'. MUST include +05:30 timezone offset."},
                    "end": {"type": "string", "description": "End datetime in IST ISO 8601 format e.g. '2025-08-10T11:00:00+05:30'. MUST include +05:30 timezone offset. Default to 1 hour after start if not specified."},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "string", "description": "Comma-separated attendee emails."},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["title", "start", "end"],
            },
        ),
        types.Tool(
            name="calendar_delete_event",
            description="Delete a calendar event by event ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["event_id"],
            },
        ),
        types.Tool(
            name="calendar_update_event",
            description="Update an existing calendar event's title, start time, end time, description, or location. Use this to fix a wrongly-timed event. Always use IST (UTC+05:30) for times.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "The event ID to update (get it from calendar_list_events or calendar_search_events)."},
                    "title": {"type": "string", "description": "New event title (optional)."},
                    "start": {"type": "string", "description": "New start datetime in IST ISO 8601 e.g. '2026-08-03T14:00:00+05:30' (optional)."},
                    "end": {"type": "string", "description": "New end datetime in IST ISO 8601 e.g. '2026-08-03T15:00:00+05:30' (optional)."},
                    "description": {"type": "string", "description": "New description (optional)."},
                    "location": {"type": "string", "description": "New location (optional)."},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["event_id"],
            },
        ),
        # ── Google Photos ──────────────────────────────────────────────────────
        types.Tool(
            name="photos_list_albums",
            description="List albums in Google Photos.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 20},
                },
            },
        ),
        types.Tool(
            name="photos_list_photos",
            description="List photos/media items, optionally from a specific album.",
            inputSchema={
                "type": "object",
                "properties": {
                    "album_id": {"type": "string", "description": "Album ID to list photos from (optional, defaults to all photos)."},
                    "max_results": {"type": "integer", "default": 20},
                },
            },
        ),
        types.Tool(
            name="photos_search_photos",
            description="Search Google Photos by date range or content categories (LANDSCAPES, SELFIES, ANIMALS, FOOD, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (optional)."},
                    "category": {"type": "string", "description": "Content category: LANDSCAPES, SELFIES, ANIMALS, FOOD, TRAVEL, WEDDINGS, BIRTHDAYS (optional)."},
                    "max_results": {"type": "integer", "default": 20},
                },
            },
        ),
        # ── Google Tasks ───────────────────────────────────────────────────────
        types.Tool(
            name="tasks_list_tasklists",
            description="List all Google Tasks task lists.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="tasks_list_tasks",
            description="List tasks in a specific task list (defaults to '@default').",
            inputSchema={
                "type": "object",
                "properties": {
                    "tasklist_id": {"type": "string", "default": "@default"},
                    "show_completed": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 20},
                },
            },
        ),
        types.Tool(
            name="tasks_create_task",
            description="Create a new task in Google Tasks. For the due date, always use IST (UTC+05:30) ISO 8601 format e.g. '2025-08-15T00:00:00+05:30'. Only the date portion is stored by Google Tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "due": {"type": "string", "description": "Due date in IST ISO 8601 format e.g. '2025-08-15T00:00:00+05:30'. Only the date portion is used."},
                    "tasklist_id": {"type": "string", "default": "@default"},
                },
                "required": ["title"],
            },
        ),
        types.Tool(
            name="tasks_complete_task",
            description="Mark a Google Task as completed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "tasklist_id": {"type": "string", "default": "@default"},
                },
                "required": ["task_id"],
            },
        ),
        # ── Google Contacts ────────────────────────────────────────────────────
        types.Tool(
            name="contacts_list",
            description="List contacts from Google Contacts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 20},
                },
            },
        ),
        types.Tool(
            name="contacts_search",
            description="Search Google Contacts by name or email address.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    ]


# ── Tool Router ────────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        # Gmail
        if name == "gmail_list_emails":
            return await _gmail_list_emails(arguments)
        elif name == "gmail_search_emails":
            return await _gmail_search_emails(arguments)
        elif name == "gmail_get_email":
            return await _gmail_get_email(arguments)
        elif name == "gmail_send_email":
            return await _gmail_send_email(arguments)
        elif name == "gmail_reply_email":
            return await _gmail_reply_email(arguments)
        # Drive
        elif name == "drive_list_files":
            return await _drive_list_files(arguments)
        elif name == "drive_search_files":
            return await _drive_search_files(arguments)
        elif name == "drive_get_file":
            return await _drive_get_file(arguments)
        elif name == "drive_read_file":
            return await _drive_read_file(arguments)
        elif name == "drive_create_folder":
            return await _drive_create_folder(arguments)
        # Calendar
        elif name == "calendar_list_events":
            return await _calendar_list_events(arguments)
        elif name == "calendar_search_events":
            return await _calendar_search_events(arguments)
        elif name == "calendar_create_event":
            return await _calendar_create_event(arguments)
        elif name == "calendar_update_event":
            return await _calendar_update_event(arguments)
        elif name == "calendar_delete_event":
            return await _calendar_delete_event(arguments)
        # Photos
        elif name == "photos_list_albums":
            return await _photos_list_albums(arguments)
        elif name == "photos_list_photos":
            return await _photos_list_photos(arguments)
        elif name == "photos_search_photos":
            return await _photos_search_photos(arguments)
        # Tasks
        elif name == "tasks_list_tasklists":
            return await _tasks_list_tasklists(arguments)
        elif name == "tasks_list_tasks":
            return await _tasks_list_tasks(arguments)
        elif name == "tasks_create_task":
            return await _tasks_create_task(arguments)
        elif name == "tasks_complete_task":
            return await _tasks_complete_task(arguments)
        # Contacts
        elif name == "contacts_list":
            return await _contacts_list(arguments)
        elif name == "contacts_search":
            return await _contacts_search(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error in {name}: {e}")]


# ══════════════════════════════════════════════════════════════════════════════
# Gmail helpers
# ══════════════════════════════════════════════════════════════════════════════

def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit] + "…" if len(text) > limit else text


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            padding = "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
        return ""
    if "parts" in payload:
        for part in payload["parts"]:
            text = _extract_body(part)
            if text:
                return text
    return ""


def _parse_headers(headers: list[dict]) -> dict:
    res = {}
    for h in headers:
        res[h["name"]] = h["value"]
        res[h["name"].lower()] = h["value"]
    return res


def _format_gmail_message(msg: dict) -> dict:
    headers = _parse_headers(msg["payload"]["headers"])
    return {
        "id": msg["id"],
        "from": headers.get("From", headers.get("from", "")),
        "to": headers.get("To", headers.get("to", "")),
        "subject": headers.get("Subject", headers.get("subject", "(no subject)")),
        "date": headers.get("Date", headers.get("date", "")),
        "snippet": msg.get("snippet", ""),
    }


async def _gmail_list_emails(args: dict) -> list[types.TextContent]:
    service = get_gmail_service()
    max_results = min(args.get("max_results", 10), 50)
    label = args.get("label", "INBOX")
    result = service.users().messages().list(
        userId="me", labelIds=[label], maxResults=max_results
    ).execute()
    messages = result.get("messages", [])
    if not messages:
        return [types.TextContent(type="text", text="No emails found.")]
    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()
        emails.append(_format_gmail_message(msg))
    return [types.TextContent(type="text", text=json.dumps(emails, indent=2))]


async def _gmail_search_emails(args: dict) -> list[types.TextContent]:
    service = get_gmail_service()
    query = args["query"]
    max_results = min(args.get("max_results", 10), 50)
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    messages = result.get("messages", [])
    if not messages:
        return [types.TextContent(type="text", text=f"No emails found for: {query}")]
    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()
        emails.append(_format_gmail_message(msg))
    return [types.TextContent(type="text", text=json.dumps(emails, indent=2))]


async def _gmail_get_email(args: dict) -> list[types.TextContent]:
    service = get_gmail_service()
    msg = service.users().messages().get(
        userId="me", id=args["message_id"], format="full"
    ).execute()
    headers = _parse_headers(msg["payload"]["headers"])
    body = _extract_body(msg["payload"])
    email = {
        "id": msg["id"],
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "date": headers.get("Date", ""),
        "body": body or msg.get("snippet", ""),
    }
    return [types.TextContent(type="text", text=json.dumps(email, indent=2))]


async def _gmail_send_email(args: dict) -> list[types.TextContent]:
    service = get_gmail_service()
    msg = MIMEMultipart()
    msg["to"] = args["to"]
    msg["subject"] = args["subject"]
    if args.get("cc"):
        msg["cc"] = args["cc"]
    msg.attach(MIMEText(args["body"], "plain"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return [types.TextContent(type="text", text=f"Email sent! Message ID: {sent['id']}")]


async def _gmail_reply_email(args: dict) -> list[types.TextContent]:
    service = get_gmail_service()
    original = service.users().messages().get(
        userId="me", id=args["message_id"], format="metadata",
        metadataHeaders=["From", "Subject", "Message-ID", "References"]
    ).execute()
    headers = _parse_headers(original["payload"]["headers"])
    thread_id = original["threadId"]
    orig_from = headers.get("From", headers.get("from", ""))
    orig_subj = headers.get("Subject", headers.get("subject", ""))
    orig_msg_id = headers.get("Message-ID", headers.get("message-id", ""))
    orig_refs = headers.get("References", headers.get("references", ""))
    reply = MIMEText(args["body"], "plain")
    reply["to"] = orig_from
    reply["subject"] = orig_subj if orig_subj.lower().startswith("re:") else f"Re: {orig_subj}"
    if orig_msg_id:
        reply["In-Reply-To"] = orig_msg_id
        reply["References"] = f"{orig_refs} {orig_msg_id}".strip()
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
    sent = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()
    return [types.TextContent(type="text", text=f"Reply sent! Message ID: {sent['id']}")]


# ══════════════════════════════════════════════════════════════════════════════
# Google Drive helpers
# ══════════════════════════════════════════════════════════════════════════════

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


async def _drive_list_files(args: dict) -> list[types.TextContent]:
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


async def _drive_search_files(args: dict) -> list[types.TextContent]:
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


async def _drive_get_file(args: dict) -> list[types.TextContent]:
    service = get_drive_service()
    f = service.files().get(
        fileId=args["file_id"],
        fields="id,name,mimeType,size,modifiedTime,webViewLink,description,owners,parents"
    ).execute()
    return [types.TextContent(type="text", text=json.dumps(f, indent=2))]


async def _drive_read_file(args: dict) -> list[types.TextContent]:
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


async def _drive_create_folder(args: dict) -> list[types.TextContent]:
    service = get_drive_service()
    metadata = {
        "name": args["name"],
        "mimeType": "application/vnd.google-apps.folder",
    }
    if args.get("parent_folder_id"):
        metadata["parents"] = [args["parent_folder_id"]]
    folder = service.files().create(body=metadata, fields="id,name,webViewLink").execute()
    return [types.TextContent(type="text", text=f"Folder created: {folder['name']} (ID: {folder['id']})\nLink: {folder.get('webViewLink', '')}")]


# ══════════════════════════════════════════════════════════════════════════════
# Google Calendar helpers
# ══════════════════════════════════════════════════════════════════════════════

def _to_ist_display(dt_val: str | None) -> str:
    """Convert any datetime string (UTC/ISO/bare) to a human-readable IST string."""
    if not dt_val:
        return ""
    try:
        # Normalise the raw string from Google API (usually UTC with Z suffix)
        normalised = dt_val.strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalised)
        ist_dt = dt.astimezone(_IST)
        return ist_dt.strftime('%I:%M %p IST, %a %d %b %Y')   # e.g. "02:00 PM IST, Mon 03 Aug 2026"
    except Exception:
        return dt_val  # fallback: return raw


def _to_ist_iso(dt_val: str | None) -> str:
    """Return a clean ISO 8601 string with +05:30 offset from any input datetime."""
    if not dt_val:
        return ""
    try:
        normalised = dt_val.strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalised)
        ist_dt = dt.astimezone(_IST)
        return ist_dt.strftime('%Y-%m-%dT%H:%M:%S+05:30')
    except Exception:
        return dt_val


def _format_event(e: dict) -> dict:
    raw_start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
    raw_end   = e.get("end",   {}).get("dateTime") or e.get("end",   {}).get("date")
    return {
        "id": e["id"],
        "title": e.get("summary", "(no title)"),
        # Always present times in IST so the LLM / user always sees the correct local time
        "start_IST": _to_ist_display(raw_start),
        "start_iso": _to_ist_iso(raw_start),
        "end_IST": _to_ist_display(raw_end),
        "end_iso": _to_ist_iso(raw_end),
        "location": e.get("location", ""),
        "description": e.get("description", ""),
        "attendees": [a.get("email") for a in e.get("attendees", [])],
        "link": e.get("htmlLink", ""),
    }


async def _calendar_list_events(args: dict) -> list[types.TextContent]:
    service = get_calendar_service()
    days = args.get("days_ahead", 7)
    max_results = min(args.get("max_results", 15), 50)
    cal_id = args.get("calendar_id", "primary")
    # FIX #6: Google Calendar API requires strict RFC 3339 with 'Z' suffix.
    # datetime.isoformat() produces '+00:00' which some API versions reject.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = service.events().list(
        calendarId=cal_id, timeMin=now, timeMax=end,
        maxResults=max_results, singleEvents=True, orderBy="startTime"
    ).execute()
    events = result.get("items", [])
    if not events:
        return [types.TextContent(type="text", text=f"No events in the next {days} days.")]
    return [types.TextContent(type="text", text=json.dumps([_format_event(e) for e in events], indent=2))]


async def _calendar_search_events(args: dict) -> list[types.TextContent]:
    service = get_calendar_service()
    max_results = min(args.get("max_results", 15), 50)
    cal_id = args.get("calendar_id", "primary")
    # timeMin is required by Google Calendar API when orderBy="startTime" + singleEvents=True.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = service.events().list(
        calendarId=cal_id, q=args["query"], timeMin=now,
        maxResults=max_results, singleEvents=True, orderBy="startTime"
    ).execute()
    events = result.get("items", [])
    if not events:
        return [types.TextContent(type="text", text="No matching events found.")]
    return [types.TextContent(type="text", text=json.dumps([_format_event(e) for e in events], indent=2))]


async def _calendar_create_event(args: dict) -> list[types.TextContent]:
    service = get_calendar_service()
    cal_id = args.get("calendar_id", "primary")

    # Log raw LLM output BEFORE normalization so we can see what it sent
    _validate_ist_time("RAW start (from LLM)", args["start"])
    _validate_ist_time("RAW end   (from LLM)", args["end"])

    # Normalize start/end to proper IST datetimes — guards against the LLM
    # sending UTC 'Z' times or bare datetimes without a timezone offset.
    start_str = _normalize_datetime_ist(args["start"])
    end_str = _normalize_datetime_ist(args["end"])

    # ⏩ USER PREFERENCE: shift event times +5h30m from what was spoken.
    # e.g. user says '2:30 AM' → stored as 8:00 AM IST.
    start_str = _shift_ist_hours(start_str)
    end_str   = _shift_ist_hours(end_str)

    # Fallback: if end is still missing/invalid, default to 1 hour after start.
    if not end_str:
        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(start_str)
            end_dt = start_dt + timedelta(hours=1)
            end_str = end_dt.strftime('%Y-%m-%dT%H:%M:%S+05:30')
        except Exception:
            end_str = start_str  # worst-case fallback

    body: dict = {
        "summary": args["title"],
        "start": {"dateTime": start_str, "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_str, "timeZone": "Asia/Kolkata"},
    }
    if args.get("description"):
        body["description"] = args["description"]
    if args.get("location"):
        body["location"] = args["location"]
    if args.get("attendees"):
        body["attendees"] = [{"email": e.strip()} for e in args["attendees"].split(",")]
    event = service.events().insert(calendarId=cal_id, body=body).execute()
    # Readable confirmation in IST — using _to_ist_display on the RESPONSE
    # so even if Google normalises the stored time, we show the correct IST value.
    resp_start = event.get("start", {}).get("dateTime", start_str)
    resp_end   = event.get("end",   {}).get("dateTime", end_str)
    return [types.TextContent(type="text", text=(
        f"✅ Event created: **{event['summary']}**\n"
        f"🕐 Start : {_to_ist_display(resp_start)}\n"
        f"🕑 End   : {_to_ist_display(resp_end)}\n"
        f"🔗 Link  : {event.get('htmlLink', '')}"
    ))]


async def _calendar_delete_event(args: dict) -> list[types.TextContent]:
    service = get_calendar_service()
    cal_id = args.get("calendar_id", "primary")
    service.events().delete(calendarId=cal_id, eventId=args["event_id"]).execute()
    return [types.TextContent(type="text", text=f"Event {args['event_id']} deleted.")]


async def _calendar_update_event(args: dict) -> list[types.TextContent]:
    """Patch an existing calendar event with updated fields."""
    service = get_calendar_service()
    cal_id = args.get("calendar_id", "primary")
    event_id = args["event_id"]

    # Fetch the current event to preserve unchanged fields
    existing = service.events().get(calendarId=cal_id, eventId=event_id).execute()
    patch: dict = {}

    if args.get("title"):
        patch["summary"] = args["title"]
    if args.get("description"):
        patch["description"] = args["description"]
    if args.get("location"):
        patch["location"] = args["location"]

    # Normalize and update start/end if provided, with +5h30m user preference shift
    if args.get("start"):
        start_str = _shift_ist_hours(_normalize_datetime_ist(args["start"]))
        patch["start"] = {"dateTime": start_str, "timeZone": "Asia/Kolkata"}
    else:
        start_str = existing.get("start", {}).get("dateTime", "")

    if args.get("end"):
        end_str = _shift_ist_hours(_normalize_datetime_ist(args["end"]))
        patch["end"] = {"dateTime": end_str, "timeZone": "Asia/Kolkata"}
    else:
        end_str = existing.get("end", {}).get("dateTime", "")

    if not patch:
        return [types.TextContent(type="text", text="No changes provided. Please specify title, start, end, description, or location.")]

    updated = service.events().patch(calendarId=cal_id, eventId=event_id, body=patch).execute()
    return [types.TextContent(type="text", text=(
        f"✅ Event updated: **{updated.get('summary', event_id)}**\n"
        f"🕐 Start: {start_str}\n"
        f"🕑 End:   {end_str}\n"
        f"🔗 Link: {updated.get('htmlLink', '')}"
    ))]


# ══════════════════════════════════════════════════════════════════════════════
# Google Photos helpers  (REST API via bearer token)
# ══════════════════════════════════════════════════════════════════════════════

def _photos_headers() -> dict:
    creds = get_credentials()
    if creds.expired:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        # Persist the refreshed token so future calls don't re-trigger a refresh.
        TOKEN_FILE = Path(__file__).resolve().parent.parent / "config" / "token.json"
        TOKEN_FILE.write_text(creds.to_json())
    return {"Authorization": f"Bearer {creds.token}"}


async def _photos_list_albums(args: dict) -> list[types.TextContent]:
    max_results = min(args.get("max_results", 20), 50)
    # FIX #7: requests.get is blocking I/O — wrap in asyncio.to_thread so it
    # does not stall the asyncio event loop.
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
    formatted = [{"id": a["id"], "title": a.get("title", "(untitled)"), "itemCount": a.get("mediaItemsCount", 0), "link": a.get("productUrl", "")} for a in albums]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _photos_list_photos(args: dict) -> list[types.TextContent]:
    max_results = min(args.get("max_results", 20), 50)
    headers = _photos_headers()
    # FIX #7: Wrap blocking requests.post in asyncio.to_thread.
    if args.get("album_id"):
        resp = await asyncio.to_thread(
            requests.post,
            f"{PHOTOS_BASE}/mediaItems:search",
            headers=headers,
            json={"albumId": args["album_id"], "pageSize": max_results},
            timeout=15,
        )
    else:
        resp = await asyncio.to_thread(
            requests.post,
            f"{PHOTOS_BASE}/mediaItems:search",
            headers=headers,
            json={"pageSize": max_results},
            timeout=15,
        )
    if not resp.ok:
        return [types.TextContent(type="text", text=f"Photos API HTTP {resp.status_code} error:\n{resp.text}")]
    items = resp.json().get("mediaItems", [])
    if not items:
        return [types.TextContent(type="text", text="No photos found.")]
    formatted = [{"id": i["id"], "filename": i.get("filename"), "description": i.get("description", ""), "creationTime": i.get("mediaMetadata", {}).get("creationTime"), "url": i.get("productUrl")} for i in items]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _photos_search_photos(args: dict) -> list[types.TextContent]:
    max_results = min(args.get("max_results", 20), 50)
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
    # FIX #7: Wrap blocking requests.post in asyncio.to_thread.
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
    formatted = [{"id": i["id"], "filename": i.get("filename"), "creationTime": i.get("mediaMetadata", {}).get("creationTime"), "url": i.get("productUrl")} for i in items]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


# ══════════════════════════════════════════════════════════════════════════════
# Google Tasks helpers
# ══════════════════════════════════════════════════════════════════════════════

async def _tasks_list_tasklists(args: dict) -> list[types.TextContent]:
    service = get_tasks_service()
    result = service.tasklists().list(maxResults=20).execute()
    lists = result.get("items", [])
    if not lists:
        return [types.TextContent(type="text", text="No task lists found.")]
    return [types.TextContent(type="text", text=json.dumps([{"id": l["id"], "title": l["title"]} for l in lists], indent=2))]


async def _tasks_list_tasks(args: dict) -> list[types.TextContent]:
    service = get_tasks_service()
    tasklist_id = args.get("tasklist_id", "@default")
    max_results = min(args.get("max_results", 20), 100)
    result = service.tasks().list(
        tasklist=tasklist_id,
        maxResults=max_results,
        showCompleted=args.get("show_completed", False),
        showHidden=False,
    ).execute()
    tasks = result.get("items", [])
    if not tasks:
        return [types.TextContent(type="text", text="No tasks found.")]
    formatted = [{"id": t["id"], "title": t.get("title"), "status": t.get("status"), "due": t.get("due"), "notes": t.get("notes", "")} for t in tasks]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _tasks_create_task(args: dict) -> list[types.TextContent]:
    service = get_tasks_service()
    tasklist_id = args.get("tasklist_id", "@default")
    body: dict = {"title": args["title"]}
    if args.get("notes"):
        body["notes"] = args["notes"]
    if args.get("due"):
        # Google Tasks API requires due in RFC 3339 UTC format (ends with 'Z').
        # Normalize: convert IST (+05:30) or bare datetime to UTC 'Z' format.
        due_str = args["due"].strip()
        try:
            # Parse with or without timezone info
            if due_str.endswith('Z') or due_str.endswith('+00:00'):
                # Already UTC — keep as-is, just ensure Z suffix
                due_normalized = due_str.replace('+00:00', 'Z')
                if not due_normalized.endswith('Z'):
                    due_normalized += 'Z'
            else:
                # Parse as IST (or whatever offset is present) and convert to UTC
                ist_dt = datetime.fromisoformat(
                    due_str if ('+' in due_str[10:] or due_str.count('-') > 3)
                    else due_str + '+05:30'
                )
                utc_dt = ist_dt.astimezone(timezone.utc)
                due_normalized = utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            # Fallback: pass as-is and let Google API validate
            due_normalized = due_str
        body["due"] = due_normalized
    task = service.tasks().insert(tasklist=tasklist_id, body=body).execute()
    # Show the due date in IST for user-friendly confirmation
    due_display = ""
    if task.get("due"):
        try:
            utc_due = datetime.fromisoformat(task["due"].replace('Z', '+00:00'))
            ist_due = utc_due.astimezone(_IST)
            due_display = f"\n📅 Due: {ist_due.strftime('%A, %d %B %Y')}"
        except Exception:
            due_display = f"\n📅 Due: {task['due']}"
    return [types.TextContent(type="text", text=f"✅ Task created: '{task['title']}' (ID: {task['id']}){due_display}")]


async def _tasks_complete_task(args: dict) -> list[types.TextContent]:
    service = get_tasks_service()
    tasklist_id = args.get("tasklist_id", "@default")
    # Use patch() with only the changed field — sending the full task object via update()
    # causes a 400 error because read-only fields (etag, selfLink, kind, etc.) are rejected.
    task_id = args["task_id"]
    updated = service.tasks().patch(
        tasklist=tasklist_id, task=task_id, body={"status": "completed"}
    ).execute()
    return [types.TextContent(type="text", text=f"Task '{updated.get('title', task_id)}' marked as completed.")]


# ══════════════════════════════════════════════════════════════════════════════
# Google Contacts helpers (People API)
# ══════════════════════════════════════════════════════════════════════════════

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


async def _contacts_list(args: dict) -> list[types.TextContent]:
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


async def _contacts_search(args: dict) -> list[types.TextContent]:
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


# ── Run server ─────────────────────────────────────────────────────────────────

async def run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
