"""
Recruiter Agent — Finds jobs for you using your resume.

Uses resume-only context (config.yaml recruiter.resume_files) — separate from
main RAG. Web search for job discovery, adds matches to pipeline.

Run: python -m src.recruiter_agent
Or:  python -m src.recruiter_agent "Find PM roles in Austin"
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Project root
_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))

from src.env_loader import load_env
load_env()

import yaml
from src.llm_client import LLMClient
from src.config import get_recruiter_resume_files
from src.web_research import web_search, read_webpage
from src.egress import allow_public_web_research
from src.money_agent.state import add_pipeline_item, get_pipeline, log_action


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_instructions() -> dict:
    path = _PROJECT / "config" / "recruiter_instructions.yaml"
    if not path.is_file():
        return {"target_roles": ["Product Manager"], "location": "remote", "work_style": "remote"}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _tool_get_resume() -> dict:
    """Get the candidate's resume (recruiter's own context — resume only, not main RAG)."""
    parts = []
    for path in get_recruiter_resume_files():
        try:
            if path.suffix.lower() == ".md":
                content = path.read_text(encoding="utf-8")
            elif path.suffix.lower() == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(path))
                    content = "\n\n".join(p.extract_text() or "" for p in reader.pages)
                except Exception:
                    content = ""
            else:
                content = path.read_text(encoding="utf-8")
            if content.strip():
                parts.append({"title": path.stem, "content": content.strip(), "source": str(path.name)})
        except Exception as e:
            parts.append({"title": path.stem, "content": "", "source": str(path.name), "error": str(e)})
    if not parts:
        return {"results": [], "message": "No resume found. Add my_data/resume.md or configure recruiter.resume_files in config.yaml."}
    return {"results": parts}


def _tool_web_search(query: str, max_results: int = 5) -> dict:
    """Search the web for job listings."""
    if not allow_public_web_research():
        return {"error": "Web research disabled. Set ALLOW_PUBLIC_WEB_RESEARCH=true."}
    try:
        out = web_search(query, max_results=max_results)
        return {"results": out.get("results", [])}
    except Exception as e:
        return {"error": str(e)}


def _tool_read_webpage(url: str) -> dict:
    """Read a job posting or company page."""
    if not allow_public_web_research():
        return {"error": "Web research disabled."}
    try:
        text = read_webpage(url)
        return {"text": (text or "")[:8000]}
    except Exception as e:
        return {"error": str(e)}


def _tool_add_to_pipeline(title: str, url: str = None, company: str = None, raw: dict = None) -> dict:
    """Add a job to the pipeline for review."""
    try:
        rowid = add_pipeline_item(
            source="recruiter",
            title=title,
            url=url or "",
            company=company or "",
            raw=raw or {}
        )
        log_action("add_to_pipeline", {"title": title, "url": url, "company": company}, str(rowid))
        return {"success": True, "id": rowid, "message": f"Added: {title}"}
    except Exception as e:
        return {"error": str(e)}


RECRUITER_TOOLS = [
    {
        "name": "get_resume",
        "description": "Get the candidate's resume (experience, skills, background). Use this first to understand the candidate before searching for jobs.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "web_search",
        "description": "Search the web for job listings. Use queries like 'Product Manager remote Austin jobs' or 'Senior PM jobs LinkedIn'.",
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
        "description": "Read a job posting URL to get full details before adding to pipeline.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    },
    {
        "name": "add_to_pipeline",
        "description": "Add a job to the pipeline for the candidate to review. Call after finding a relevant job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Job title"},
                "url": {"type": "string", "description": "Job posting URL"},
                "company": {"type": "string", "description": "Company name"},
                "raw": {"type": "object", "description": "Extra details (optional)"}
            },
            "required": ["title"]
        }
    },
]

TOOL_EXECUTORS = {
    "get_resume": lambda inp: _tool_get_resume(),
    "web_search": lambda inp: _tool_web_search(inp["query"], inp.get("max_results", 5)),
    "read_webpage": lambda inp: _tool_read_webpage(inp["url"]),
    "add_to_pipeline": lambda inp: _tool_add_to_pipeline(
        inp["title"], inp.get("url"), inp.get("company"), inp.get("raw")
    ),
}


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------

def run_recruiter(query: str = None, max_iterations: int = 8) -> dict:
    """
    Run the recruiter agent.

    Args:
        query: Optional prompt, e.g. "Find PM roles in Austin". Default: "Find jobs matching my resume."
        max_iterations: Max tool-use rounds.

    Returns:
        {"answer": str, "pipeline_added": int}
    """
    instructions = _load_instructions()
    target_roles = instructions.get("target_roles", ["Product Manager"])
    location = instructions.get("location", "remote")
    work_style = instructions.get("work_style", "remote")
    pipeline = get_pipeline(limit=10)

    default_query = "Find jobs matching my resume and add the best matches to the pipeline."
    user_message = query or default_query

    system = f"""You are a recruiter for the candidate. Your job is to find relevant jobs and add them to the pipeline.

Today is {datetime.now().strftime("%A, %B %d, %Y")}.

## Instructions
- Target roles: {', '.join(target_roles)}
- Location: {location}
- Work style: {work_style}
- Constraints: {instructions.get('constraints', {})}

## Your workflow
1. **get_resume** to load the candidate's resume (experience, skills, background)
2. **web_search** for job listings (e.g. "{target_roles[0]} {location} jobs" or "remote PM jobs")
3. **read_webpage** on promising URLs to verify fit before adding
4. **add_to_pipeline** for each relevant job (title, url, company)

## Current pipeline (recent)
{json.dumps(pipeline[:5], indent=2)}

## Guidelines
- Add 3–5 quality matches per run. Prioritize relevance over quantity.
- Skip jobs that clearly don't match (wrong industry, location, level).
- Include the job URL so the candidate can apply.
- Summarize what you found at the end.
"""

    client = LLMClient.from_env()
    messages = [{"role": "user", "content": user_message}]
    pipeline_added = 0

    for _ in range(max_iterations):
        response = client.create(messages, RECRUITER_TOOLS, system)

        if response.stop_reason == "end_turn":
            return {
                "answer": response.text or "",
                "pipeline_added": pipeline_added,
            }

        # Execute tools
        results = []
        for call in response.tool_calls:
            name = call["name"]
            inp = call["input"]
            executor = TOOL_EXECUTORS.get(name)
            if executor:
                try:
                    out = executor(inp)
                    results.append(out)
                    if name == "add_to_pipeline" and out.get("success"):
                        pipeline_added += 1
                except Exception as e:
                    results.append({"error": str(e)})
            else:
                results.append({"error": f"Unknown tool: {name}"})

        # Feed back
        result_strs = [json.dumps(r) for r in results]
        provider = getattr(client, "provider", "") or getattr(response, "provider", "")
        if provider == "claude" and hasattr(client, "assistant_message_from_raw") and response.raw:
            messages.append(client.assistant_message_from_raw(response.raw))
        else:
            asst = {"role": "assistant", "content": response.text or ""}
            if response.tool_calls:
                asst["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["input"])}}
                    for c in response.tool_calls
                ]
            messages.append(asst)
        messages.extend(client.build_tool_result_messages(response.tool_calls, result_strs))

    return {
        "answer": "Reached max iterations. Check pipeline for any jobs added.",
        "pipeline_added": pipeline_added,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    out = run_recruiter(query)
    print(out.get("answer", ""))
    if out.get("pipeline_added", 0) > 0:
        print(f"\n✅ Added {out['pipeline_added']} job(s) to pipeline. View in data/money_agent.db or via API.")


if __name__ == "__main__":
    main()
