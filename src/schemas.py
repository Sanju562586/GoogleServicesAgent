"""
Tool Schemas
------------
Single source of truth for all MCP tool definitions:

  TOOL_INPUT_SCHEMAS  — full JSON Schema ``inputSchema`` dicts consumed by
                        google_mcp_server.py when registering tools with MCP.

  TOOL_COERCION_META  — lightweight coercion / validation metadata consumed by
                        agent.py to fill defaults and clamp integer values before
                        forwarding arguments to the MCP session.

Both dicts are keyed by the canonical tool name (e.g. ``"gmail_list_emails"``).
"""

from __future__ import annotations

# ── JSON Input Schemas (used by MCP list_tools) ────────────────────────────────

TOOL_INPUT_SCHEMAS: dict[str, dict] = {

    # ── Gmail ──────────────────────────────────────────────────────────────────

    "gmail_list_emails": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "max_results": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
                "description": "Number of emails to fetch (1–50).",
            },
            "label": {
                "type": "string",
                "default": "INBOX",
                "enum": ["INBOX", "SENT", "UNREAD", "SPAM", "TRASH", "STARRED", "IMPORTANT"],
                "description": "Gmail system label to filter by.",
            },
        },
    },

    "gmail_search_emails": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "Gmail search query string.",
            },
            "max_results": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": ["query"],
    },

    "gmail_get_email": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message_id": {
                "type": "string",
                "minLength": 1,
                "description": "The Gmail message ID.",
            },
        },
        "required": ["message_id"],
    },

    "gmail_send_email": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "to": {
                "type": "string",
                "minLength": 1,
                "description": "Recipient email address.",
            },
            "subject": {
                "type": "string",
                "minLength": 1,
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "minLength": 1,
                "description": "Plain-text email body.",
            },
            "cc": {
                "type": "string",
                "description": "Comma-separated CC addresses (optional).",
            },
        },
        "required": ["to", "subject", "body"],
    },

    "gmail_reply_email": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message_id": {
                "type": "string",
                "minLength": 1,
                "description": "The Gmail message ID to reply to.",
            },
            "body": {
                "type": "string",
                "minLength": 1,
                "description": "Plain-text reply body.",
            },
        },
        "required": ["message_id", "body"],
    },

    # ── Google Drive ───────────────────────────────────────────────────────────

    "drive_list_files": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 50,
            },
            "folder_id": {
                "type": "string",
                "description": "Folder ID to list contents of (optional). Use 'root' for the root folder.",
            },
        },
    },

    "drive_search_files": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Drive query string. Examples: "
                    "\"name contains 'budget'\", \"mimeType='application/pdf'\""
                ),
            },
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": ["query"],
    },

    "drive_get_file": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "file_id": {
                "type": "string",
                "minLength": 1,
                "description": "The Google Drive file ID.",
            },
        },
        "required": ["file_id"],
    },

    "drive_read_file": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "file_id": {
                "type": "string",
                "minLength": 1,
                "description": "The Google Drive file ID.",
            },
            "max_chars": {
                "type": "integer",
                "default": 4000,
                "minimum": 100,
                "maximum": 20000,
                "description": "Maximum characters to return.",
            },
        },
        "required": ["file_id"],
    },

    "drive_create_folder": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "description": "Name of the new folder.",
            },
            "parent_folder_id": {
                "type": "string",
                "description": "Parent folder ID (optional, defaults to root).",
            },
        },
        "required": ["name"],
    },

    # ── Google Calendar ────────────────────────────────────────────────────────

    "calendar_list_events": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "days_ahead": {
                "type": "integer",
                "default": 7,
                "minimum": 1,
                "maximum": 365,
                "description": "How many days ahead to look.",
            },
            "max_results": {
                "type": "integer",
                "default": 15,
                "minimum": 1,
                "maximum": 50,
            },
            "calendar_id": {
                "type": "string",
                "default": "primary",
                "description": "Calendar ID (default: 'primary').",
            },
        },
    },

    "calendar_search_events": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "Search keyword.",
            },
            "max_results": {
                "type": "integer",
                "default": 15,
                "minimum": 1,
                "maximum": 50,
            },
            "calendar_id": {
                "type": "string",
                "default": "primary",
            },
        },
        "required": ["query"],
    },

    "calendar_create_event": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "description": "Event title.",
            },
            "start": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
                "description": "Start datetime in IST ISO 8601, e.g. '2025-08-10T10:00:00+05:30'.",
            },
            "end": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
                "description": "End datetime in IST ISO 8601, e.g. '2025-08-10T11:00:00+05:30'.",
            },
            "description": {
                "type": "string",
                "description": "Optional event description.",
            },
            "location": {
                "type": "string",
                "description": "Optional event location.",
            },
            "attendees": {
                "type": "string",
                "description": "Comma-separated attendee email addresses (optional).",
            },
            "calendar_id": {
                "type": "string",
                "default": "primary",
            },
        },
        "required": ["title", "start", "end"],
    },

    "calendar_update_event": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_id": {
                "type": "string",
                "minLength": 1,
                "description": "Event ID to update (from calendar_list_events or calendar_search_events).",
            },
            "title": {
                "type": "string",
                "description": "New event title (optional).",
            },
            "start": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
                "description": "New start datetime in IST ISO 8601 (optional).",
            },
            "end": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
                "description": "New end datetime in IST ISO 8601 (optional).",
            },
            "description": {
                "type": "string",
                "description": "New description (optional).",
            },
            "location": {
                "type": "string",
                "description": "New location (optional).",
            },
            "calendar_id": {
                "type": "string",
                "default": "primary",
            },
        },
        "required": ["event_id"],
    },

    "calendar_delete_event": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_id": {
                "type": "string",
                "minLength": 1,
                "description": "The event ID to delete.",
            },
            "calendar_id": {
                "type": "string",
                "default": "primary",
            },
        },
        "required": ["event_id"],
    },

    # ── Google Photos ──────────────────────────────────────────────────────────

    "photos_list_albums": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 50,
            },
        },
    },

    "photos_list_photos": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "album_id": {
                "type": "string",
                "description": "Album ID to list photos from (optional, defaults to all photos).",
            },
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 50,
            },
        },
    },

    "photos_search_photos": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start_date": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
                "description": "Start date in YYYY-MM-DD format (optional).",
            },
            "end_date": {
                "type": "string",
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
                "description": "End date in YYYY-MM-DD format (optional).",
            },
            "category": {
                "type": "string",
                "enum": [
                    "LANDSCAPES", "SELFIES", "ANIMALS", "FOOD",
                    "TRAVEL", "WEDDINGS", "BIRTHDAYS",
                ],
                "description": "Content category filter (optional).",
            },
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 50,
            },
        },
    },

    # ── Google Tasks ───────────────────────────────────────────────────────────

    "tasks_list_tasklists": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },

    "tasks_list_tasks": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tasklist_id": {
                "type": "string",
                "default": "@default",
                "description": "Task list ID (default: '@default').",
            },
            "show_completed": {
                "type": "boolean",
                "default": False,
                "description": "Include completed tasks (default: false).",
            },
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 100,
            },
        },
    },

    "tasks_create_task": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "description": "Task title.",
            },
            "notes": {
                "type": "string",
                "description": "Optional task notes.",
            },
            "due": {
                "type": "string",
                "description": "Due date in IST ISO 8601 format, e.g. '2025-08-15T00:00:00+05:30' (optional).",
            },
            "tasklist_id": {
                "type": "string",
                "default": "@default",
            },
        },
        "required": ["title"],
    },

    "tasks_complete_task": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task_id": {
                "type": "string",
                "minLength": 1,
                "description": "Task ID to mark as completed.",
            },
            "tasklist_id": {
                "type": "string",
                "default": "@default",
            },
        },
        "required": ["task_id"],
    },

    # ── Google Contacts ────────────────────────────────────────────────────────

    "contacts_list": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 100,
            },
        },
    },

    "contacts_search": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "Name or email to search for.",
            },
        },
        "required": ["query"],
    },
}


