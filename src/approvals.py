"""
Approval queue for irreversible actions.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

import gmail_integration
import nest_integration
from src.config import PROJECT_DIR
from src.security import redact_obj, safe_error_message

_DB_PATH = str(PROJECT_DIR / "data" / "approvals.db")
_db_lock = threading.Lock()


def _init_db() -> None:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                action_input_json TEXT NOT NULL,
                session_id TEXT,
                reason TEXT,
                result_json TEXT,
                rejection_reason TEXT
            )
            """
        )
        conn.commit()
        conn.close()


_init_db()


def approval_gate_enabled() -> bool:
    """
    Global toggle for approval/security layer.
    Default is disabled for simpler local usage.
    """
    return os.getenv("SECURITY_HARDENING", "false").strip().lower() in {"1", "true", "yes", "on"}


def create_pending_action(tool_name: str, action_input: dict, session_id: str | None = None, reason: str | None = None) -> dict:
    now_ms = int(time.time() * 1000)
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        cur = conn.execute(
            """
            INSERT INTO approvals (
                created_at_ms, updated_at_ms, status, tool_name, action_input_json, session_id, reason
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
            (now_ms, now_ms, tool_name, json.dumps(action_input), session_id, reason or ""),
        )
        approval_id = cur.lastrowid
        conn.commit()
        conn.close()
    return {"approval_id": approval_id, "status": "pending"}


def list_pending_actions(limit: int = 100) -> list[dict]:
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            """
            SELECT id, created_at_ms, updated_at_ms, status, tool_name, action_input_json, session_id, reason
            FROM approvals
            WHERE status='pending'
            ORDER BY created_at_ms DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()

    out: list[dict] = []
    for r in rows:
        action_input = json.loads(r[5])
        out.append(
            {
                "id": r[0],
                "created_at_utc": datetime.fromtimestamp(r[1] / 1000, tz=timezone.utc).isoformat(),
                "updated_at_utc": datetime.fromtimestamp(r[2] / 1000, tz=timezone.utc).isoformat(),
                "status": r[3],
                "tool_name": r[4],
                "action_input": redact_obj(action_input),
                "session_id": r[6],
                "reason": r[7],
            }
        )
    return out


def _execute_approved(tool_name: str, action_input: dict) -> dict:
    if tool_name == "send_email":
        return gmail_integration.send_email(action_input["to"], action_input["subject"], action_input["body"])
    if tool_name == "set_thermostat":
        if not nest_integration.is_authenticated():
            return {"error": "Nest is not connected."}
        device_id = action_input["device_id"]
        mode = action_input.get("mode")
        temperature_f = action_input.get("temperature_f")
        result: dict[str, Any] = {}
        if mode:
            result["mode_result"] = nest_integration.set_thermostat_mode(device_id, mode)
        if temperature_f is not None:
            result["temp_result"] = nest_integration.set_thermostat_temperature(device_id, temperature_f, mode)
        result["new_status"] = nest_integration.get_thermostat_status(device_id)
        return result
    return {"error": f"Unsupported approval action: {tool_name}"}


def approve_action(approval_id: int) -> dict:
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute(
            "SELECT status, tool_name, action_input_json FROM approvals WHERE id=?",
            (approval_id,),
        ).fetchone()
        if row is None:
            conn.close()
            return {"error": "Approval not found."}
        status, tool_name, action_input_json = row
        if status != "pending":
            conn.close()
            return {"error": f"Cannot approve action in status '{status}'."}
        conn.close()

    action_input = json.loads(action_input_json)
    now_ms = int(time.time() * 1000)
    try:
        result = _execute_approved(tool_name, action_input)
        final_status = "executed" if "error" not in result else "failed"
    except Exception as e:
        result = {"error": safe_error_message(e)}
        final_status = "failed"

    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "UPDATE approvals SET status=?, updated_at_ms=?, result_json=? WHERE id=?",
            (final_status, now_ms, json.dumps(result), approval_id),
        )
        conn.commit()
        conn.close()

    return {"id": approval_id, "status": final_status, "result": redact_obj(result)}


def reject_action(approval_id: int, reason: str = "") -> dict:
    now_ms = int(time.time() * 1000)
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            conn.close()
            return {"error": "Approval not found."}
        status = row[0]
        if status != "pending":
            conn.close()
            return {"error": f"Cannot reject action in status '{status}'."}
        conn.execute(
            "UPDATE approvals SET status='rejected', updated_at_ms=?, rejection_reason=? WHERE id=?",
            (now_ms, reason, approval_id),
        )
        conn.commit()
        conn.close()
    return {"id": approval_id, "status": "rejected"}


TOOL_PERMISSION_CLASSES = {
    "read_only": {
        "search_documents",
        "get_calendar_events",
        "get_recent_emails",
        "search_emails",
        "get_thermostat_status",
        "get_camera_status",
        "get_daily_goals",
        "recall_memories",
        "web_search",
        "read_webpage",
    },
    "write_draft": {
        "save_document",
        "create_email_draft",
        "remember_fact",
        "forget_fact",
        "save_daily_goals",
        "update_goal_status",
        "query_openclaw",
    },
    "approval_required": {
        "send_email",
        "set_thermostat",
    },
}


def permission_class_for_tool(tool_name: str) -> str:
    for cls, tools in TOOL_PERMISSION_CLASSES.items():
        if tool_name in tools:
            return cls
    return "read_only"

