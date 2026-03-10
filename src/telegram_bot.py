"""
Telegram bot for the Personal AI Agent.

Uses python-telegram-bot in polling mode — no public IP or webhook needed.
Each Telegram user gets their own session (multi-turn conversation history).

Run standalone:  python -m src.telegram_bot
Or via start.sh alongside the FastAPI server.
"""

import base64
import io
import logging
import os
import sys

from src.env_loader import load_env
load_env()

from PIL import Image

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# Add project root to path so src.agent imports work when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import run_agent, clear_session
from src.goals import register_user, get_all_chat_ids, get_today_goals, format_goals_status
from src.morning_brief import generate_morning_brief

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Map Telegram user ID → agent session ID
_user_sessions: dict[int, str] = {}


def _session_id_for(user_id: int) -> str:
    """Return a stable session ID string for a Telegram user."""
    if user_id not in _user_sessions:
        import uuid
        _user_sessions[user_id] = f"telegram-{user_id}-{uuid.uuid4().hex[:8]}"
    return _user_sessions[user_id]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"Hey {name}! I'm your personal AI assistant.\n\n"
        "I can help you with:\n"
        "• Your documents & personal info\n"
        "• Google Calendar\n"
        "• Gmail (read, search, draft, send)\n"
        "• General questions\n\n"
        "Just send me a message. Use /reset to start a fresh conversation."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in _user_sessions:
        clear_session(_user_sessions[user_id])
        del _user_sessions[user_id]
    await update.message.reply_text("Conversation cleared. Fresh start!")


