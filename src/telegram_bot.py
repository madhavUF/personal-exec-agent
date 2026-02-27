"""
Telegram bot for the Personal AI Agent.

Uses python-telegram-bot in polling mode — no public IP or webhook needed.
Each Telegram user gets their own session (multi-turn conversation history).

Run standalone:  python -m src.telegram_bot
Or via start.sh alongside the FastAPI server.
"""

import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# Add project root to path so src.agent imports work when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import run_agent, clear_session

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

💬 *General*
• Anything else — recipes, math, advice, explanations

⚙️ *Commands*
/start — welcome message
/reset — clear conversation history
/help or /tools — this menu
""".strip()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    if not query:
        return

    user_id = update.effective_user.id
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


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
