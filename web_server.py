"""
Web Server — Google Services AI Agent
---------------------------------------
Flow:
  1.  python web_server.py  → server starts, prints URL, waits.
  2.  User opens http://localhost:8000 in any browser.
  3.  If not authenticated → auth page is shown.
  4.  User clicks "Connect Google Account" → redirected to Google OAuth.
  5.  Google redirects back to /auth/callback → token saved → agent starts.
  6.  User lands on the chat page → ready to use.

Endpoints:
  GET  /                 → index.html
  GET  /api/auth-status  → {"authenticated": bool, "agent_ready": bool, "agent_error": str|null}
  GET  /auth/login       → redirect to Google OAuth consent page
  GET  /auth/callback    → OAuth callback, saves token, starts agent
  WS   /ws               → real-time chat (requires authentication)
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── Windows asyncio fix ────────────────────────────────────────────────────────
# On Windows, ProactorEventLoop raises ConnectionResetError (WinError 10054)
# when cleaning up pipe transports after the remote end (MCP subprocess) has
# already closed. This is harmless noise — suppress it globally.
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport

        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _patched_call_connection_lost(self, exc):
            try:
                _orig_call_connection_lost(self, exc)
            except ConnectionResetError:
                pass  # WinError 10054 – remote end already closed, safe to ignore

        _ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost
    except Exception:
        pass  # If patch fails for any reason, continue normally

# Allow HTTP for the OAuth callback on localhost (required by google-auth-oauthlib)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.auth.transport.requests import Request as GoogRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
TOKEN_FILE = BASE_DIR / "config" / "token.json"

sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from src.agent import GmailGroqAgent
from src.gmail_auth import SCOPES

REDIRECT_URI = "http://localhost:8000/auth/callback"

# ── Global agent state ─────────────────────────────────────────────────────────

_agent: GmailGroqAgent | None = None
_agent_ready: bool = False
_agent_error: str | None = None


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _check_auth() -> bool:
    """Return True if a valid (or refreshable) token exists."""
    if not TOKEN_FILE.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogRequest())
            TOKEN_FILE.write_text(creds.to_json())
            return True
    except Exception:
        pass
    return False


def _make_flow() -> Flow:
    """Build a google-auth-oauthlib Flow from the Desktop-app credentials file."""
    return Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )


# ── Agent lifecycle ────────────────────────────────────────────────────────────

async def _init_agent() -> None:
    global _agent, _agent_ready, _agent_error
    # Reset in case of a retry after a previous failure
    _agent_ready = False
    _agent_error = None
    try:
        _agent = GmailGroqAgent()
        await _agent.setup()
        _agent_ready = True
        print("  Agent ready — all Google services connected.")
    except Exception as exc:
        _agent_error = str(exc)
        print(f"  Agent initialization failed: {exc}")


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # If a valid token already exists, start the agent immediately in the
    # background — no blocking, no browser prompts.
    if _check_auth():
        print("  Existing Google token found — initializing agent in background.")
        asyncio.create_task(_init_agent())
    else:
        print("  No Google token found. Open http://localhost:8000 to authenticate.")

    yield

    # Graceful shutdown
    if _agent:
        try:
            await _agent.close()
        except Exception:
            pass


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Google Services AI Agent",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ── HTTP routes ────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/auth-status")
async def api_auth_status():
    """Polled by the frontend to decide which screen to show."""
    return JSONResponse({
        "authenticated": _check_auth(),
        "agent_ready":   _agent_ready,
        "agent_error":   _agent_error,
    })


@app.get("/auth/login")
async def auth_login():
    """Redirect the browser to Google's OAuth consent page."""
    if not CREDENTIALS_FILE.exists():
        return HTMLResponse(
            content=(
                "<h2 style='font-family:sans-serif'>Missing credentials.json</h2>"
                "<p style='font-family:sans-serif'>Place your Google OAuth 2.0 client file at "
                "<code>config/credentials.json</code> and restart the server.</p>"
            ),
            status_code=500,
        )

    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """
    Google redirects here after the user grants permission.
    Exchange the auth code for tokens, save them, then kick off the agent.
    """
    global _agent, _agent_ready, _agent_error

    # Shut down any previous agent instance cleanly before re-initialising
    if _agent:
        try:
            await _agent.close()
        except Exception:
            pass
        _agent = None
        _agent_ready = False
        _agent_error = None

    flow = _make_flow()
    try:
        flow.fetch_token(authorization_response=str(request.url))
        creds = flow.credentials
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        print("  Google authentication successful — starting agent.")
    except Exception as exc:
        return HTMLResponse(
            content=(
                "<h2 style='font-family:sans-serif'>Authentication Error</h2>"
                f"<p style='font-family:sans-serif'>{exc}</p>"
                "<p><a href='/auth/login'>Try again</a></p>"
            ),
            status_code=500,
        )

    # Start the agent in the background so the redirect is instant
    asyncio.create_task(_init_agent())

    # Redirect back to the main page — the JS will see agent_ready soon
    return RedirectResponse("/")


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Guard: must be authenticated
    if not _check_auth():
        await websocket.send_json({"type": "auth_required"})
        await websocket.close()
        return

    # Wait up to ~30 s for the agent to finish initialising
    for _ in range(60):
        if _agent_ready:
            break
        if _agent_error:
            await websocket.send_json({
                "type": "error",
                "message": f"Agent failed to start: {_agent_error}",
            })
            await websocket.close()
            return
        await websocket.send_json({
            "type": "status",
            "message": "Connecting to Google services…",
        })
        await asyncio.sleep(0.5)
    else:
        await websocket.send_json({
            "type": "error",
            "message": "Agent timed out. Please refresh the page.",
        })
        await websocket.close()
        return

    await websocket.send_json({"type": "ready"})

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "message":
                continue

            user_message = data.get("content", "").strip()
            if not user_message:
                continue

            await websocket.send_json({"type": "typing"})

            try:
                response = await _agent.chat(user_message)
                await websocket.send_json({
                    "type": "message",
                    "role": "assistant",
                    "content": response,
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Log the raw error server-side for debugging.
                import sys
                print(f"[chat error] {exc}", file=sys.stderr)
                # Send a clean, user-friendly message to the frontend.
                await websocket.send_json({
                    "type": "error",
                    "message": (
                        "Something went wrong while processing your request. "
                        "Please try again, or rephrase your question."
                    ),
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass  # Client disconnected mid-stream — nothing to do.


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Google Services AI Agent")
    print("  Open http://localhost:8000 in your browser\n")
    uvicorn.run(
        "web_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",
    )