HELP_TEXT = """
*Personal AI Assistant — What I can do*

📄 *Documents & Notes*
• Search anything you've saved: _"What's my license number?"_
• Save new info: _"Save this meal plan"_ / _"Remember my wifi is XYZ"_
• Retrieve later: _"What meal plan did I save?"_

📅 *Calendar*
• _"What's on my calendar this week?"_
• _"Do I have meetings tomorrow?"_
• _"What about next month?"_ _(remembers context)_

✉️ *Email*
• _"Check my recent emails"_
• _"Search emails from John"_
• _"Draft an email to x@y.com saying hello"_
• _"Send an email to x@y.com"_ _(explicitly say send)_

📷 *Photos & Images*
• Send any photo with a caption question: _"Is this plant dead?"_
• No caption needed — it will describe the image automatically
• Works for plants, receipts, labels, anything visual

💬 *General*
• Anything else — recipes, math, advice, explanations

🎯 *Daily Goals*
• Set goals when prompted at 8 AM, or anytime: _"My 3 goals: 1. X 2. Y 3. Z"_
• Mark complete: _"Goal 1 is done"_ / _"Finished the second one"_
• Check status anytime with /goals
• Check-ins at 12 PM, 3 PM, 6 PM · Summary at 8 PM

⚙️ *Commands*
/start — welcome message
/reset — clear conversation history
/goals — see today's goals
/brief — get your morning brief now (also runs at 8 AM)
/help or /tools — this menu
""".strip()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    goals = get_today_goals(user_id)
    if not goals:
        await update.message.reply_text(
            "No goals set for today yet.\n\nSend me your 3 goals and I'll track them!"
        )
    else:
        await update.message.reply_text(
            f"*Today's Goals*\n\n{format_goals_status(goals)}",
            parse_mode="Markdown"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    if not query:
        return

    user_id = update.effective_user.id
    # Register chat_id so the scheduler can send proactive messages
    register_user(user_id, update.effective_chat.id, update.effective_user.username)
    session_id = _session_id_for(user_id)

    # Show typing indicator while agent runs
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        result = run_agent(query, session_id=session_id)
        answer = result.get("answer", "No response.")
        intent = result.get("intent", "general")
        sources = result.get("sources", [])

        # Build reply: intent label + answer + sources
        intent_labels = {
            "documents": "📄 Documents",
            "calendar":  "📅 Calendar",
            "email":     "✉️ Email",
            "goals":     "🎯 Goals",
            "general":   "💬 General",
        }
        label = intent_labels.get(intent, "💬 General")

        text = f"_{label}_\n\n{answer}"
        if sources:
            text += f"\n\n_Sources: {', '.join(sources)}_"

        # Telegram max message length is 4096 chars
        if len(text) > 4096:
            text = text[:4090] + "…"

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Agent error for user %s", user_id)
        await update.message.reply_text(f"Sorry, something went wrong: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Use caption as the query, or a default if no caption provided
    query = (update.message.caption or "").strip() or "What's in this image? Describe it and answer any questions."

    user_id = update.effective_user.id
    register_user(user_id, update.effective_chat.id, update.effective_user.username)
    session_id = _session_id_for(user_id)

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        # Download the highest-resolution version Telegram provides
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        raw_bytes = await tg_file.download_as_bytearray()

        # Resize to max 800px — keeps quality, cuts token cost by ~60-70%
        img = Image.open(io.BytesIO(bytes(raw_bytes)))
        img.thumbnail((800, 800), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        image_data = {"data": image_b64, "media_type": "image/jpeg"}

        result = run_agent(query, session_id=session_id, image_data=image_data)
        answer = result.get("answer", "No response.")
        intent = result.get("intent", "general")
        sources = result.get("sources", [])

        intent_labels = {
            "documents": "📄 Documents",
            "calendar":  "📅 Calendar",
            "email":     "✉️ Email",
            "general":   "💬 General",
        }
        label = intent_labels.get(intent, "💬 General")
        text = f"_{label}_\n\n{answer}"
        if sources:
            text += f"\n\n_Sources: {', '.join(sources)}_"
        if len(text) > 4096:
            text = text[:4090] + "…"

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Photo agent error for user %s", user_id)
        await update.message.reply_text(f"Sorry, something went wrong: {e}")


# ---------------------------------------------------------------------------
# Scheduler jobs — proactive messages sent on a schedule
# All times are US/Central (Austin, TX).  APScheduler handles DST.
# ---------------------------------------------------------------------------

async def job_morning_prompt(context) -> None:
    """8:00 AM — LLM-generated personalized morning brief."""
    for user in get_all_chat_ids():
        try:
            user_id = int(user["user_id"])
            name = os.getenv("USER_DISPLAY_NAME") or user.get("username") or "there"
            brief = generate_morning_brief(user_id, user_name=name)
            # Telegram max 4096 chars
            if len(brief) > 4096:
                brief = brief[:4090] + "…"
            await context.bot.send_message(
                chat_id=user["chat_id"],
                text=brief,
                parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Morning brief failed for chat_id %s", user["chat_id"])


async def job_checkin(context) -> None:
    """Noon / 3 PM / 6 PM — check in on goal progress."""
    for user in get_all_chat_ids():
        try:
            goals = get_today_goals(int(user["user_id"]))
            if not goals:
                continue  # No goals set, skip check-in
            done = sum(1 for g in goals if g["completed"])
            if done == len(goals):
                continue  # All done, no need to bug them
            status = format_goals_status(goals)
            await context.bot.send_message(
                chat_id=user["chat_id"],
                text=f"⏰ *Goal check-in!*\n\n{status}\n\nHow's it going? Let me know when you complete one.",
                parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Check-in failed for chat_id %s", user["chat_id"])


async def job_evening_wrap(context) -> None:
    """8:00 PM — end-of-day summary."""
    for user in get_all_chat_ids():
        try:
            goals = get_today_goals(int(user["user_id"]))
            if not goals:
                continue
            done = sum(1 for g in goals if g["completed"])
            status = format_goals_status(goals)
            if done == len(goals):
                msg = f"🎉 *You crushed it today!* All 3 goals done.\n\n{status}"
            elif done > 0:
                msg = f"💪 *Good effort today!* {done}/{len(goals)} goals completed.\n\n{status}"
            else:
                msg = f"Tomorrow is a new day. Here's where things stood:\n\n{status}"
            await context.bot.send_message(
                chat_id=user["chat_id"],
                text=msg,
                parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Evening wrap failed for chat_id %s", user["chat_id"])


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    import pytz
    CT = pytz.timezone("America/Chicago")

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    # --- Scheduled jobs (all times US/Central) ---
    jq = app.job_queue
    jq.run_daily(job_morning_prompt, time=__import__("datetime").time(8,  0, tzinfo=CT))
    jq.run_daily(job_checkin,        time=__import__("datetime").time(12, 0, tzinfo=CT))
    jq.run_daily(job_checkin,        time=__import__("datetime").time(15, 0, tzinfo=CT))
    jq.run_daily(job_checkin,        time=__import__("datetime").time(18, 0, tzinfo=CT))
    jq.run_daily(job_evening_wrap,   time=__import__("datetime").time(20, 0, tzinfo=CT))

    # --- Command & message handlers ---
    # /brief — manually trigger morning brief (for testing)
    async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        register_user(user_id, update.effective_chat.id, update.effective_user.username)
        name = os.getenv("USER_DISPLAY_NAME") or update.effective_user.username or "there"
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            brief = generate_morning_brief(user_id, user_name=name)
            if len(brief) > 4096:
                brief = brief[:4090] + "…"
            await update.message.reply_text(brief, parse_mode="Markdown")
        except Exception as e:
            logger.exception("Brief failed")
            await update.message.reply_text(f"Sorry, brief failed: {e}")

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("goals", cmd_goals))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
