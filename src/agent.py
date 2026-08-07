"""
Google Services Groq Agent
---------------------------
Orchestrates:
  1. Spawning the unified Google MCP server as a subprocess
  2. Connecting to it via the MCP client
  3. Forwarding all Google tools to Groq's tool-calling API
  4. Running a multi-turn conversation loop with robust fallback handling
"""

from __future__ import annotations

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
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.schemas import TOOL_COERCION_META

# ── Timezone ───────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))

# ── Paths & config ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Model fallback list ────────────────────────────────────────────────────────
# Primary model is read from GROQ_MODEL env var; rest are ordered fallbacks.
# Only active, non-decommissioned Groq models should appear here.

FALLBACK_MODELS: list[str] = [
    os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "llama-3.1-8b-instant",   # Fast small model — excellent tool-calling
    "gemma2-9b-it",            # Google Gemma 2 — reliable fallback
    "llama3-70b-8192",         # Meta Llama 3 70B — active and capable
]

# Maximum conversation history messages retained (prevents context-window overflow).
# Keeps an even count so we never split a tool-call / tool-result pair.
MAX_HISTORY_MESSAGES: int = 40  # ~20 turns

# Hard cap on LLM iterations per user turn (prevents infinite tool-call loops).
MAX_CHAT_ITERATIONS: int = 20

# _TOOL_SCHEMAS has been moved to src/schemas.py as TOOL_COERCION_META.
# Imported at the top of this file.

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
You are a powerful personal AI assistant with LIVE access to all the user's Google services via MCP tools.

{time_context}

You have the following tools available:

GMAIL        : gmail_list_emails, gmail_search_emails, gmail_get_email, gmail_send_email, gmail_reply_email
GOOGLE DRIVE : drive_list_files, drive_search_files, drive_get_file, drive_read_file, drive_create_folder
GOOGLE CALENDAR : calendar_list_events, calendar_search_events, calendar_create_event, calendar_update_event, calendar_delete_event
GOOGLE PHOTOS: photos_list_albums, photos_list_photos, photos_search_photos
GOOGLE TASKS : tasks_list_tasklists, tasks_list_tasks, tasks_create_task, tasks_complete_task
GOOGLE CONTACTS : contacts_list, contacts_search

CRITICAL RULES — FOLLOW WITHOUT EXCEPTION:
1. You ALREADY HAVE live access to all services via tools. NEVER say you cannot access them.
2. ALWAYS call the appropriate tool FIRST before composing any reply.
3. For ANY email question: call gmail_list_emails or gmail_search_emails IMMEDIATELY.
4. For ANY calendar question: call calendar_list_events or calendar_search_events IMMEDIATELY.
5. For ANY Drive / Tasks / Contacts / Photos question: call the matching tool IMMEDIATELY.
6. NEVER fabricate tool results. If a tool returns an error, explain it clearly.
7. Always ask for confirmation before sending emails, creating/deleting events, or creating tasks.
8. Present results clearly and beautifully formatted in markdown.

TIME & TIMEZONE RULES (ALL calendar / task operations):

  RULE 1 — USE IST LITERAL CLOCK VALUES, NEVER CONVERT TO UTC:
    ✅ User says '3 PM'  → datetime = YYYY-MM-DDTHH:MM:SS+05:30  with HH=15
    ✅ User says '5 PM'  → datetime = YYYY-MM-DDTHH:MM:SS+05:30  with HH=17
    ❌ NEVER subtract 5:30.  3 PM is NOT 09:30Z.  3 PM IS 15:00+05:30.
    ❌ NEVER use Z suffix.  NEVER use +00:00.  ALWAYS use +05:30.

  RULE 2 — FORMAT:
    YYYY-MM-DDTHH:MM:SS+05:30  — always include +05:30, never Z, never +00:00.

  RULE 3 — DATE REFERENCES:
    'Today'    = the current date shown above.
    'Tomorrow' = current date + 1 day.
    Always compute the exact calendar date before making a tool call.

  RULE 4 — MISSING END TIME:
    If the user gives only a start time, default end = start + 1 hour.

  RULE 5 — SECONDS:
    Always use :00 for seconds unless the user specifies them.

  RULE 6 — CONFIRMATION:
    Before calendar_create_event or calendar_update_event, state:
    'I will create/update the event on [DATE] from [START IST] to [END IST].'
    Then immediately call the tool with those EXACT times.
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _current_time_context() -> str:
    """Return the current IST datetime string for injection into the system prompt."""
    now = datetime.now(IST)
    return (
        f"CURRENT DATE & TIME (user's local time, IST / UTC+05:30): "
        f"{now.strftime('%A, %d %B %Y %I:%M %p')} "
        f"| ISO 8601: {now.strftime('%Y-%m-%dT%H:%M:%S+05:30')}"
    )


