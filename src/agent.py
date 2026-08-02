"""
Google Services Groq Agent
---------------------------
Orchestrates:
  1. Spawning the unified Google MCP server as a subprocess
  2. Connecting to it via the MCP client
  3. Forwarding all Google tools to Groq's tool-calling API
  4. Running a multi-turn conversation loop with fallback parsing
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from groq import Groq, BadRequestError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


def _current_time_context() -> str:
    """Return a string describing the current IST time for injection into system prompts."""
    now = datetime.now(IST)
    return (
        f"CURRENT DATE & TIME (user's local time, IST / UTC+05:30): "
        f"{now.strftime('%A, %d %B %Y %I:%M %p')} "
        f"| ISO 8601: {now.strftime('%Y-%m-%dT%H:%M:%S+05:30')}"
    )

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from BASE_DIR if it exists
load_dotenv(BASE_DIR / ".env")

# Fallback models in case primary model hits rate limit (429).
# Keep only ACTIVE Groq models — decommissioned ones cause silent failures.
FALLBACK_MODELS = [
    os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "llama-3.1-8b-instant",  # Fast small model — excellent tool-calling
    "gemma2-9b-it",          # Google Gemma 2 — reliable fallback
    "llama3-70b-8192",       # Meta Llama 3 70B — active and capable
]

# Maximum number of history turns kept to avoid context-window overflow.
# Each turn = 1 user + 1 assistant (or tool) message pair.
MAX_HISTORY_MESSAGES = 40  # ~20 turns

SYSTEM_PROMPT_TEMPLATE = """You are a powerful personal AI assistant with LIVE access to all the user's Google services via MCP tools.

{time_context}

You have the following tools available:

GMAIL: gmail_list_emails, gmail_search_emails, gmail_get_email, gmail_send_email, gmail_reply_email
GOOGLE DRIVE: drive_list_files, drive_search_files, drive_get_file, drive_read_file, drive_create_folder
GOOGLE CALENDAR: calendar_list_events, calendar_search_events, calendar_create_event, calendar_delete_event
GOOGLE PHOTOS: photos_list_albums, photos_list_photos, photos_search_photos
GOOGLE TASKS: tasks_list_tasklists, tasks_list_tasks, tasks_create_task, tasks_complete_task
GOOGLE CONTACTS: contacts_list, contacts_search

CRITICAL RULES — YOU MUST FOLLOW THESE WITHOUT EXCEPTION:
1. You ALREADY HAVE active live access to all these services via tools — NEVER say you cannot access them or ask the user to run terminal commands to authenticate.
2. ALWAYS call the appropriate tool FIRST before composing any reply. NEVER answer from memory or training data.
3. For ANY email question (e.g. summarize last email, check inbox): call gmail_list_emails or gmail_search_emails IMMEDIATELY.
4. For ANY calendar question: call calendar_list_events or calendar_search_events IMMEDIATELY.
5. For ANY Drive/Tasks/Contacts/Photos question: call the matching tool IMMEDIATELY.
6. NEVER fabricate tool results. If a tool returns an error, explain the error clearly to the user.
7. Always ask for confirmation before sending emails, creating/deleting calendar events, or creating tasks.
8. Present results clearly, concisely, and beautifully formatted in markdown.

