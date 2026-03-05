"""
Claude Agent SDK — tool_use agent loop for the Personal AI Assistant.

Replaces the manual classify_intent + dispatch pattern with a proper
multi-turn agent loop where Claude decides which tools to call.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Callable

import urllib.request
import urllib.error

from dotenv import load_dotenv
load_dotenv()

from src.llm_client import LLMClient

from rag import get_engine
import calendar_integration
import gmail_integration
import nest_integration
from src.goals import save_goals, get_today_goals, mark_goal_complete, format_goals_status

# =============================================================================
# AgentGate — optional credential broker
# Set AGENT_GATE_URL in .env to route tool calls through AgentGate instead of
# calling Google APIs directly. Leave blank to use direct integrations.
# =============================================================================

_GATE_URL = os.getenv("AGENT_GATE_URL", "").rstrip("/")
_GATE_KEY = os.getenv("AGENT_GATE_KEY", "dev-agent-key")


def _gate_call(provider: str, action: str, body: dict = None) -> dict:
    """POST to AgentGate /agent/tool/:provider/:action. Returns result dict."""
    url = f"{_GATE_URL}/agent/tool/{provider}/{action}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"x-agent-key": _GATE_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"AgentGate {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": f"AgentGate call failed: {e}"}


# =============================================================================
# Tool Definitions
# =============================================================================

TOOLS = [
    {
        "name": "search_documents",
        "description": (
            "Search the user's personal document knowledge base using semantic + keyword search. "
            "Use this for questions about personal information, IDs, licenses, insurance, notes, "
            "bills, receipts, or any documents the user has uploaded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant document chunks."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Fetch the user's upcoming Google Calendar events. "
            "Use this for questions about schedule, meetings, appointments, or free time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to look for events (default: 7).",
                    "default": 7
                }
            },
            "required": []
        }
    },
    {
        "name": "get_recent_emails",
        "description": (
            "Fetch the user's most recent Gmail inbox emails. "
            "Use this when the user wants to see their inbox or recent messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return (default: 5).",
                    "default": 5
                }
            },
            "required": []
        }
    },
    {
        "name": "search_emails",
        "description": (
            "Search the user's Gmail for emails matching a query. "
            "Use this when the user wants to find specific emails by sender, subject, or content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'from:boss@company.com', 'subject:invoice')."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return (default: 5).",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "send_email",
        "description": (
            "Send an email via Gmail. "
            "IMPORTANT: Only call this tool if the user has explicitly said 'send'. "
            "Prefer create_email_draft unless the user clearly wants to send immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Email body text."
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "save_document",
        "description": (
            "Save a new note or document to the personal knowledge base so it can be searched later. "
            "Use this when the user asks to save, remember, store, or add anything for future reference — "
            "meal plans, notes, passwords, reminders, lists, or any information they want to keep."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "A short descriptive title (e.g. 'Weekly Meal Plan', 'Wifi Password', 'Car Insurance Notes')."
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to save."
                }
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "get_thermostat_status",
        "description": (
            "Get the current status of one or all Nest thermostats — temperature, humidity, mode, "
            "and setpoints. Use when the user asks about home temperature, thermostat, heating, or cooling. "
            "Leave device_id empty to get all thermostats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Full SDM device ID. Omit to fetch all thermostats."
                }
            },
            "required": []
        }
    },
    {
        "name": "set_thermostat",
        "description": (
            "Control a Nest thermostat — set the target temperature or change the mode. "
            "Temperature is always in Fahrenheit. "
            "mode options: HEAT, COOL, HEATCOOL, OFF."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Full SDM device ID of the thermostat to control."
                },
                "temperature_f": {
                    "type": "number",
                    "description": "Target temperature in Fahrenheit."
                },
                "mode": {
                    "type": "string",
                    "enum": ["HEAT", "COOL", "HEATCOOL", "OFF"],
                    "description": "Thermostat mode to set. Optional if only changing temperature."
                }
            },
            "required": ["device_id"]
        }
    },
    {
        "name": "get_camera_status",
        "description": (
            "Get the status and features of one or all Nest cameras. "
            "Use when the user asks about their cameras or security."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Full SDM device ID. Omit to fetch all cameras."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_daily_goals",
        "description": (
            "Get today's goals and their completion status for the current user. "
            "Use this when the user asks about their goals, progress, or what they planned for today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user's Telegram user ID."
                }
            },
            "required": ["user_id"]
        }
    },
    {
        "name": "save_daily_goals",
        "description": (
            "Save the user's 3 goals for today. Call this when the user provides their daily goals, "
            "typically in response to the morning prompt. Extract exactly the goal texts from their message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user's Telegram user ID."
                },
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of up to 3 goal strings extracted from the user's message.",
                    "maxItems": 3
                }
            },
            "required": ["user_id", "goals"]
        }
    },
    {
        "name": "update_goal_status",
        "description": (
            "Mark one of today's goals as complete or incomplete. "
            "Use this when the user says a goal is done, finished, or complete. "
            "Goal numbers are 1, 2, or 3."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user's Telegram user ID."
                },
                "goal_number": {
                    "type": "integer",
                    "description": "Which goal to update (1, 2, or 3).",
                    "enum": [1, 2, 3]
                },
                "completed": {
                    "type": "boolean",
                    "description": "True to mark complete, false to unmark.",
                    "default": True
                }
            },
            "required": ["user_id", "goal_number"]
        }
    },
    {
        "name": "create_email_draft",
        "description": (
            "Create a Gmail draft (does not send). "
            "Use this by default when the user asks to compose or draft an email. "
            "Only use send_email if the user explicitly says they want to send it now."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Email body text."
                }
            },
            "required": ["to", "subject", "body"]
        }
    }
]


# =============================================================================
# Tool Executors — pure data fetching, no Claude calls inside
# =============================================================================

_DOCS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "documents.json")


def _execute_save_document(title: str, content: str) -> dict:
    """Save a new document to the RAG knowledge base."""
    try:
        from load_documents import chunk_text
        import rag

        documents = []
        if os.path.exists(_DOCS_PATH):
            with open(_DOCS_PATH, "r") as f:
                documents = json.load(f)

        existing_ids = [
            int(d["id"].split("_")[0])
            for d in documents
            if d["id"].split("_")[0].isdigit()
        ]
        next_id = max(existing_ids, default=0) + 1

        chunks = chunk_text(content, chunk_size=500, overlap=50)
        slug = title.lower().replace(" ", "_")[:40]

        for i, chunk in enumerate(chunks):
            doc_id = f"{next_id}_{i+1}" if len(chunks) > 1 else str(next_id)
            chunk_title = f"{title} (Part {i+1}/{len(chunks)})" if len(chunks) > 1 else title
            documents.append({
                "id": doc_id,
                "title": chunk_title,
                "content": chunk,
                "metadata": {
                    "source": f"agent_saved/{slug}.txt",
                    "type": "agent_saved",
                    "saved": datetime.now().isoformat()
                }
            })

        with open(_DOCS_PATH, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)

        # Invalidate RAG cache so next search picks up the new doc
        if rag._engine is not None:
            rag._engine._initialized = False

        return {"success": True, "title": title, "chunks": len(chunks)}
    except Exception as e:
        return {"error": f"Failed to save document: {e}"}


def _execute_search_documents(query: str) -> dict:
    """Search personal documents via RAG (semantic + keyword). Always runs locally."""
    try:
        engine = get_engine()
        results = engine.search(query, top_k=8)
        if not results:
            return {"results": [], "message": "No matching documents found."}
        return {
            "results": [
                {
                    "title": r["title"],
                    "content": r["content"],
                    "source": r["source"],
                    "similarity": round(r["similarity"], 3)
                }
                for r in results
            ]
        }
    except Exception as e:
        return {"error": f"Document search failed: {e}"}


def _execute_get_calendar_events(days: int = 7) -> dict:
    """Fetch upcoming Google Calendar events."""
    if _GATE_URL:
        return _gate_call("calendar", "get_events", {"days": days})
    if not calendar_integration.is_authenticated():
        return {"error": "Google Calendar is not connected. Please connect via the sidebar."}
    try:
        events = calendar_integration.get_upcoming_events(days=days)
        if events is None:
            return {"error": "Failed to fetch calendar events. Please try reconnecting."}
        return {"events": events, "days_ahead": days}
    except Exception as e:
        return {"error": f"Calendar fetch failed: {e}"}


def _execute_get_recent_emails(max_results: int = 5) -> dict:
    """Fetch recent inbox emails from Gmail."""
    if _GATE_URL:
        return _gate_call("gmail", "get_recent_emails", {"max_results": max_results})
    if not gmail_integration.is_authenticated():
        return {"error": "Gmail is not connected. Please connect via the sidebar."}
    try:
        emails = gmail_integration.get_recent_emails(max_results=max_results)
        if emails is None:
            return {"error": "Failed to fetch emails. Please try reconnecting Gmail."}
        return {"emails": emails}
    except Exception as e:
        return {"error": f"Email fetch failed: {e}"}


def _execute_search_emails(query: str, max_results: int = 5) -> dict:
    """Search Gmail for emails matching a query."""
    if _GATE_URL:
        return _gate_call("gmail", "search_emails", {"query": query, "max_results": max_results})
    if not gmail_integration.is_authenticated():
        return {"error": "Gmail is not connected. Please connect via the sidebar."}
    try:
        emails = gmail_integration.search_emails(query, max_results=max_results)
        if emails is None:
            return {"error": "Failed to search emails. Please try reconnecting Gmail."}
        return {"emails": emails, "query": query}
    except Exception as e:
        return {"error": f"Email search failed: {e}"}


def _execute_send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via Gmail."""
    if _GATE_URL:
        return _gate_call("gmail", "send_email", {"to": to, "subject": subject, "body": body})
    if not gmail_integration.is_authenticated():
        return {"error": "Gmail is not connected. Please connect via the sidebar."}
    try:
        return gmail_integration.send_email(to, subject, body)
    except Exception as e:
        return {"error": f"Send email failed: {e}"}