def _coerce_tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and clamp integer values according to the tool's schema.

    Returns a new dict — never mutates the original.
    Schema data is sourced from ``src.schemas.TOOL_COERCION_META``.
    Guards against ``args`` being None or a non-dict value (e.g. JSON ``null``).
    """
    if not isinstance(args, dict):
        args = {}  # Treat None / list / scalar as empty args

    schema = TOOL_COERCION_META.get(name)
    if not schema:
        return dict(args)

    result = {**schema["defaults"], **args}

    # Clamp integers to their declared (min, max) range.
    for field, (lo, hi) in schema["integers"].items():
        if field in result:
            try:
                result[field] = max(lo, min(hi, int(result[field])))
            except (TypeError, ValueError):
                result[field] = schema["defaults"].get(field, lo)

    return result


def _validate_tool_args(name: str, args: dict[str, Any]) -> str | None:
    """Check that all required fields are present and non-empty.

    Returns an error message string if validation fails, or None if valid.
    Schema data is sourced from ``src.schemas.TOOL_COERCION_META``.
    """
    schema = TOOL_COERCION_META.get(name)
    if not schema:
        return None

    missing = [
        f for f in schema["required"]
        if f not in args or args[f] is None or args[f] == ""
    ]
    if missing:
        return f"Missing required argument(s) for {name}: {', '.join(missing)}"

    return None


def _mcp_to_groq_tool(tool: Any) -> dict:
    """Convert an MCP Tool object to Groq's function-calling format."""
    schema = tool.inputSchema or {"type": "object", "properties": {}}
    if isinstance(schema, dict) and "type" not in schema:
        schema = {"type": "object", "properties": {}, **schema}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        },
    }


# ── Tool-call recovery (Groq malformed-output parser) ─────────────────────────

# All known patterns Groq can use when it emits a malformed tool call.
# Ordered from most-specific to least-specific to minimise false matches.
_RECOVERY_PATTERNS: list[str] = [
    # <function=name "{\\"k\\": ...}"></function>  — stringified JSON inside quotes
    r'<function=(\w+)\s+"(.*?)">\s*</function>',
    r"<function=(\w+)\s+'(.*?)'>\s*</function>",
    # <function=name [{"k": v}]></function>  — args in square brackets
    r"<function=(\w+)\s+\[(\{.*?\})]?>?\s*</function>",
    # <function=name {"k": v}></function>  — args after space, before >
    r"<function=(\w+)\s+(\{.*?\})>\s*</function>",
    # <function=name>{"k": v}</function>  — standard MCP format
    r"<function=(\w+)>(\{.*?\})</function>",
    # <function=name{"k": v}</function>  — NO separator between name and JSON
    r"<function=(\w+)(\{.*?\})</function>",
    # <function=name{"k": v}  — no closing tag at all
    r"<function=(\w+)(\{[^<]*\})",
    # <function=name => {"k": v}  — any separator character
    r"<function=(\w+)[=>\s]+(\{.*?\})",
    # <|python_tag|>func_name{"arg": val}  or  <|python_tag|>func_name({"arg": val})
    r"<\|python_tag\|>\s*(\w+)\s*(?:(?:\((.*?)\))|(\{.*?\}))",
    # [TOOL_CALLS] [{"name": "...", "arguments": {...}}]
    r'\[TOOL_CALLS\]\s*\[?\s*\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
    # {"name": "func_name", "arguments": {...}}
    r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
    # func_name({"arg": val})
    r'(\w+)\s*\(\s*(\{.*?\})\s*\)',
]


