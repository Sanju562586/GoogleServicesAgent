"""
Google Calendar Tool Handlers
------------------------------
Exposes 5 Calendar MCP tools:
  calendar_list_events, calendar_search_events, calendar_create_event,
  calendar_update_event, calendar_delete_event

IST datetime helpers are also defined here and exported for reuse.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from mcp import types

from src.gmail_auth import get_calendar_service
from src.schemas import TOOL_INPUT_SCHEMAS

# IST offset constant (UTC+05:30)
_IST = timezone(timedelta(hours=5, minutes=30))

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="calendar_list_events",
        description="List upcoming calendar events within a time window.",
        inputSchema=TOOL_INPUT_SCHEMAS["calendar_list_events"],
    ),
    types.Tool(
        name="calendar_search_events",
        description="Search calendar events by keyword in title or description.",
        inputSchema=TOOL_INPUT_SCHEMAS["calendar_search_events"],
    ),
    types.Tool(
        name="calendar_create_event",
        description=(
            "Create a new event on Google Calendar. "
            "Always provide start and end times in IST (UTC+05:30) using ISO 8601 format "
            "e.g. '2025-08-10T10:00:00+05:30'."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["calendar_create_event"],
    ),
    types.Tool(
        name="calendar_update_event",
        description=(
            "Update an existing calendar event's title, start time, end time, "
            "description, or location. Always use IST (UTC+05:30) for times."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["calendar_update_event"],
    ),
    types.Tool(
        name="calendar_delete_event",
        description="Delete a calendar event by its event ID.",
        inputSchema=TOOL_INPUT_SCHEMAS["calendar_delete_event"],
    ),
]


# ── IST datetime helpers ───────────────────────────────────────────────────────

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
    """
    if not dt_str:
        return dt_str
    dt_str = dt_str.strip()
    try:
        # Date-only — add midnight IST
        if len(dt_str) == 10 and "T" not in dt_str:
            return f"{dt_str}T00:00:00+05:30"

        # Already correct IST — return as-is
        if dt_str.endswith("+05:30"):
            return dt_str

        # Strip any timezone suffix to get the bare local datetime string.
        bare = dt_str
        for suffix in ("+00:00", "+05:00", "+05:30", "-05:30", "-08:00"):
            if bare.endswith(suffix):
                bare = bare[: -len(suffix)]
                break
        bare = bare.rstrip("Z")

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
    print(f"[CALENDAR DEBUG] {label}: '{dt_str}'", file=sys.stderr, flush=True)