TIME & TIMEZONE RULES (CRITICAL — follow for ALL calendar/task operations):
- The user is in IST (India Standard Time, UTC+05:30). Always use +05:30 as the timezone offset.
- When the user says a time like '3 PM', '10 AM', 'tomorrow at 6', always convert it to a full ISO 8601 string: YYYY-MM-DDTHH:MM:SS+05:30.
- 'Today' = the current date shown above. 'Tomorrow' = current date + 1 day.
- NEVER use UTC (Z suffix) for calendar event start/end times — always use +05:30.
- For Google Tasks 'due' field, use YYYY-MM-DDTHH:MM:SS+05:30 format (the time part will be treated as midnight locally).
- If the user does not specify an end time for a calendar event, default the event duration to 1 hour.
- ALWAYS confirm the exact date and time you understood before creating a calendar event or task.
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
        print("   Services: Gmail · Drive · Calendar · Photos · Tasks · Contacts")

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

        # Trim history to avoid context-window overflow.
        # Always keep an even number of messages so we never cut mid tool-call/result pair.
        if len(self.history) > MAX_HISTORY_MESSAGES:
            trim_to = MAX_HISTORY_MESSAGES - (MAX_HISTORY_MESSAGES % 2)
            self.history = self.history[-trim_to:]

        while True:
            response = None
            last_err = None
            # FIX #1: Track whether we successfully recovered from a failed
            # generation so the outer while-loop can continue without re-raising.
            recovered = False

            for model_name in FALLBACK_MODELS:
                try:
                    # Inject fresh current time on every LLM call so the model
                    # always has the exact current IST datetime — critical for
                    # correct calendar event and task due-date construction.
                    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                        time_context=_current_time_context()
                    )
                    response = self.groq.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "system", "content": system_prompt}] + self.history,
                        tools=self._tools,
                        tool_choice="auto",
                    )
                    break
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    # Skip decommissioned models silently — no point retrying them.
                    if "model_decommissioned" in err_str or "decommissioned" in err_str or "404" in err_str:
                        print(f"⚠️ Model {model_name} is invalid or decommissioned. Skipping...")
                        continue
                    if "429" in err_str or "rate_limit_exceeded" in err_str:
                        print(f"⚠️ Model {model_name} rate limited. Trying fallback model...")
                        await asyncio.sleep(1)  # Brief pause before trying next model
                        continue
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
                        # Mark as recovered so outer loop continues instead of raising.
                        recovered = True
                        break
                    else:
                        raise e

            # FIX #1: If we recovered from a failed generation, continue the
            # outer loop to let the model produce a final answer from the tool
            # result we just appended — do NOT raise last_err.
            if recovered:
                continue

            if response is None:
                if last_err:
                    raise last_err
                raise RuntimeError("Failed to get response from Groq.")

            message = response.choices[0].message

            # Check if model returned no tool_calls, but output text contains a tool call tag
            if not message.tool_calls:
                text = message.content or ""
                text_tool_call = _parse_text_tool_call(text)
                if text_tool_call:
                    func_name, func_args = text_tool_call
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
                # FIX #5: Guard against empty/null arguments from Groq.
                raw_args = tc.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}
                result = await self._call_mcp_tool(tc.function.name, parsed_args)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

    # ── MCP tool execution ─────────────────────────────────────────────────────

    async def _call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if not self._mcp_session:
            raise RuntimeError("MCP session is not initialized.")
        try:
            result = await self._mcp_session.call_tool(name, arguments)
            parts = [c.text for c in result.content if hasattr(c, "text")]
            return "\n".join(parts) if parts else "(no result)"
        except Exception as e:
            return f"Tool error ({name}): {e}"


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


