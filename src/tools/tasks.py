"""
Google Tasks Tool Handlers
---------------------------
Exposes 4 Tasks MCP tools:
  tasks_list_tasklists, tasks_list_tasks,
  tasks_create_task, tasks_complete_task
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from mcp import types

from src.gmail_auth import get_tasks_service
from src.schemas import TOOL_INPUT_SCHEMAS

# IST offset constant (UTC+05:30)
_IST = timezone(timedelta(hours=5, minutes=30))

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="tasks_list_tasklists",
        description="List all Google Tasks task lists.",
        inputSchema=TOOL_INPUT_SCHEMAS["tasks_list_tasklists"],
    ),
    types.Tool(
        name="tasks_list_tasks",
        description="List tasks in a specific task list (defaults to '@default').",
        inputSchema=TOOL_INPUT_SCHEMAS["tasks_list_tasks"],
    ),
    types.Tool(
        name="tasks_create_task",
        description=(
            "Create a new task in Google Tasks. "
            "For the due date, use IST ISO 8601 format e.g. '2025-08-15T00:00:00+05:30'."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["tasks_create_task"],
    ),
    types.Tool(
        name="tasks_complete_task",
        description="Mark a Google Task as completed.",
        inputSchema=TOOL_INPUT_SCHEMAS["tasks_complete_task"],
    ),
]


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _tasks_list_tasklists(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_tasks_service()
    result = service.tasklists().list(maxResults=20).execute()
    lists = result.get("items", [])
    if not lists:
        return [types.TextContent(type="text", text="No task lists found.")]
    return [types.TextContent(type="text", text=json.dumps(
        [{"id": l["id"], "title": l["title"]} for l in lists], indent=2
    ))]


async def _tasks_list_tasks(args: dict[str, Any]) -> list[types.TextContent]:
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
    formatted = [
        {
            "id": t["id"],
            "title": t.get("title"),
            "status": t.get("status"),
            "due": t.get("due"),
            "notes": t.get("notes", ""),
        }
        for t in tasks
    ]
    return [types.TextContent(type="text", text=json.dumps(formatted, indent=2))]


async def _tasks_create_task(args: dict[str, Any]) -> list[types.TextContent]:
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
            if due_str.endswith("Z") or due_str.endswith("+00:00"):
                # Already UTC — keep as-is, just ensure Z suffix
                due_normalized = due_str.replace("+00:00", "Z")
                if not due_normalized.endswith("Z"):
                    due_normalized += "Z"
            else:
                # Parse as IST (or whatever offset is present) and convert to UTC
                ist_dt = datetime.fromisoformat(
                    due_str if ("+" in due_str[10:] or due_str.count("-") > 3)
                    else due_str + "+05:30"
                )
                utc_dt = ist_dt.astimezone(timezone.utc)
                due_normalized = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            # Fallback: pass as-is and let Google API validate
            due_normalized = due_str
        body["due"] = due_normalized
    task = service.tasks().insert(tasklist=tasklist_id, body=body).execute()
    # Show the due date in IST for user-friendly confirmation
    due_display = ""
    if task.get("due"):
        try:
            utc_due = datetime.fromisoformat(task["due"].replace("Z", "+00:00"))
            ist_due = utc_due.astimezone(_IST)
            due_display = f"\n📅 Due: {ist_due.strftime('%A, %d %B %Y')}"
        except Exception:
            due_display = f"\n📅 Due: {task['due']}"
    return [types.TextContent(type="text", text=f"✅ Task created: '{task['title']}' (ID: {task['id']}){due_display}")]


async def _tasks_complete_task(args: dict[str, Any]) -> list[types.TextContent]:
    service = get_tasks_service()
    tasklist_id = args.get("tasklist_id", "@default") or "@default"
    # Use patch() with only the status field — sending full task body via update()
    # causes 400 errors because read-only fields (etag, selfLink, kind) are rejected.
    task_id = args["task_id"]
    updated = service.tasks().patch(
        tasklist=tasklist_id, task=task_id, body={"status": "completed"}
    ).execute()
    return [types.TextContent(type="text", text=f"Task '{updated.get('title', task_id)}' marked as completed.")]


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "tasks_list_tasklists": _tasks_list_tasklists,
    "tasks_list_tasks": _tasks_list_tasks,
    "tasks_create_task": _tasks_create_task,
    "tasks_complete_task": _tasks_complete_task,
}
