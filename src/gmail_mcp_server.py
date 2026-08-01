"""
Gmail MCP Server
----------------
Exposes Gmail operations as MCP tools:
  - list_emails    : Fetch recent emails from inbox
  - search_emails  : Search emails by query string
  - get_email      : Get full content of a single email
  - send_email     : Send a new email
  - reply_email    : Reply to an existing email
"""

import json
import base64
import asyncio
from typing import Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from src.gmail_auth import get_gmail_service


# ── MCP Server setup ───────────────────────────────────────────────────────────

app = Server("gmail-mcp")


def _snippet(text: str, limit: int = 200) -> str:
    return text[:limit] + "…" if len(text) > limit else text


# ── Tool definitions ───────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_emails",
            description="Fetch and list recent emails from Gmail inbox or specified label. Use this tool whenever asked to show, list, check, explain, or get recent emails.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Number of emails to fetch (default 10, max 50).",
                        "default": 10,
                    },
                    "label": {
                        "type": "string",
                        "description": "Gmail label to filter by (e.g. INBOX, SENT, SPAM, UNREAD).",
                        "default": "INBOX",
                    },
                },
            },
        ),
        types.Tool(
            name="search_emails",
            description="Search Gmail emails using query filters (e.g. 'is:unread', 'from:boss@company.com', 'subject:report').",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query, e.g. 'from:boss@company.com subject:report'.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 10).",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_email",
            description="Get the full body content, sender, recipient, and details of a single email by its message ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The Gmail message ID.",
                    }
                },
                "required": ["message_id"],
            },
        ),
        types.Tool(
            name="send_email",
            description="Send a new email to a recipient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string", "description": "Email subject."},
                    "body": {"type": "string", "description": "Plain-text email body."},
                    "cc": {"type": "string", "description": "CC addresses (comma-separated, optional)."},
                },
                "required": ["to", "subject", "body"],
            },
        ),
        types.Tool(
            name="reply_email",
            description="Reply to an existing email by message ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "ID of the email to reply to."},
                    "body": {"type": "string", "description": "Reply body text."},
                },
                "required": ["message_id", "body"],
            },
        ),
    ]


# ── Tool handlers ──────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        service = get_gmail_service()
    except Exception as e:
        return [types.TextContent(type="text", text=f"Gmail Auth Error: {e}")]

    try:
        if name == "list_emails":
            return await _list_emails(service, arguments)
        elif name == "search_emails":
            return await _search_emails(service, arguments)
        elif name == "get_email":
            return await _get_email(service, arguments)
        elif name == "send_email":
            return await _send_email(service, arguments)
        elif name == "reply_email":
            return await _reply_email(service, arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing {name}: {e}")]


# ── Gmail helpers ──────────────────────────────────────────────────────────────

def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
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


def _format_message(msg: dict) -> dict:
    headers = _parse_headers(msg["payload"]["headers"])
    return {
        "id": msg["id"],
        "from": headers.get("From", headers.get("from", "")),
        "to": headers.get("To", headers.get("to", "")),
        "subject": headers.get("Subject", headers.get("subject", "(no subject)")),
        "date": headers.get("Date", headers.get("date", "")),
        "snippet": msg.get("snippet", ""),
    }


async def _list_emails(service, args: dict) -> list[types.TextContent]:
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
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        emails.append(_format_message(msg))

    return [types.TextContent(type="text", text=json.dumps(emails, indent=2))]


async def _search_emails(service, args: dict) -> list[types.TextContent]:
    query = args["query"]
    max_results = min(args.get("max_results", 10), 50)

    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = result.get("messages", [])
    if not messages:
        return [types.TextContent(type="text", text=f"No emails found for query: {query}")]

    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()
        emails.append(_format_message(msg))

    return [types.TextContent(type="text", text=json.dumps(emails, indent=2))]


async def _get_email(service, args: dict) -> list[types.TextContent]:
    msg = service.users().messages().get(
        userId="me", id=args["message_id"], format="full"
    ).execute()

    headers = _parse_headers(msg["payload"]["headers"])
    body = _extract_body(msg["payload"])

    email = {
        "id": msg["id"],
        "from": headers.get("From", headers.get("from", "")),
        "to": headers.get("To", headers.get("to", "")),
        "subject": headers.get("Subject", headers.get("subject", "(no subject)")),
        "date": headers.get("Date", headers.get("date", "")),
        "body": body or msg.get("snippet", ""),
    }
    return [types.TextContent(type="text", text=json.dumps(email, indent=2))]


async def _send_email(service, args: dict) -> list[types.TextContent]:
    msg = MIMEMultipart()
    msg["to"] = args["to"]
    msg["subject"] = args["subject"]
    if args.get("cc"):
        msg["cc"] = args["cc"]
    msg.attach(MIMEText(args["body"], "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    return [types.TextContent(type="text", text=f"Email sent! Message ID: {sent['id']}")]


async def _reply_email(service, args: dict) -> list[types.TextContent]:
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


# ── Run server ─────────────────────────────────────────────────────────────────

async def run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
