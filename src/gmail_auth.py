"""
Google OAuth2 Authentication
----------------------------
Handles the OAuth2 flow for all Google services:
  Gmail, Drive, Calendar, Photos, Tasks, Contacts.
Credentials are cached in config/token.json after the first login.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
# pyrefly: ignore [missing-import]
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── OAuth Scopes ───────────────────────────────────────────────────────────────
SCOPES = [
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    # Google Drive
    "https://www.googleapis.com/auth/drive",
    # Google Calendar
    "https://www.googleapis.com/auth/calendar",
    # Google Photos (read-only) — requires Photos Library API enabled in Cloud Console
    "https://www.googleapis.com/auth/photoslibrary.readonly",
    # Google Tasks
    "https://www.googleapis.com/auth/tasks",
    # Google Contacts (People API)
    "https://www.googleapis.com/auth/contacts.readonly",
]

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
TOKEN_FILE = BASE_DIR / "config" / "token.json"


# ── Service Builders ───────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """Return valid Google OAuth2 credentials (for raw token access e.g. Photos API)."""
    return _load_credentials()


def get_gmail_service():
    """Authenticated Gmail API v1 service."""
    return build("gmail", "v1", credentials=_load_credentials())


def get_drive_service():
    """Authenticated Google Drive API v3 service."""
    return build("drive", "v3", credentials=_load_credentials())


def get_calendar_service():
    """Authenticated Google Calendar API v3 service."""
    return build("calendar", "v3", credentials=_load_credentials())


def get_people_service():
    """Authenticated Google People API v1 service (Contacts)."""
    return build("people", "v1", credentials=_load_credentials())


def get_tasks_service():
    """Authenticated Google Tasks API v1 service."""
    return build("tasks", "v1", credentials=_load_credentials())


# ── Internal ───────────────────────────────────────────────────────────────────

def _load_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Missing credentials file: {CREDENTIALS_FILE}\n"
                    "Download OAuth 2.0 Client ID (Desktop app) from Google Cloud Console\n"
                    "and place it at 'config/credentials.json'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return creds
