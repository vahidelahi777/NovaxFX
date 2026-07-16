"""python-telegram-bot application wiring for the NovaxFX product bot.

This is the only module that imports ``telegram`` — keep it thin. All reply
text comes from :mod:`novax.bot.messages` (pure, tested). Run via
``scripts/run_bot.py`` after installing the optional dependency group:

    pip install -e ".[bot]"

The bot runs alongside the existing production daemon; it does not touch the
research engine or send trading orders (that arrives in later Phase 0 tasks).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from . import messages
from .config import BotConfig, load_bot_config

__all__ = ["build_application", "run"]

logger = logging.getLogger("novax.bot")

_PARSE_MODE = "Markdown"


async def _reply(update: Update, text: str) -> None:
    if update.message is not None:
        await update.message.reply_text(text, parse_mode=_PARSE_MODE)


async def _start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    first_name = user.first_name if user is not None else None
    await _reply(update, messages.start_text(first_name))


async def _help(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.help_text())


async def _disclaimer(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.disclaimer_text())


async def _unknown(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.unknown_text())


def build_application(config: BotConfig) -> Application:  # type: ignore[type-arg]
    """Construct and wire the Telegram application (no network I/O yet)."""
    app = Application.builder().token(config.token).build()
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CommandHandler("help", _help))
    app.add_handler(CommandHandler("disclaimer", _disclaimer))
    app.add_handler(MessageHandler(filters.COMMAND, _unknown))
    return app


def run() -> None:
    """Entry point: load config, build the app, and start long-polling."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config = load_bot_config()
    app = build_application(config)
    logger.info("Starting NovaxFX product bot (polling); admins=%s", sorted(config.admin_ids))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
