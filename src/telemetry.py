"""
Lightweight usage telemetry for the personal agent.

Stores per-LLM-call latency + token usage (best-effort) in SQLite.
Optionally computes cost if pricing is configured.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.config import PROJECT_DIR

_DB_PATH = str(PROJECT_DIR / "data" / "usage.db")
_db_lock = threading.Lock()


def _init_db() -> None:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                date TEXT NOT NULL,
                session_id TEXT,
                provider TEXT,
                model TEXT,
                stop_reason TEXT,
                latency_ms INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                cache_write_tokens INTEGER,
                total_tokens INTEGER,
                cost_total REAL,
                cost_input REAL,
                cost_output REAL,
                cost_cache_read REAL,
                cost_cache_write REAL,
                error TEXT
            )
            """
        )
        conn.commit()
        conn.close()


_init_db()


def _pricing_from_env() -> dict[str, Any]:
    """
    Optional pricing map (per 1M tokens):
      TELEMETRY_PRICING_JSON='{"groq":{"meta-llama/...":{"input":0.1,"output":0.3}}}'
    """
    raw = os.getenv("TELEMETRY_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _compute_cost(provider: str, model: str, usage: dict) -> dict:
    """
    Compute best-effort cost using TELEMETRY_PRICING_JSON if present.
    Pricing is per 1M tokens: {input, output, cacheRead, cacheWrite}.
    """
    pricing = _pricing_from_env()
    p = (
        pricing.get(provider, {}).get(model)
        or pricing.get(provider, {}).get("*")
        or pricing.get("*", {}).get(model)
        or pricing.get("*", {}).get("*")
        or {}
    )
    def per_million(name: str) -> float:
        try:
            return float(p.get(name, 0.0) or 0.0)
        except Exception:
            return 0.0

    input_t = int(usage.get("input", 0) or 0)
    output_t = int(usage.get("output", 0) or 0)
    cr_t = int(usage.get("cacheRead", 0) or 0)
    cw_t = int(usage.get("cacheWrite", 0) or 0)

    input_cost = input_t * per_million("input") / 1_000_000
    output_cost = output_t * per_million("output") / 1_000_000
    cr_cost = cr_t * per_million("cacheRead") / 1_000_000
    cw_cost = cw_t * per_million("cacheWrite") / 1_000_000
    total = input_cost + output_cost + cr_cost + cw_cost
    return {
        "totalCost": total,
        "inputCost": input_cost,
        "outputCost": output_cost,
        "cacheReadCost": cr_cost,
        "cacheWriteCost": cw_cost,
        "missingCostEntries": 0 if p else 1,
    }


def record_llm_call(
    *,
    ts_ms: int | None = None,
    session_id: str | None,
    provider: str,
    model: str,
    stop_reason: str,
    latency_ms: int | None,
    usage: dict | None = None,
    error: str | None = None,
) -> None:
    usage = usage or {}
    ts_ms = int(ts_ms if ts_ms is not None else time.time() * 1000)
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    date = dt.date().isoformat()

    input_t = int(usage.get("input", 0) or 0)
    output_t = int(usage.get("output", 0) or 0)
    cr_t = int(usage.get("cacheRead", 0) or 0)
    cw_t = int(usage.get("cacheWrite", 0) or 0)
    total_t = int(usage.get("totalTokens", input_t + output_t + cr_t + cw_t) or 0)

    cost = _compute_cost(provider, model, {"input": input_t, "output": output_t, "cacheRead": cr_t, "cacheWrite": cw_t})

    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            """
            INSERT INTO llm_calls (
                ts_ms, date, session_id, provider, model, stop_reason, latency_ms,
                input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,
                cost_total, cost_input, cost_output, cost_cache_read, cost_cache_write,
                error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_ms, date, session_id, provider, model, stop_reason, latency_ms,
                input_t, output_t, cr_t, cw_t, total_t,
                float(cost.get("totalCost", 0.0) or 0.0),
                float(cost.get("inputCost", 0.0) or 0.0),
                float(cost.get("outputCost", 0.0) or 0.0),
                float(cost.get("cacheReadCost", 0.0) or 0.0),
                float(cost.get("cacheWriteCost", 0.0) or 0.0),
                error,
            ),
        )
        conn.commit()
        conn.close()


def usage_report(start_date: str | None = None, end_date: str | None = None) -> dict:
    """
    Generate an OpenClaw-like usage report from llm_calls.
    Dates are YYYY-MM-DD in UTC, inclusive.
    """
    where = []
    params: list[Any] = []
    if start_date:
        where.append("date >= ?")
        params.append(start_date)
    if end_date:
        where.append("date <= ?")
        params.append(end_date)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with _db_lock:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            f"""
            SELECT date, provider, model, stop_reason, latency_ms,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,
                   cost_total, cost_input, cost_output, cost_cache_read, cost_cache_write,
                   error
            FROM llm_calls
            {clause}
            """,
            params,
        ).fetchall()
        conn.close()

    totals = Counter()
    cost_totals = Counter()
    missing_cost_entries = 0
    daily = defaultdict(Counter)
    by_model = defaultdict(Counter)
    by_provider = defaultdict(Counter)
    latency_daily = defaultdict(list)

    call_count = 0
    error_count = 0

    for (
        date, provider, model, stop_reason, latency_ms,
        in_t, out_t, cr_t, cw_t, total_t,
        cost_total, cost_in, cost_out, cost_cr, cost_cw,
        error,
    ) in rows:
        call_count += 1
        if error:
            error_count += 1

        totals.update({
            "input": in_t,
            "output": out_t,
            "cacheRead": cr_t,
            "cacheWrite": cw_t,
            "totalTokens": total_t,
        })
        cost_totals.update({
            "totalCost": cost_total or 0.0,
            "inputCost": cost_in or 0.0,
            "outputCost": cost_out or 0.0,
            "cacheReadCost": cost_cr or 0.0,
            "cacheWriteCost": cost_cw or 0.0,
        })
        if (cost_total or 0.0) == 0.0 and total_t:
            # If tokens exist but we couldn't price them (no pricing config), count as missing.
            missing_cost_entries += 1

        daily[date].update({
            "input": in_t,
            "output": out_t,
            "cacheRead": cr_t,
            "cacheWrite": cw_t,
            "totalTokens": total_t,
            "totalCost": cost_total or 0.0,
        })

        key_m = (provider, model)
        by_model[key_m].update({
            "count": 1,
            "input": in_t,
            "output": out_t,
            "cacheRead": cr_t,
            "cacheWrite": cw_t,
            "totalTokens": total_t,
            "totalCost": cost_total or 0.0,
        })
        by_provider[provider].update({
            "count": 1,
            "input": in_t,
            "output": out_t,
            "cacheRead": cr_t,
            "cacheWrite": cw_t,
            "totalTokens": total_t,
            "totalCost": cost_total or 0.0,
        })

        if latency_ms is not None:
            latency_daily[date].append(int(latency_ms))

    # Latency aggregates
    def _lat_stats(values: list[int]) -> dict:
        if not values:
            return {"count": 0, "avgMs": 0, "p95Ms": 0, "minMs": 0, "maxMs": 0}
        values = sorted(values)
        count = len(values)
        avg = sum(values) / count
        p95 = values[int(0.95 * (count - 1))]
        return {"count": count, "avgMs": avg, "p95Ms": p95, "minMs": values[0], "maxMs": values[-1]}

    all_lat = [v for vs in latency_daily.values() for v in vs]
    latency = _lat_stats(all_lat)
    daily_latency = [{"date": d, **_lat_stats(vs)} for d, vs in sorted(latency_daily.items())]

    report = {
        "totals": {
            "input": int(totals["input"]),
            "output": int(totals["output"]),
            "cacheRead": int(totals["cacheRead"]),
            "cacheWrite": int(totals["cacheWrite"]),
            "totalTokens": int(totals["totalTokens"]),
            "totalCost": float(cost_totals["totalCost"]),
            "inputCost": float(cost_totals["inputCost"]),
            "outputCost": float(cost_totals["outputCost"]),
            "cacheReadCost": float(cost_totals["cacheReadCost"]),
            "cacheWriteCost": float(cost_totals["cacheWriteCost"]),
            "missingCostEntries": int(missing_cost_entries),
        },
        "daily": [
            {
                "date": d,
                "input": int(c["input"]),
                "output": int(c["output"]),
                "cacheRead": int(c["cacheRead"]),
                "cacheWrite": int(c["cacheWrite"]),
                "totalTokens": int(c["totalTokens"]),
                "totalCost": float(c["totalCost"]),
            }
            for d, c in sorted(daily.items())
        ],
        "aggregates": {
            "llmCalls": {"total": call_count, "errors": error_count},
            "latency": latency,
            "dailyLatency": daily_latency,
            "byModel": [
                {
                    "provider": prov,
                    "model": model,
                    "count": int(c["count"]),
                    "totals": {
                        "input": int(c["input"]),
                        "output": int(c["output"]),
                        "cacheRead": int(c["cacheRead"]),
                        "cacheWrite": int(c["cacheWrite"]),
                        "totalTokens": int(c["totalTokens"]),
                        "totalCost": float(c["totalCost"]),
                    },
                }
                for (prov, model), c in sorted(by_model.items(), key=lambda kv: kv[0])
            ],
            "byProvider": [
                {
                    "provider": prov,
                    "count": int(c["count"]),
                    "totals": {
                        "input": int(c["input"]),
                        "output": int(c["output"]),
                        "cacheRead": int(c["cacheRead"]),
                        "cacheWrite": int(c["cacheWrite"]),
                        "totalTokens": int(c["totalTokens"]),
                        "totalCost": float(c["totalCost"]),
                    },
                }
                for prov, c in sorted(by_provider.items(), key=lambda kv: kv[0])
            ],
        },
        "meta": {
            "db": _DB_PATH,
            "startDate": start_date,
            "endDate": end_date,
            "pricingConfigured": bool(_pricing_from_env()),
        },
    }
    return report