def _recover_tool_call(text: str) -> tuple[str, dict] | None:
    """Attempt to extract a tool name and argument dict from a malformed text string.

    Used for two scenarios:
      1. Groq's ``tool_use_failed`` 400 error — call with the ``failed_generation`` text.
      2. Model returned plain text containing an embedded tool-call tag instead of
         the structured ``tool_calls`` field.

    Returns ``(func_name, func_args)`` on success, or ``None`` if no pattern matched.
    """
    if not text:
        return None

    for pat in _RECOVERY_PATTERNS:
        match = re.search(pat, text, re.DOTALL)
        if not match:
            continue

        func_name = match.group(1)

        # Find the first non-empty capture group after group(1) as the raw args.
        raw_args: str = "{}"
        for g in match.groups()[1:]:
            if g is not None and g.strip():
                raw_args = g.strip()
                break

        # Un-escape backslash-quoted characters from Groq's stringified JSON.
        raw_args = raw_args.replace('\\"', '"').replace("\\'", "'")
        raw_args = raw_args.strip('"').strip("'")

        try:
            func_args = json.loads(raw_args)
            if not isinstance(func_args, dict):
                func_args = {}  # Guard: JSON null / array / scalar
            return func_name, func_args
        except json.JSONDecodeError:
            try:
                import ast
                func_args = ast.literal_eval(raw_args)
                if not isinstance(func_args, dict):
                    func_args = {}
                return func_name, func_args
            except Exception:
                continue  # Try the next pattern

    return None


def _extract_failed_generation(exc: Exception) -> str:
    """Pull the ``failed_generation`` text out of a Groq 400 error body."""
    if hasattr(exc, "body") and isinstance(exc.body, dict):
        return str(exc.body.get("error", {}).get("failed_generation", ""))
    return str(exc)


# ── Agent ──────────────────────────────────────────────────────────────────────