# ── Agent-side coercion metadata (used by agent.py) ────────────────────────────
# Mirrors the key constraints in TOOL_INPUT_SCHEMAS but in a compact format
# that the agent uses to:
#   - fill ``defaults`` before forwarding args to MCP
#   - clamp ``integers`` to their (min, max) range
#   - reject calls missing ``required`` fields early (before the MCP round-trip)

TOOL_COERCION_META: dict[str, dict] = {
    # Gmail
    "gmail_list_emails": {
        "defaults": {"max_results": 10, "label": "INBOX"},
        "required": [],
        "integers": {"max_results": (1, 50)},
    },
    "gmail_search_emails": {
        "defaults": {"max_results": 10},
        "required": ["query"],
        "integers": {"max_results": (1, 50)},
    },
    "gmail_get_email": {
        "defaults": {},
        "required": ["message_id"],
        "integers": {},
    },
    "gmail_send_email": {
        "defaults": {},
        "required": ["to", "subject", "body"],
        "integers": {},
    },
    "gmail_reply_email": {
        "defaults": {},
        "required": ["message_id", "body"],
        "integers": {},
    },
    # Drive
    "drive_list_files": {
        "defaults": {"max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 50)},
    },
    "drive_search_files": {
        "defaults": {"max_results": 20},
        "required": ["query"],
        "integers": {"max_results": (1, 50)},
    },
    "drive_get_file": {
        "defaults": {},
        "required": ["file_id"],
        "integers": {},
    },
    "drive_read_file": {
        "defaults": {"max_chars": 4000},
        "required": ["file_id"],
        "integers": {"max_chars": (100, 20000)},
    },
    "drive_create_folder": {
        "defaults": {},
        "required": ["name"],
        "integers": {},
    },
    # Calendar
    "calendar_list_events": {
        "defaults": {"days_ahead": 7, "max_results": 15, "calendar_id": "primary"},
        "required": [],
        "integers": {"days_ahead": (1, 365), "max_results": (1, 50)},
    },
    "calendar_search_events": {
        "defaults": {"max_results": 15, "calendar_id": "primary"},
        "required": ["query"],
        "integers": {"max_results": (1, 50)},
    },
    "calendar_create_event": {
        "defaults": {"calendar_id": "primary"},
        "required": ["title", "start", "end"],
        "integers": {},
    },
    "calendar_update_event": {
        "defaults": {"calendar_id": "primary"},
        "required": ["event_id"],
        "integers": {},
    },
    "calendar_delete_event": {
        "defaults": {"calendar_id": "primary"},
        "required": ["event_id"],
        "integers": {},
    },
    # Photos
    "photos_list_albums": {
        "defaults": {"max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 50)},
    },
    "photos_list_photos": {
        "defaults": {"max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 50)},
    },
    "photos_search_photos": {
        "defaults": {"max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 50)},
    },
    # Tasks
    "tasks_list_tasklists": {
        "defaults": {},
        "required": [],
        "integers": {},
    },
    "tasks_list_tasks": {
        "defaults": {"tasklist_id": "@default", "show_completed": False, "max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 100)},
    },
    "tasks_create_task": {
        "defaults": {"tasklist_id": "@default"},
        "required": ["title"],
        "integers": {},
    },
    "tasks_complete_task": {
        "defaults": {"tasklist_id": "@default"},
        "required": ["task_id"],
        "integers": {},
    },
    # Contacts
    "contacts_list": {
        "defaults": {"max_results": 20},
        "required": [],
        "integers": {"max_results": (1, 100)},
    },
    "contacts_search": {
        "defaults": {},
        "required": ["query"],
        "integers": {},
    },
}
