"""
Long-term memory store for the Personal AI Assistant.

Memories persist across sessions in SQLite. They are automatically injected
into the system prompt so the agent always knows what it has learned about the user.

Categories:
  preference  — how the user likes things done ("prefers short emails")
  person      — people the user knows ("boss is Sarah Chen at Acme Corp")
  routine     — recurring patterns ("standup every Mon/Wed/Fri at 9am")
  fact        — one-off facts ("home address is 123 Main St")
  general     — anything else
"""

import os
import sqlite3
import threading
from datetime import datetime

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_DIR, "data", "memory.db")
_lock = threading.Lock()


# =============================================================================
# DB Init
# =============================================================================

def _init_db() -> None:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content    TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()


_init_db()


# =============================================================================
# CRUD
# =============================================================================

def save_memory(content: str, category: str = "general") -> dict:
    """Save a new memory. Returns the saved record."""
    now = datetime.now().isoformat()
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        cur = conn.execute(
            "INSERT INTO memories (content, category, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (content, category, now, now)
        )
        memory_id = cur.lastrowid
        conn.commit()
        conn.close()
    return {"success": True, "id": memory_id, "content": content, "category": category}


def get_all_memories() -> list[dict]:
    """Return all memories ordered by most recently updated."""
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            "SELECT id, content, category, created_at FROM memories ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
    return [{"id": r[0], "content": r[1], "category": r[2], "created_at": r[3]} for r in rows]


def search_memories(query: str, top_k: int = 10) -> list[dict]:
    """Keyword search over memories — returns top_k most relevant."""
    all_memories = get_all_memories()
    query_words = set(query.lower().split())
    scored = []
    for m in all_memories:
        content_lower = m["content"].lower()
        score = sum(1 for w in query_words if w in content_lower)
        if score > 0:
            scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top_k]]


def delete_memory(memory_id: int) -> dict:
    """Delete a memory by ID."""
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
    return {"success": True, "deleted_id": memory_id}


# =============================================================================
# Prompt Formatting
# =============================================================================

def format_memories_for_prompt(memories: list[dict]) -> str:
    """Format memories into a system prompt section."""
    if not memories:
        return ""
    lines = ["## What I know about you (long-term memory)"]
    # Group by category
    by_category: dict[str, list[str]] = {}
    for m in memories:
        cat = m["category"]
        by_category.setdefault(cat, []).append(m["content"])
    for cat, items in by_category.items():
        lines.append(f"\n**{cat.capitalize()}**")
        for item in items:
            lines.append(f"- {item}")
    return "\n".join(lines)