class GmailGroqAgent:
    """Manages the MCP subprocess connection and the Groq conversation loop."""

    def __init__(self) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "gsk_your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY environment variable is missing or using a placeholder value.\n"
                "Please set a valid GROQ_API_KEY in your .env file."
            )
        self.groq = Groq(api_key=api_key)
        self.history: list[dict] = []
        self._mcp_session: ClientSession | None = None
        self._tools: list[dict] = []
        self._client_cm: Any = None
        self._session_cm: Any = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def setup(self) -> None:
        """Start the unified Google MCP server subprocess and load all tools."""
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

    async def close(self) -> None:
        """Shut down the MCP session and subprocess cleanly."""
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

    # ── Public API ─────────────────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        """Process a user message and return the assistant's reply."""
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        for iteration in range(1, MAX_CHAT_ITERATIONS + 1):
            # --- Call the LLM (with model fallback + tool_use_failed recovery) ---
            response, recovered = await self._llm_call_with_fallback()

            if recovered:
                # A tool_use_failed error was parsed into a valid tool call.
                # Execute it and loop so the model can produce a final answer.
                func_name, func_args, tool_call_id = recovered
                result = await self._call_mcp_tool(func_name, func_args)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                })
                continue

            if response is None:
                return "⚠️ All models are unavailable or rate-limited. Please try again shortly."

            message = response.choices[0].message

            # --- Check for text-embedded tool calls (non-standard model output) ---
            if not message.tool_calls:
                text = message.content or ""
                text_call = _recover_tool_call(text)
                if text_call:
                    func_name, func_args = text_call
                    tool_call_id = f"call_{len(self.history)}"
                    self.history.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(func_args),
                            },
                        }],
                    })
                    result = await self._call_mcp_tool(func_name, func_args)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    })
                    continue

                # Plain text reply — conversation turn complete.
                self.history.append({"role": "assistant", "content": text})
                return text

            # --- Execute structured tool calls ---
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

            for tc in message.tool_calls:
                raw_args = tc.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                    if not isinstance(parsed_args, dict):
                        parsed_args = {}  # Guard: JSON null / array / scalar
                except json.JSONDecodeError:
                    parsed_args = {}
                result = await self._call_mcp_tool(tc.function.name, parsed_args)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Iteration cap reached — prevent infinite loops.
        msg = f"⚠️ Stopped after {MAX_CHAT_ITERATIONS} iterations to prevent an infinite loop."
        self.history.append({"role": "assistant", "content": msg})
        return msg

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _trim_history(self) -> None:
        """Trim conversation history to MAX_HISTORY_MESSAGES, keeping pairs intact."""
        if len(self.history) > MAX_HISTORY_MESSAGES:
            trim_to = MAX_HISTORY_MESSAGES - (MAX_HISTORY_MESSAGES % 2)
            self.history = self.history[-trim_to:]

    async def _llm_call_with_fallback(
        self,
    ) -> tuple[Any | None, tuple[str, dict, str] | None]:
        """Try each model in FALLBACK_MODELS until one succeeds.

        Returns:
            (response, None)         — successful LLM response.
            (None, recovered_call)   — tool_use_failed recovered as (name, args, id).
            (None, None)             — all models failed.
        """
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            time_context=_current_time_context()
        )
        messages = [{"role": "system", "content": system_prompt}] + self.history

        for model_name in FALLBACK_MODELS:
            try:
                response = self.groq.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto",
                )
                return response, None

            except asyncio.CancelledError:
                raise  # Never swallow CancelledError.

            except Exception as exc:
                err_str = str(exc)

                # Model decommissioned or not found — skip silently.
                if any(kw in err_str for kw in ("model_decommissioned", "decommissioned", "404")):
                    print(f"⚠️  Model {model_name!r} unavailable — skipping.", file=sys.stderr)
                    continue

                # Rate-limited — brief pause then try next model.
                if "429" in err_str or "rate_limit_exceeded" in err_str:
                    print(f"⚠️  Model {model_name!r} rate-limited — trying fallback.", file=sys.stderr)
                    try:
                        await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        raise
                    continue

                # tool_use_failed (400) — attempt to recover the call from the
                # failed_generation text embedded in the error body.
                failed_text = _extract_failed_generation(exc)
                recovered = _recover_tool_call(failed_text)
                if recovered:
                    func_name, func_args = recovered
                    func_args = _coerce_tool_args(func_name, func_args)
                    tool_call_id = f"call_{len(self.history)}"
                    # Inject a synthetic assistant + tool pair into history so
                    # the next LLM call has a coherent conversation context.
                    self.history.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": func_name,
                                "arguments": json.dumps(func_args),
                            },
                        }],
                    })
                    return None, (func_name, func_args, tool_call_id)

                # Unrecognised error — propagate as a user-visible message rather
                # than a raw exception so the WebSocket handler can format it nicely.
                print(f"❌ LLM error ({model_name!r}): {exc}", file=sys.stderr)
                raise

        return None, None

    async def _call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool via the MCP session, with coercion and validation.

        Always returns a string — never raises an exception to the caller.
        """
        if not self._mcp_session:
            return "Tool error: MCP session is not initialised."

        # Coerce defaults and clamp integer bounds.
        arguments = _coerce_tool_args(name, arguments)

        # Validate required fields before forwarding to MCP.
        validation_error = _validate_tool_args(name, arguments)
        if validation_error:
            return f"Argument error: {validation_error}"

        try:
            result = await self._mcp_session.call_tool(name, arguments)
            parts = [c.text for c in result.content if hasattr(c, "text")]
            return "\n".join(parts) if parts else "(no result)"
        except Exception as exc:
            return f"Tool error ({name}): {exc}"