def _parse_text_tool_call(text: str) -> tuple[str, dict] | None:
    """Extract tool name and args from text-encoded tool calls emitted in assistant messages.

    Handles formats like:
      - <|python_tag|>gmail_list_emails{"label": "INBOX", "max_results": 1}
      - <|python_tag|>gmail_list_emails({"label": "INBOX", "max_results": 1})
      - <function=gmail_list_emails>{"label": "INBOX"}</function>
      - [TOOL_CALLS] [{"name": "gmail_list_emails", "arguments": {...}}]
      - {"name": "gmail_list_emails", "arguments": {...}}
      - gmail_list_emails({"label": "INBOX"})
    """
    if not text:
        return None

    patterns = [
        # <|python_tag|>func_name{"arg": val} or <|python_tag|>func_name({"arg": val})
        r'<\|python_tag\|>\s*(\w+)\s*(?:(?:\((.*?)\))|(\{.*?\}))',
        # <function=func_name ...>...</function>
        r'<function=(\w+)\s+"(.*?)">\s*</function>',
        r"<function=(\w+)\s+'(.*?)'>\s*</function>",
        r"<function=(\w+)\s+\[(\{.*?\})\]>?\s*</function>",
        r"<function=(\w+)\s+(\{.*?\})>\s*</function>",
        r"<function=(\w+)>(\{.*?\})</function>",
        r"<function=(\w+)[=>\s]+(\{.*?\})",
        # [TOOL_CALLS] [{"name": "...", "arguments": {...}}]
        r'\[TOOL_CALLS\]\s*\[?\s*\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
        # {"name": "func_name", "arguments": {...}}
        r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
        # func_name({"arg": val})
        r'(\w+)\s*\(\s*(\{.*?\})\s*\)',
    ]

    for pat in patterns:
        match = re.search(pat, text, re.DOTALL)
        if match:
            func_name = match.group(1)
            raw_args = None
            for g in match.groups()[1:]:
                if g is not None and g.strip():
                    raw_args = g.strip()
                    break
            if not raw_args:
                raw_args = "{}"

            raw_args = raw_args.replace('\\"', '"').replace("\\'", "'")
            raw_args = raw_args.strip('"').strip("'")
            try:
                func_args = json.loads(raw_args)
                return func_name, func_args
            except json.JSONDecodeError:
                try:
                    import ast
                    func_args = ast.literal_eval(raw_args)
                    return func_name, func_args
                except Exception:
                    continue
    return None


def _parse_failed_generation(e: Exception) -> tuple[str, dict] | None:
    """Extract tool name and args from Groq's tool_use_failed 400 errors.

    Handles all known malformed formats Groq can emit:
      - <function=name "{\"arg\": val}"></function>   ← quoted stringified JSON
      - <function=name [{"arg": val}]></function>   ← square-bracket args
      - <function=name {"arg": val}></function>      ← space-separated args
      - <function=name>{"arg": val}</function>       ← standard
      - <function=name=>\"arg\": val}</function>       ← arrow separator
      - name({"arg": val})                           ← function-call style
    """
    text = ""
    if hasattr(e, "body") and isinstance(e.body, dict):
        text = str(e.body.get("error", {}).get("failed_generation", ""))
    if not text:
        text = str(e)

    patterns = [
        # <function=name "{\"k\": ...}"></function>  — stringified JSON inside quotes
        r'<function=(\w+)\s+"(.*?)">\s*</function>',
        r"<function=(\w+)\s+'(.*?)'>\s*</function>",
        # <function=name [{"k": v}]></function>  — args in square brackets
        r"<function=(\w+)\s+\[(\{.*?\})\]>?\s*</function>",
        # <function=name {"k": v}></function>    — args after space before >
        r"<function=(\w+)\s+(\{.*?\})>\s*</function>",
        # <function=name>{"k": v}</function>     — standard
        r"<function=(\w+)>(\{.*?\})</function>",
        # <function=name ... {"k": v} ...        — any separator
        r"<function=(\w+)[=>\s]+(\{.*?\})",
        # name({"k": v})                         — function-call style
        r"(\w+)\s*\(\s*(\{.*?\})\s*\)",
    ]

    for pat in patterns:
        match = re.search(pat, text, re.DOTALL)
        if match:
            func_name = match.group(1)
            raw_args = match.group(2) or "{}"
            # Clean backslashes/escaped quotes
            raw_args = raw_args.replace('\\"', '"').replace("\\'", "'")
            # If wrapped in quotes or extra whitespace, strip
            raw_args = raw_args.strip('"').strip("'")
            try:
                func_args = json.loads(raw_args)
                return func_name, func_args
            except json.JSONDecodeError:
                try:
                    import ast
                    func_args = ast.literal_eval(raw_args)
                    return func_name, func_args
                except Exception:
                    continue
    return None