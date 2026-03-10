"""
State persistence for the money-earning orchestrator.

Stores: pipeline, last_run, actions, user feedback.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _PROJECT_DIR / "data" / "money_agent.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _PROJECT_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH)


def init_db() -> None:
    with _lock:
        conn = _conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT,
                url TEXT,
                company TEXT,
                status TEXT DEFAULT 'new',
                raw_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                payload TEXT,
                result TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS last_run (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL
            );
        """)
        conn.commit()
        conn.close()


init_db()


def add_pipeline_item(source: str, title: str = None, url: str = None, company: str = None, raw: dict = None) -> int:
    with _lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO pipeline (source, title, url, company, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source, title or "", url or "", company or "", json.dumps(raw or {}), datetime.now().timestamp())
        )
        rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
    return rowid


def get_pipeline(status: str = None, limit: int = 50) -> list[dict]:
    with _lock:
        conn = _conn()
        if status:
            rows = conn.execute(
                "SELECT id, source, title, url, company, status, raw_json, created_at FROM pipeline WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, source, title, url, company, status, raw_json, created_at FROM pipeline ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
    return [
        {
            "id": r[0], "source": r[1], "title": r[2], "url": r[3], "company": r[4],
            "status": r[5], "raw": json.loads(r[6]) if r[6] else {}, "created_at": r[7]
        }
        for r in rows
    ]


def update_pipeline_status(item_id: int, status: str) -> None:
    with _lock:
        conn = _conn()
        conn.execute("UPDATE pipeline SET status = ? WHERE id = ?", (status, item_id))
        conn.commit()
        conn.close()


def log_action(action_type: str, payload: dict = None, result: str = None) -> None:
    with _lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO actions (action_type, payload, result, created_at) VALUES (?, ?, ?, ?)",
            (action_type, json.dumps(payload or {}), result or "", datetime.now().timestamp())
        )
        conn.commit()
        conn.close()


def get_last_run(key: str) -> float | None:
    with _lock:
        conn = _conn()
        row = conn.execute("SELECT value FROM last_run WHERE key = ?", (key,)).fetchone()
        conn.close()
    return row[0] if row else None


def set_last_run(key: str, value: float = None) -> None:
    val = value or datetime.now().timestamp()
    with _lock:
        conn = _conn()
        conn.execute("INSERT OR REPLACE INTO last_run (key, value) VALUES (?, ?)", (key, val))
        conn.commit()
        conn.close()
