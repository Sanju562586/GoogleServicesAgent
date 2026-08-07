"""
Gmail Tool Handlers
--------------------
Exposes 5 Gmail MCP tools:
  gmail_list_emails, gmail_search_emails, gmail_get_email,
  gmail_send_email, gmail_reply_email
"""

from __future__ import annotations

import base64
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable

from mcp import types

from src.gmail_auth import get_gmail_service
from src.schemas import TOOL_INPUT_SCHEMAS

# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS: list[types.Tool] = [
    types.Tool(
        name="gmail_list_emails",
        description=(
            "List recent emails from Gmail inbox or a specific label. "
            "Use when asked to show, list, or check recent emails."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["gmail_list_emails"],
    ),
    types.Tool(
        name="gmail_search_emails",
        description=(
            "Search Gmail emails using query syntax "
            "(e.g. 'from:boss@company.com', 'is:unread', 'subject:invoice', 'newer_than:1d')."
        ),
        inputSchema=TOOL_INPUT_SCHEMAS["gmail_search_emails"],
    ),
    types.Tool(
        name="gmail_get_email",
        description="Read the full body and details of a single Gmail email by its message ID.",
        inputSchema=TOOL_INPUT_SCHEMAS["gmail_get_email"],
    ),
    types.Tool(
        name="gmail_send_email",
        description="Send a new email via Gmail.",
        inputSchema=TOOL_INPUT_SCHEMAS["gmail_send_email"],
    ),
    types.Tool(
        name="gmail_reply_email",
        description="Reply to an existing Gmail email thread by message ID.",
        inputSchema=TOOL_INPUT_SCHEMAS["gmail_reply_email"],
    ),
]


# ── Private helpers ────────────────────────────────────────────────────────────

def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit] + "…" if len(text) > limit else text


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
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


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _gmail_list_emails(args: dict[str, Any]) -> list[types.TextContent]:
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


async def _gmail_search_emails(args: dict[str, Any]) -> list[types.TextContent]:
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


async def _gmail_get_email(args: dict[str, Any]) -> list[types.TextContent]:
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


async def _gmail_send_email(args: dict[str, Any]) -> list[types.TextContent]:
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


async def _gmail_reply_email(args: dict[str, Any]) -> list[types.TextContent]:
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


# ── Handler registry ───────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable] = {
    "gmail_list_emails": _gmail_list_emails,
    "gmail_search_emails": _gmail_search_emails,
    "gmail_get_email": _gmail_get_email,
    "gmail_send_email": _gmail_send_email,
    "gmail_reply_email": _gmail_reply_email,
}
