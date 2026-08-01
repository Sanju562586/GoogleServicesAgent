# Gmail AI Assistant · Groq + MCP

A terminal chat assistant that connects to your Gmail via the **Model Context Protocol (MCP)** and uses **Groq's LLM** for fast AI responses.

```
You: Show me my last 5 unread emails
Assistant: Here are your 5 most recent unread emails:
  1. [Jane] "Q3 Report Draft" — Jul 24
  2. [GitHub] "New PR review requested" — Jul 24
  ...
```

---

## Architecture

```
main.py  ──▶  GmailGroqAgent
                  │
                  ├─ spawns ──▶  gmail_mcp_server.py  (MCP stdio server)
                  │                   └─ gmail_auth.py  (OAuth2)
                  │
                  └─ calls ───▶  Groq API  (LLM with tool use)
```

- **MCP Server** (`src/gmail_mcp_server.py`) — runs as a subprocess, exposes 5 Gmail tools over stdio.
- **Agent** (`src/agent.py`) — manages the Groq conversation loop and routes tool calls to MCP.
- **Auth** (`src/gmail_auth.py`) — handles OAuth2 with token caching.

---

## Setup

### 1 · Install dependencies

```bash
pip install -r requirements.txt
```

### 2 · Get a Groq API key

Sign up at [console.groq.com](https://console.groq.com) (free tier available).

```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### 3 · Set up Gmail API credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → **APIs & Services → Library** → enable **Gmail API**
3. **Credentials → Create Credentials → OAuth 2.0 Client ID** (Desktop app)
4. Download the JSON → rename to `credentials.json` → place in `config/`

On first run, a browser window opens for OAuth consent. The token is saved to `config/token.json` automatically.

### 4 · Run

```bash
# Load env vars
export $(cat .env | xargs)

# Start the assistant
python main.py
```

---

## Available Tools

| Tool | Description |
|---|---|
| `list_emails` | Fetch recent emails (by label) |
| `search_emails` | Search with Gmail query syntax |
| `get_email` | Read full email body by ID |
| `send_email` | Send a new email |
| `reply_email` | Reply to an email thread |

### Example prompts

```
Show me my last 10 inbox emails
Search for emails from john@example.com about invoices
Read email <id>
Send an email to alice@example.com with subject "Hello" and say Hi there
Reply to <id> saying "Thanks, I'll review it tomorrow"
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Your Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Any Groq model with tool use |

---

## File Structure

```
gmail-groq-mcp/
├── main.py                       # Entry point
├── requirements.txt
├── .env.example
├── README.md
├── config/
│   ├── credentials.json          # ← you provide this (see Setup)
│   └── token.json                # ← auto-generated after first login
└── src/
    ├── __init__.py
    ├── agent.py                  # Groq agent + MCP client
    ├── gmail_auth.py             # OAuth2 helper
    └── gmail_mcp_server.py       # MCP server with Gmail tools
```
