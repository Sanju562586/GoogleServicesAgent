"""
Google Services Groq Agent
---------------------------
Orchestrates:
  1. Spawning the unified Google MCP server as a subprocess
  2. Connecting to it via the MCP client
  3. Forwarding all Google tools to Groq's tool-calling API
  4. Running a multi-turn conversation loop with fallback parsing
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from groq import Groq, BadRequestError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from BASE_DIR if it exists
load_dotenv(BASE_DIR / ".env")

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

SYSTEM_PROMPT = """You are a powerful personal AI assistant with LIVE access to all the user's Google services via MCP tools.

You have the following tools available:

GMAIL: gmail_list_emails, gmail_search_emails, gmail_get_email, gmail_send_email, gmail_reply_email
GOOGLE DRIVE: drive_list_files, drive_search_files, drive_get_file, drive_read_file, drive_create_folder
GOOGLE CALENDAR: calendar_list_events, calendar_search_events, calendar_create_event, calendar_delete_event
GOOGLE PHOTOS: photos_list_albums, photos_list_photos, photos_search_photos
GOOGLE MAPS: maps_search_places, maps_geocode, maps_get_directions, maps_place_details
GOOGLE TASKS: tasks_list_tasklists, tasks_list_tasks, tasks_create_task, tasks_complete_task
GOOGLE CONTACTS: contacts_list, contacts_search

CRITICAL RULES:
1. You ALREADY HAVE active live access to all these services — NEVER say you cannot access them.
2. Always call the appropriate tool immediately when the user asks about emails, files, events, photos, places, tasks, or contacts.
3. For emails: use gmail_search_emails with queries like 'newer_than:1d' for recent emails.
4. For Maps: if GOOGLE_MAPS_API_KEY is not set, inform the user how to add it.
5. Always ask for confirmation before sending emails, creating/deleting calendar events, or creating tasks.
6. Present results clearly and concisely.
"""


class GmailGroqAgent:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "gsk_your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY environment variable is missing or using placeholder value.\n"
                "Please set a valid GROQ_API_KEY in your .env file."
            )
        self.groq = Groq(api_key=api_key)
        self.history: list[dict] = []
        self._mcp_session: ClientSession | None = None
        self._tools: list[dict] = []
        self._client_cm = None
        self._session_cm = None

    # ── Setup ──────────────────────────────────────────────────────────────────

    async def setup(self):
        """Start unified Google MCP server and load all available tools."""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.google_mcp_server"],
            cwd=str(BASE_DIR),
            env={**os.environ},
        )

        self._client_cm = stdio_client(server_params)
        read, write = await self._client_cm.__aenter__()

        self._session_cm = ClientSession(read, write)
        self._mcp_session = await self._session_cm.__aenter__()
        await self._mcp_session.initialize()

        mcp_tools = await self._mcp_session.list_tools()
        self._tools = [_mcp_to_groq_tool(t) for t in mcp_tools.tools]
        print(f"✅ Connected to Google MCP ({len(self._tools)} tools loaded)")
        print("   Services: Gmail · Drive · Calendar · Photos · Maps · Tasks · Contacts")

    # ── Teardown ───────────────────────────────────────────────────────────────

    async def close(self):
        """Clean up MCP session and subprocess."""
        if self._session_cm:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_cm = None

        if self._client_cm:
            try:
                await self._client_cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._client_cm = None

    # ── Chat ───────────────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        while True:
            try:
                response = self.groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.history,
                    tools=self._tools,
                    tool_choice="auto",
                )

                message = response.choices[0].message

                # No tool call → final answer
                if not message.tool_calls:
                    text = message.content or ""
                    self.history.append({"role": "assistant", "content": text})
                    return text

                # Append assistant message with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                })

                # Execute each tool call via MCP
                for tc in message.tool_calls:
                    result = await self._call_mcp_tool(
                        tc.function.name,
                        json.loads(tc.function.arguments),
                    )
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            except Exception as e:
                # Handle Groq's tool_use_failed error by recovering from failed_generation
                failed_call = _parse_failed_generation(e)
                if failed_call:
                    func_name, func_args = failed_call
                    tool_call_id = f"call_{len(self.history)}"
                    self.history.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": func_name,
                                    "arguments": json.dumps(func_args),
                                },
                            }
                        ],
                    })
                    result = await self._call_mcp_tool(func_name, func_args)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    })
                    continue
                else:
                    raise e

    # ── MCP tool execution ─────────────────────────────────────────────────────

    async def _call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if not self._mcp_session:
            raise RuntimeError("MCP session is not initialized.")
        result = await self._mcp_session.call_tool(name, arguments)
        parts = [c.text for c in result.content if hasattr(c, "text")]
        return "\n".join(parts) if parts else "(no result)"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mcp_to_groq_tool(tool) -> dict:
    """Convert an MCP Tool object to Groq's function-calling format."""
    schema = tool.inputSchema or {"type": "object", "properties": {}}
    if isinstance(schema, dict) and "type" not in schema:
        schema["type"] = "object"
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        },
    }


def _parse_failed_generation(e: Exception) -> tuple[str, dict] | None:
    """Extract tool name and args if Groq API throws a tool_use_failed 400 error."""
    text = ""
    if hasattr(e, "body") and isinstance(e.body, dict):
        text = str(e.body.get("error", {}).get("failed_generation", ""))
    if not text:
        text = str(e)

    patterns = [
        r"<function=(\w+)[=\s(]*({.*?})?\)?</function>",
        r"<function=(\w+)[=>\s]*({.*?})</function>",
        r"(\w+)\s*\(\s*({.*?})\s*\)",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.DOTALL)
        if match:
            func_name = match.group(1)
            raw_args = match.group(2)
            # Unescape escaped single quotes that Groq sometimes generates
            raw_args = raw_args.replace("\\'" , "'")
            try:
                func_args = json.loads(raw_args)
                return func_name, func_args
            except json.JSONDecodeError:
                # Last resort: use regex to extract key fields individually
                try:
                    import ast
                    func_args = ast.literal_eval(raw_args)
                    return func_name, func_args
                except Exception:
                    continue
    return None