def _execute_get_thermostat_status(device_id: str = None) -> dict:
    if not nest_integration.is_authenticated():
        return {"error": "Nest is not connected. Please connect via the dashboard sidebar."}
    if not nest_integration.NEST_PROJECT_ID:
        return {"error": "NEST_PROJECT_ID not set in .env"}
    devices = nest_integration.list_devices()
    thermostats = [d for d in devices if d["type"] == "THERMOSTAT"]
    if not thermostats:
        return {"error": "No thermostats found in your Nest account."}
    if device_id:
        return nest_integration.get_thermostat_status(device_id)
    return {"thermostats": [nest_integration.get_thermostat_status(d["id"]) for d in thermostats]}


def _execute_set_thermostat(device_id: str, temperature_f: float = None, mode: str = None) -> dict:
    if not nest_integration.is_authenticated():
        return {"error": "Nest is not connected. Please connect via the dashboard sidebar."}
    results = {}
    if mode:
        results["mode_result"] = nest_integration.set_thermostat_mode(device_id, mode)
    if temperature_f is not None:
        results["temp_result"] = nest_integration.set_thermostat_temperature(device_id, temperature_f, mode)
    if not results:
        return {"error": "Provide temperature_f or mode to set."}
    results["new_status"] = nest_integration.get_thermostat_status(device_id)
    return results


