"""
Always-on money-earning orchestrator.

Runs a tick loop: load instructions + state → ask LLM what to do next → invoke sub-agents → persist.

Run: python -m src.money_agent.orchestrator

Usage:
  python -m src.money_agent.orchestrator           # one tick
  python -m src.money_agent.orchestrator --loop   # continuous (every 30 min)
  python -m src.money_agent.orchestrator --loop 15 # every 15 min
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root on path
_PROJECT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT))

from src.env_loader import load_env
load_env()

import yaml
from src.llm_client import LLMClient
from src.money_agent.state import (
    get_pipeline,
    add_pipeline_item,
    log_action,
    get_last_run,
    set_last_run,
)
from src.money_agent.subagents import run_job_search, run_freelance_agent

# Optional: web research (may be disabled by egress policy)
try:
    from src.web_research import web_search, read_webpage
    _WEB_AVAILABLE = True
except Exception:
    _WEB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INSTRUCTIONS_PATH = _PROJECT / "config" / "money_instructions.yaml"
if not INSTRUCTIONS_PATH.is_file():
    INSTRUCTIONS_PATH = _PROJECT / "config" / "money_instructions.yaml.example"


def load_instructions() -> dict:
    if not INSTRUCTIONS_PATH.is_file():
        return {"objectives": [], "constraints": {}, "channels": {}, "cadence": {}}
    with open(INSTRUCTIONS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Tools for orchestrator LLM
# ---------------------------------------------------------------------------

def _tool_invoke_job_search(task: str, context: dict) -> dict:
    result = run_job_search(task, context)
    return {"success": result.success, "summary": result.summary, "data": result.data, "actions": result.actions_suggested}


def _tool_invoke_freelance(task: str, context: dict) -> dict:
    result = run_freelance_agent(task, context)
    return {"success": result.success, "summary": result.summary, "data": result.data, "actions": result.actions_suggested}


def _tool_web_search(query: str, max_results: int = 5) -> dict:
    if not _WEB_AVAILABLE:
        return {"error": "Web research not available (egress disabled)."}
    try:
        out = web_search(query, max_results=max_results)
        return {"results": out.get("results", [])}
    except Exception as e:
        return {"error": str(e)}


def _tool_read_webpage(url: str) -> dict:
    if not _WEB_AVAILABLE:
        return {"error": "Web research not available."}
    try:
        text = read_webpage(url)
        return {"text": text[:8000] if text else ""}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Orchestrator tick
# ---------------------------------------------------------------------------

ORCHESTRATOR_TOOLS = [
    {
        "name": "invoke_job_search",
        "description": "Run the job search sub-agent. Use for: finding jobs, drafting applications, building role maps.",
        "input_schema": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "Task for job search agent, e.g. 'find PM roles' or 'draft application for job X'"}},
            "required": ["task"]
        }
    },
    {
        "name": "invoke_freelance",
        "description": "Run the freelance/gig sub-agent. Use for: checking Upwork invites, finding gigs, drafting proposals.",
        "input_schema": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "Task for freelance agent"}},
            "required": ["task"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web. Use for job boards, company research, gig listings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_webpage",
        "description": "Fetch and read a webpage. Use for job postings, company pages.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    },
]

TOOL_EXECUTORS = {
    "invoke_job_search": lambda inp: _tool_invoke_job_search(inp["task"], _TICK_CONTEXT),
    "invoke_freelance": lambda inp: _tool_invoke_freelance(inp["task"], _TICK_CONTEXT),
    "web_search": lambda inp: _tool_web_search(inp["query"], inp.get("max_results", 5)),
    "read_webpage": lambda inp: _tool_read_webpage(inp["url"]),
}

# Context passed to sub-agents (set each tick)
_TICK_CONTEXT: dict = {}


def run_tick() -> dict:
    """Run one orchestrator tick. Returns summary of actions taken."""
    instructions = load_instructions()
    pipeline = get_pipeline(limit=20)
    last = get_last_run("orchestrator_tick") or 0
    now = datetime.now()

    global _TICK_CONTEXT
    _TICK_CONTEXT = {
        "instructions": instructions,
        "pipeline": pipeline,
        "last_run": last,
        "now": now.isoformat(),
    }

    system = f"""You are the orchestrator for an always-on money-earning agent. Your job is to help the user earn money by coordinating sub-agents and taking actions.

Today is {now.strftime("%A, %B %d, %Y")}. Current time: {now.strftime("%H:%M")}.

## User instructions
{json.dumps(instructions, indent=2)}

## Current pipeline (recent items)
{json.dumps(pipeline[:10], indent=2)}

## Your task
Decide what to do next. Use the tools to:
1. **invoke_job_search** — find jobs, draft applications, build role maps
2. **invoke_freelance** — check freelance/gig opportunities
3. **web_search** — search job boards, company sites, gig listings
4. **read_webpage** — read specific job postings or pages

Be proactive. If it's morning and job_search is enabled, consider scanning for new jobs. If the pipeline is empty, find some. If there are new pipeline items, consider drafting applications.

Keep responses concise. After using tools, summarize what you did and what the user should do next (e.g. "Found 3 jobs. Review them and say APPLY 1 to draft.").
"""

    client = LLMClient.from_env()
    messages = [{"role": "user", "content": "What should we do next to help the user earn money? Use the tools and then summarize."}]

    # LLM loop with tool use (up to 5 rounds)
    max_rounds = 5
    for _ in range(max_rounds):
        response = client.create(messages, ORCHESTRATOR_TOOLS, system)

        if response.stop_reason == "end_turn":
            set_last_run("orchestrator_tick")
            return {"action": "response", "text": response.text or ""}

        # tool_use: execute and feed results back
        results = []
        for call in response.tool_calls:
            name = call["name"]
            inp = call["input"]
            executor = TOOL_EXECUTORS.get(name)
            if executor:
                try:
                    out = executor(inp)
                    results.append({"tool": name, "result": out})
                    log_action(name, inp, json.dumps(out)[:500])
                except Exception as e:
                    results.append({"tool": name, "error": str(e)})

        # Feed tool results back — format depends on provider (Anthropic vs OpenAI-compat)
        result_strs = [json.dumps(r.get("result", r) if "result" in r else {"error": r.get("error", "")}) for r in results]
        provider = getattr(client, "provider", "") or getattr(response, "provider", "")
        if provider == "claude" and hasattr(client, "assistant_message_from_raw") and response.raw:
            messages.append(client.assistant_message_from_raw(response.raw))
        else:
            # OpenAI-compat (Groq, etc.): assistant needs content + tool_calls
            asst = {"role": "assistant", "content": response.text or ""}
            if response.tool_calls:
                asst["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["input"])}}
                    for c in response.tool_calls
                ]
            messages.append(asst)
        messages.extend(client.build_tool_result_messages(response.tool_calls, result_strs))

    set_last_run("orchestrator_tick")
    return {"action": "max_rounds", "text": "Reached max tool rounds."}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Money-earning orchestrator")
    parser.add_argument("--loop", nargs="?", const=30, type=int, metavar="MIN",
                        help="Run continuously every N minutes (default 30)")
    args = parser.parse_args()

    if args.loop:
        import time
        interval = args.loop * 60
        print(f"Orchestrator running every {args.loop} min. Ctrl+C to stop.")
        while True:
            try:
                out = run_tick()
                print(f"[{datetime.now().isoformat()}] {out.get('action', '?')}: {out.get('text', '')[:200]}...")
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error: {e}")
            time.sleep(interval)
    else:
        out = run_tick()
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
