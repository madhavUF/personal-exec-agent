"""
LLM-generated morning brief.

Fetches calendar, goals, emails, weather and uses an LLM to generate
a personalized morning brief. Replaces the fixed 8am template.
"""

import json
import os
from datetime import datetime

from src.env_loader import load_env
load_env()

from src.llm_client import LLMClient
from src.goals import get_today_goals, format_goals_status


def _get_calendar_today() -> list[dict]:
    """Fetch today's calendar events. Returns [] if not connected."""
    try:
        import calendar_integration
        if not calendar_integration.is_authenticated():
            return []
        events = calendar_integration.get_todays_events()
        return events or []
    except Exception:
        return []


def _get_recent_emails(max_results: int = 5) -> list[dict]:
    """Fetch recent emails. Returns [] if not connected."""
    try:
        import gmail_integration
        if not gmail_integration.is_authenticated():
            return []
        result = gmail_integration.get_recent_emails(max_results=max_results)
        if not result or "emails" not in result:
            return []
        emails = result["emails"]
        return [
            {"from": e.get("from", ""), "subject": e.get("subject", ""), "snippet": (e.get("snippet", "") or "")[:150]}
            for e in emails
        ]
    except Exception:
        return []


def _get_weather(location: str = None) -> str:
    """Fetch weather via web search. Returns '' if disabled."""
    try:
        from src.config import get_config
        loc = location or (get_config().get("morning_brief", {}) or {}).get("weather_location", "Austin, TX")
        from src.web_research import web_search
        from src.egress import allow_public_web_research
        if not allow_public_web_research():
            return ""
        out = web_search(f"weather {loc} today", max_results=3)
        results = out.get("results", [])
        if not results:
            return ""
        snippets = [r.get("snippet", "") for r in results if r.get("snippet")]
        return " | ".join(snippets[:2]) if snippets else ""
    except Exception:
        return ""


def generate_morning_brief(user_id: int, user_name: str = None) -> str:
    """
    Generate a personalized LLM morning brief.

    Args:
        user_id: Telegram user ID (for goals).
        user_name: Display name (e.g. from USER_DISPLAY_NAME or Telegram).

    Returns:
        Markdown-formatted morning brief string.
    """
    name = user_name or os.getenv("USER_DISPLAY_NAME", "there")
    today = datetime.now().strftime("%A, %B %d, %Y")

    # Gather context
    calendar = _get_calendar_today()
    goals = get_today_goals(user_id)
    emails = _get_recent_emails(5)
    weather = _get_weather()

    # Build context for LLM
    calendar_str = "No events today." if not calendar else "\n".join(
        f"- {e['summary']} ({e.get('start', '')[:16] if isinstance(e.get('start'), str) else ''})"
        for e in calendar
    )
    goals_str = format_goals_status(goals) if goals else "No goals set yet."
    emails_str = "No recent emails." if not emails else "\n".join(
        f"- From {e['from']}: {e['subject']} — {e['snippet']}..."
        for e in emails
    )
    weather_str = weather or "Weather not available."

    system = """You are a personal assistant writing a morning brief. Be concise, warm, and actionable.
Use Markdown for formatting (bold, lists). Keep it under 400 words.
End with a prompt for the user to set their 3 goals if they haven't yet, or a brief encouragement."""

    user_msg = f"""Generate a morning brief for {name}.

Today is {today}.

## Calendar (today)
{calendar_str}

## Goals (yesterday/today)
{goals_str}

## Recent emails (inbox)
{emails_str}

## Weather
{weather_str}

Write a personalized morning brief. Include:
1. A warm greeting
2. Today's schedule (if any meetings/events)
3. Email highlights (what needs attention, if anything)
4. Weather
5. Goals status or prompt to set 3 goals for today

Keep it scannable. Use bullet points. Be encouraging but not cheesy."""

    try:
        client = LLMClient.from_env()
        response = client.create(
            messages=[{"role": "user", "content": user_msg}],
            tools=[],  # No tools — simple completion
            system=system,
        )
        return (response.text or "").strip()
    except Exception as e:
        # Fallback to simple template if LLM fails
        return (
            f"Good morning, {name}! 🌅\n\n"
            f"*Today:* {today}\n\n"
            f"*Calendar:* {calendar_str}\n\n"
            f"*Goals:* {goals_str}\n\n"
            "What are your *3 goals for today?* Reply with them numbered:\n"
            "1. ...\n2. ...\n3. ..."
        )