def _execute_get_camera_status(device_id: str = None) -> dict:
    if not nest_integration.is_authenticated():
        return {"error": "Nest is not connected. Please connect via the dashboard sidebar."}
    devices = nest_integration.list_devices()
    cameras = [d for d in devices if d["type"] in ("CAMERA", "DOORBELL", "DISPLAY")]
    if not cameras:
        return {"error": "No cameras found in your Nest account."}
    if device_id:
        return nest_integration.get_camera_status(device_id)
    return {"cameras": [nest_integration.get_camera_status(d["id"]) for d in cameras]}


def _execute_get_daily_goals(user_id: str) -> dict:
    goals = get_today_goals(int(user_id))
    return {"goals": goals, "summary": format_goals_status(goals)}


def _execute_save_daily_goals(user_id: str, goals: list) -> dict:
    return save_goals(int(user_id), goals)


def _execute_update_goal_status(user_id: str, goal_number: int, completed: bool = True) -> dict:
    result = mark_goal_complete(int(user_id), goal_number, completed)
    goals = get_today_goals(int(user_id))
    result["summary"] = format_goals_status(goals)
    return result


def _execute_create_email_draft(to: str, subject: str, body: str) -> dict:
    """Create a Gmail draft."""
    if _GATE_URL:
        return _gate_call("gmail", "create_draft", {"to": to, "subject": subject, "body": body})
    if not gmail_integration.is_authenticated():
        return {"error": "Gmail is not connected. Please connect via the sidebar."}
    try:
        return gmail_integration.create_draft(to, subject, body)
    except Exception as e:
        return {"error": f"Create draft failed: {e}"}