def _shift_ist_hours(dt_str: str, hours: float = 5.5) -> str:
    """
    Shift a normalized IST datetime string by ``hours``.
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
        return dt_shifted.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except Exception:
        return dt_str  # fallback: return unchanged


def _to_ist_display(dt_val: str | None) -> str:
    """Convert any datetime string (UTC/ISO/bare) to a human-readable IST string."""
    if not dt_val:
        return ""
    try:
        normalised = dt_val.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalised)
        ist_dt = dt.astimezone(_IST)
        return ist_dt.strftime("%I:%M %p IST, %a %d %b %Y")  # e.g. "02:00 PM IST, Mon 03 Aug 2026"
    except Exception:
        return dt_val  # fallback: return raw


def _to_ist_iso(dt_val: str | None) -> str:
    """Return a clean ISO 8601 string with +05:30 offset from any input datetime."""
    if not dt_val:
        return ""
    try:
        normalised = dt_val.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalised)
        ist_dt = dt.astimezone(_IST)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except Exception:
        return dt_val


def _format_event(e: dict) -> dict:
    raw_start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
    raw_end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date")
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


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _calendar_list_events(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_calendar_service()
    days = max(1, min(int(args.get("days_ahead", 7)), 365))
    max_results = max(1, min(int(args.get("max_results", 15)), 50))
    cal_id = args.get("calendar_id", "primary") or "primary"
    # Google Calendar API requires strict RFC 3339 with 'Z' suffix.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _fetch():
        result = service.events().list(
            calendarId=cal_id, timeMin=now, timeMax=end,
            maxResults=max_results, singleEvents=True, orderBy="startTime"
        ).execute()
        return result.get("items", [])

    events = await asyncio.to_thread(_fetch)
    if not events:
        return [types.TextContent(type="text", text=f"No events in the next {days} day(s).")]
    return [types.TextContent(type="text", text=json.dumps([_format_event(e) for e in events], indent=2))]


async def _calendar_search_events(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_calendar_service()
    max_results = min(args.get("max_results", 15), 50)
    cal_id = args.get("calendar_id", "primary")
    # timeMin is required by Google Calendar API when orderBy="startTime" + singleEvents=True.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _fetch():
        result = service.events().list(
            calendarId=cal_id, q=args["query"], timeMin=now,
            maxResults=max_results, singleEvents=True, orderBy="startTime"
        ).execute()
        return result.get("items", [])

    events = await asyncio.to_thread(_fetch)
    if not events:
        return [types.TextContent(type="text", text="No matching events found.")]
    return [types.TextContent(type="text", text=json.dumps([_format_event(e) for e in events], indent=2))]


async def _calendar_create_event(args: dict[str, Any]) -> list[types.TextContent]:
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
    end_str = _shift_ist_hours(end_str)

    # Fallback: if end is still missing/invalid, default to 1 hour after start.
    if not end_str:
        try:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = start_dt + timedelta(hours=1)
            end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
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

    def _insert():
        return service.events().insert(calendarId=cal_id, body=body).execute()

    event = await asyncio.to_thread(_insert)
    # Readable confirmation in IST — using _to_ist_display on the RESPONSE
    # so even if Google normalises the stored time, we show the correct IST value.
    resp_start = event.get("start", {}).get("dateTime", start_str)
    resp_end = event.get("end", {}).get("dateTime", end_str)
    return [types.TextContent(type="text", text=(
        f"✅ Event created: **{event['summary']}**\n"
        f"🕐 Start : {_to_ist_display(resp_start)}\n"
        f"🕑 End   : {_to_ist_display(resp_end)}\n"
        f"🔗 Link  : {event.get('htmlLink', '')}"
    ))]


async def _calendar_delete_event(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_calendar_service()
    cal_id = args.get("calendar_id", "primary")
    event_id = args["event_id"]

    def _delete():
        service.events().delete(calendarId=cal_id, eventId=event_id).execute()

    await asyncio.to_thread(_delete)
    return [types.TextContent(type="text", text=f"Event {event_id} deleted.")]


async def _calendar_update_event(args: dict[str, Any]) -> list[types.TextContent]:
    """Patch an existing calendar event with updated fields."""
    service = get_calendar_service()
    cal_id = args.get("calendar_id", "primary")
    event_id = args["event_id"]

    # Fetch the current event to preserve unchanged fields
    def _get():
        return service.events().get(calendarId=cal_id, eventId=event_id).execute()

    existing = await asyncio.to_thread(_get)
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
        return [types.TextContent(type="text", text=(
            "No changes provided. Please specify title, start, end, description, or location."
        ))]

    def _patch():
        return service.events().patch(calendarId=cal_id, eventId=event_id, body=patch).execute()

    updated = await asyncio.to_thread(_patch)
    return [types.TextContent(type="text", text=(
        f"✅ Event updated: **{updated.get('summary', event_id)}**\n"
        f"🕐 Start: {_to_ist_display(start_str)}\n"
        f"🕑 End:   {_to_ist_display(end_str)}\n"
        f"🔗 Link: {updated.get('htmlLink', '')}"
    ))]


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "calendar_list_events": _calendar_list_events,
    "calendar_search_events": _calendar_search_events,
    "calendar_create_event": _calendar_create_event,
    "calendar_update_event": _calendar_update_event,
    "calendar_delete_event": _calendar_delete_event,
}
