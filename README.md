# Personal AI Agent

A self-hosted personal AI assistant that runs entirely on your Mac. It can search your documents, read your calendar, manage your Gmail, and answer general questions — accessible via a web dashboard and a Telegram bot on your phone.

Your data never leaves your machine.

---

## Why build this instead of using Claude.ai or a Claude Telegram bot?

| Feature | This project | Claude.ai | Claude Telegram bot |
|---|:---:|:---:|:---:|
| Your personal documents (RAG) | ✅ | ❌ | ❌ |
| Google Calendar integration | ✅ | ❌ | ❌ |
| Gmail (read, search, draft, send) | ✅ | ❌ | ❌ |
| Save notes from chat | ✅ | ❌ | ❌ |
| **Data stays on your device** | ✅ | ❌ | ❌ |
| Persistent memory (30-day history) | ✅ | Limited | ❌ |
| Telegram bot (phone access) | ✅ | ❌ | ✅ |
| Credential broker (AgentGate) | ✅ optional | ❌ | ❌ |
| Multi-tool per query | ✅ | ✅ | ❌ |
| Auto-starts at login | ✅ | — | — |
| Open source / self-hosted | ✅ | ❌ | ❌ |
| Cost | API usage only | Subscription | API usage |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                      Your Mac                        │
│                                                      │
│  ┌─────────────┐    ┌──────────────────────────┐    │
│  │ Telegram Bot │    │    Web Dashboard          │    │
│  │  (phone)    │    │  http://localhost:8000    │    │
│  └──────┬──────┘    └────────────┬─────────────┘    │
│         │                        │                   │
│         └────────────┬───────────┘                   │
│                      ▼                               │
│             ┌─────────────────┐                      │
│             │   Agent Loop    │                      │
│             │ claude-sonnet   │                      │
│             │  + tool_use     │                      │
│             └────────┬────────┘                      │
│                      │                               │
│        ┌─────────────┼──────────────┐                │
│        ▼             ▼              ▼                │
│   ┌─────────┐  ┌──────────┐  ┌──────────┐           │
│   │   RAG   │  │ Calendar │  │  Gmail   │           │
│   │ChromaDB │  │ Google   │  │  Gmail   │           │
│   └─────────┘  └──────────┘  └──────────┘           │
│                                                      │
│  Optional: AgentGate (credential broker, port 8787)  │
└─────────────────────────────────────────────────────┘
```

---

## Features

- **Claude tool_use agent loop** — Claude decides which tools to call; can call multiple per turn
- **RAG document search** — ChromaDB + sentence-transformers for semantic + keyword hybrid search
- **Save from chat** — say "save this" and it writes to your knowledge base
- **Multi-turn memory** — SQLite-backed session history, 30-day TTL, survives restarts
- **Telegram bot** — full access from your phone, `/reset` to clear context
- **macOS menubar app** — 🤖 icon, shows service status, auto-restarts on crash
- **AgentGate integration** (optional) — credential broker so the AI never handles your OAuth tokens directly; full audit log of every tool call

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+ (for AgentGate only)
- An [Anthropic API key](https://console.anthropic.com)

### 1. Clone and install

```bash
git clone https://github.com/yourusername/ml-from-scratch.git
cd ml-from-scratch
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum
```

### 3. Run

```bash
python app.py
# Open http://localhost:8000
```

### 4. Connect Google (optional)

1. Create a project at [Google Cloud Console](https://console.cloud.google.com)
2. Enable **Gmail API** and **Google Calendar API**
3. Create OAuth credentials (Web application), set redirect URI: `http://localhost:8000/auth/google/callback`
4. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to `.env`
5. Click **Connect** in the dashboard sidebar

### 5. Telegram bot (optional)

1. Message `@BotFather` on Telegram → `/newbot` → copy the token
2. Add `TELEGRAM_BOT_TOKEN=...` to `.env`
3. Restart the server — the bot starts automatically

### 6. Auto-start at login (macOS)

```bash
bash scripts/install_daemon.sh
```

---

## AgentGate (optional — enhanced security)

AgentGate is a credential broker that sits between the AI agent and your Google APIs. The agent calls AgentGate with an API key; AgentGate holds the encrypted OAuth tokens and makes the actual API calls.

```
Agent → AgentGate (encrypted tokens) → Google APIs
         ↓
     audit log
```

Setup:
```bash
cd AgentGate
cp .env.example .env
# Add your Google OAuth credentials (can reuse the same ones)
npm install && npm run dev
# Open http://localhost:8787, connect Google account
```

Then in `ml-from-scratch/.env`, uncomment:
```
AGENT_GATE_URL=http://localhost:8787
AGENT_GATE_KEY=dev-agent-key
```

---

## Adding documents

- **Web UI**: drag and drop files onto the dashboard (txt, md, pdf, docx, images)
- **Telegram**: send any text and say "save this" — it writes directly to the knowledge base
- **Bulk import**: drop files in `my_data/` and run `python load_documents.py`

---

## Project structure

```
ml-from-scratch/
├── app.py                  # FastAPI server + API endpoints
├── rag.py                  # ChromaDB RAG engine
├── calendar_integration.py # Google Calendar OAuth + API
├── gmail_integration.py    # Gmail OAuth + API
├── load_documents.py       # Document ingestion (pdf, docx, images, txt)
├── load_notes.py           # Apple Notes importer
├── src/
│   ├── agent.py            # Claude tool_use agent loop + session store
│   ├── telegram_bot.py     # Telegram bot (polling)
│   └── menubar_app.py      # macOS menubar app (rumps)
├── static/
│   └── index.html          # Web dashboard
├── scripts/
│   └── install_daemon.sh   # macOS launchd installer
├── AgentGate/              # Optional credential broker (Node.js)
├── .env.example
└── requirements.txt
```

---

## Environment variables

See `.env.example` for the full list. The only required variable is `ANTHROPIC_API_KEY`.

---

## License

MIT