# Dispatch table: tool name → executor lambda
TOOL_EXECUTORS: dict[str, Callable] = {
    "save_document":     lambda inp: _execute_save_document(inp["title"], inp["content"]),
    "search_documents":  lambda inp: _execute_search_documents(inp["query"]),
    "get_calendar_events": lambda inp: _execute_get_calendar_events(inp.get("days", 7)),
    "get_recent_emails": lambda inp: _execute_get_recent_emails(inp.get("max_results", 5)),
    "search_emails":     lambda inp: _execute_search_emails(inp["query"], inp.get("max_results", 5)),
    "send_email":        lambda inp: _execute_send_email(inp["to"], inp["subject"], inp["body"]),
    "create_email_draft": lambda inp: _execute_create_email_draft(inp["to"], inp["subject"], inp["body"]),
    "get_thermostat_status": lambda inp: _execute_get_thermostat_status(inp.get("device_id")),
    "set_thermostat":        lambda inp: _execute_set_thermostat(inp["device_id"], inp.get("temperature_f"), inp.get("mode")),
    "get_camera_status":     lambda inp: _execute_get_camera_status(inp.get("device_id")),
    "get_daily_goals":   lambda inp: _execute_get_daily_goals(inp["user_id"]),
    "save_daily_goals":  lambda inp: _execute_save_daily_goals(inp["user_id"], inp["goals"]),
    "update_goal_status": lambda inp: _execute_update_goal_status(inp["user_id"], inp["goal_number"], inp.get("completed", True)),
}


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a personal AI assistant with access to the user's documents, calendar, and email.
Today is {today}.

## Capabilities
- **Documents**: Search personal documents, notes, IDs, insurance, receipts, and any uploaded files. Also save new notes/information using `save_document`.
- **Calendar**: Check upcoming events and schedule via Google Calendar.
- **Email**: Read inbox, search emails, create drafts, or send emails via Gmail.
- **Vision**: Analyze photos and images sent by the user — plants, objects, text in images, receipts, etc.
- **General knowledge**: Answer questions using your training knowledge when no tool is needed.

## Guidelines
- Use tools proactively when the query is about personal data, schedule, or email.
- Call multiple tools in the same turn if needed to give a complete answer.
- For email composition: **always use `create_email_draft` by default**. Only call `send_email` if the user explicitly says "send it now" or "go ahead and send".
- If a tool returns an error about not being connected, inform the user and guide them to connect via the sidebar.
- Be concise but thorough. Format responses with markdown when it helps readability.
"""


# =============================================================================
# Session Store (SQLite-backed, 30-day TTL)
# =============================================================================

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_DIR, "data", "sessions.db")
_SESSION_TTL = 30 * 24 * 60 * 60  # 30 days
_db_lock = threading.Lock()


def _init_db() -> None:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                messages    TEXT NOT NULL,
                last_access REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()


_init_db()


def _serialize_messages(messages: list) -> str:
    """Convert messages list (may contain Pydantic SDK objects) to JSON string.
    Image blocks are replaced with a text placeholder to avoid storing large base64 blobs."""
    serializable = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            serializable.append({"role": msg["role"], "content": content})
        elif isinstance(content, list):
            blocks = []
            for block in content:
                b = block.model_dump() if hasattr(block, "model_dump") else block
                # Strip base64 image data — too large to store in SQLite session
                if isinstance(b, dict) and b.get("type") == "image":
                    blocks.append({"type": "text", "text": "[Image attached]"})
                else:
                    blocks.append(b)
            serializable.append({"role": msg["role"], "content": blocks})
    return json.dumps(serializable)


def _save_session(session_id: str, messages: list) -> None:
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, messages, last_access) VALUES (?, ?, ?)",
            (session_id, _serialize_messages(messages), time.time())
        )
        conn.commit()
        conn.close()


def _get_or_create_session(session_id: str) -> list:
    """Load session from DB, or return empty list if new/expired."""
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute(
            "SELECT messages, last_access FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        conn.close()

    if row is None:
        return []

    messages_json, last_access = row
    if time.time() - last_access > _SESSION_TTL:
        clear_session(session_id)
        return []

    return json.loads(messages_json)


def clear_session(session_id: str) -> None:
    """Delete a session from the DB."""
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()


# =============================================================================
# Intent Derivation
# =============================================================================

def _derive_intent(tools_used: list[str]) -> str:
    """Map tool names used → UI badge intent string."""
    if not tools_used:
        return "general"
    if any(t in tools_used for t in ("get_daily_goals", "save_daily_goals", "update_goal_status")):
        return "goals"
    if any(t in tools_used for t in ("search_documents", "save_document")):
        return "documents"
    if any(t in tools_used for t in ("get_recent_emails", "search_emails", "send_email", "create_email_draft")):
        return "email"
    if "get_calendar_events" in tools_used:
        return "calendar"
    return "general"


# =============================================================================
# Agent Loop
# =============================================================================

def run_agent(query: str, session_id: str = None, max_iterations: int = 10, image_data: dict = None) -> dict:
    """
    Run the Claude tool_use agent loop.

    Args:
        query:      The user's text message.
        session_id: Persistent session ID for multi-turn memory.
        image_data: Optional dict with keys 'data' (base64 str) and 'media_type' (e.g. 'image/jpeg').
                    When provided, the image is sent to Claude Vision alongside the query.

    Returns:
        {
            "answer": str,
            "intent": str,   # "documents" | "email" | "calendar" | "general"
            "sources": list  # source filenames from document search results
        }
    """
    client = LLMClient.from_env()

    # Session management
    if session_id is None:
        import uuid
        session_id = str(uuid.uuid4())

    messages = _get_or_create_session(session_id)

    # Build user message — include image block if provided (vision-capable models only)
    if image_data and client.supports_vision:
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_data["media_type"],
                    "data": image_data["data"]
                }
            },
            {"type": "text", "text": query}
        ]
    else:
        user_content = query if not image_data else f"[Image attached — vision not supported by this model]\n\n{query}"

    messages.append({"role": "user", "content": user_content})

    system = SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %B %d, %Y"))

    tools_used: list[str] = []
    sources: list[str] = []

    for _ in range(max_iterations):
        response = client.create(messages, TOOLS, system)

        if response.stop_reason == "end_turn":
            # Persist assistant message and save to DB
            messages.append({"role": "assistant", "content": response.text})
            _save_session(session_id, messages)

            return {
                "answer": response.text,
                "intent": _derive_intent(tools_used),
                "sources": sorted(set(sources))
            }

        elif response.stop_reason == "tool_use":
            # Persist the assistant message (provider-normalised)
            messages.append({"role": "assistant", "content": response.text or ""})

            # Execute each tool call and collect results
            results: list[str] = []
            for call in response.tool_calls:
                tool_name  = call["name"]
                tool_input = call["input"]
                tools_used.append(tool_name)

                executor = TOOL_EXECUTORS.get(tool_name)
                result   = executor(tool_input) if executor else {"error": f"Unknown tool: {tool_name}"}

                # Collect document sources
                if tool_name == "search_documents" and "results" in result:
                    for r in result["results"]:
                        src = r.get("source", "")
                        if src:
                            sources.append(src)

                results.append(json.dumps(result))

            # Feed tool results back in provider-specific format
            messages.extend(client.build_tool_result_messages(response.tool_calls, results))

        else:
            break

    # Max iterations exceeded
    return {
        "answer": "I'm sorry, I wasn't able to complete that request (exceeded maximum steps).",
        "intent": _derive_intent(tools_used),
        "sources": sorted(set(sources))
    }
