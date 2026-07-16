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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import messages, onboarding
from .config import BotConfig, load_bot_config
from .registry import InMemoryUserRepository, UserRepository, ensure_user

__all__ = ["build_application", "run"]

logger = logging.getLogger("novax.bot")

_PARSE_MODE = "Markdown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_markup(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=cd) for label, cd in row] for row in rows]
    )


async def _reply(update: Update, text: str) -> None:
    if update.message is not None:
        await update.message.reply_text(text, parse_mode=_PARSE_MODE)


def _repo(context: ContextTypes.DEFAULT_TYPE) -> UserRepository | None:
    return context.application.bot_data.get("repo")  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    first_name = user.first_name if user is not None else None
    await _reply(update, messages.start_text(first_name))

    repo = _repo(context)
    if repo is not None and user is not None:
        ensure_user(repo, user.id, first_name=first_name, username=user.username)
        state = onboarding.initial_state()
        context.user_data["ob_state"] = state
        markup = _build_markup(onboarding.pairs_keyboard(state))
        if update.message is not None:
            await update.message.reply_text(
                messages.onboarding_pairs_text(),
                reply_markup=markup,
                parse_mode=_PARSE_MODE,
            )


async def _help(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.help_text())


async def _disclaimer(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.disclaimer_text())


async def _settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = _repo(context)
    user = update.effective_user
    if repo is not None and user is not None:
        existing = repo.get(user.id)
        state = (
            onboarding.prefs_to_state(existing.prefs)
            if existing is not None
            else onboarding.initial_state()
        )
    else:
        state = onboarding.initial_state()
    context.user_data["ob_state"] = state
    markup = _build_markup(onboarding.pairs_keyboard(state))
    if update.message is not None:
        await update.message.reply_text(
            messages.onboarding_pairs_text(),
            reply_markup=markup,
            parse_mode=_PARSE_MODE,
        )


async def _unknown(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.unknown_text())


# ---------------------------------------------------------------------------
# Onboarding callback handlers
# ---------------------------------------------------------------------------


def _get_ob_state(context: ContextTypes.DEFAULT_TYPE) -> onboarding.OnboardingState:
    state = context.user_data.get("ob_state")
    if isinstance(state, onboarding.OnboardingState):
        return state
    return onboarding.initial_state()


async def _ob_pair_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    state = _get_ob_state(context)
    data: str = query.data or ""
    value = data[len(onboarding.CB_PREFIX_PAIR) :]

    if value == onboarding.CB_DONE:
        try:
            state = onboarding.advance_pairs(state)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.answer()
        context.user_data["ob_state"] = state
        markup = _build_markup(onboarding.sessions_keyboard(state))
        if query.message is not None:
            await query.message.edit_text(
                messages.onboarding_sessions_text(),
                reply_markup=markup,
                parse_mode=_PARSE_MODE,
            )
    else:
        state = onboarding.toggle_pair(state, value)
        context.user_data["ob_state"] = state
        await query.answer()
        markup = _build_markup(onboarding.pairs_keyboard(state))
        if query.message is not None:
            await query.message.edit_reply_markup(reply_markup=markup)


async def _ob_ses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    state = _get_ob_state(context)
    data: str = query.data or ""
    value = data[len(onboarding.CB_PREFIX_SES) :]

    if value == onboarding.CB_DONE:
        try:
            state = onboarding.advance_sessions(state)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.answer()
        context.user_data["ob_state"] = state
        markup = _build_markup(onboarding.score_keyboard())
        if query.message is not None:
            await query.message.edit_text(
                messages.onboarding_score_text(),
                reply_markup=markup,
                parse_mode=_PARSE_MODE,
            )
    else:
        state = onboarding.toggle_session(state, value)
        context.user_data["ob_state"] = state
        await query.answer()
        markup = _build_markup(onboarding.sessions_keyboard(state))
        if query.message is not None:
            await query.message.edit_reply_markup(reply_markup=markup)


async def _ob_score_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    state = _get_ob_state(context)
    data: str = query.data or ""
    value_str = data[len(onboarding.CB_PREFIX_SCORE) :]

    try:
        score = int(value_str)
        state = onboarding.set_score(state, score)
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return

    await query.answer()
    context.user_data["ob_state"] = state

    prefs = onboarding.state_to_prefs(state)
    repo = _repo(context)
    user = update.effective_user
    if repo is not None and user is not None:
        try:
            repo.set_prefs(user.id, prefs)
        except Exception:
            logger.warning("set_prefs failed for user %s — user not registered", user.id)

    if query.message is not None:
        await query.message.edit_text(
            messages.onboarding_done_text(prefs.pairs, prefs.sessions, prefs.min_score),
            parse_mode=_PARSE_MODE,
        )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_application(config: BotConfig, repo: UserRepository | None = None) -> Application:
    """Construct and wire the Telegram application (no network I/O yet)."""
    app = Application.builder().token(config.token).build()
    if repo is not None:
        app.bot_data["repo"] = repo
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CommandHandler("help", _help))
    app.add_handler(CommandHandler("disclaimer", _disclaimer))
    app.add_handler(CommandHandler("settings", _settings))
    app.add_handler(
        CallbackQueryHandler(_ob_pair_callback, pattern=f"^{onboarding.CB_PREFIX_PAIR}")
    )
    app.add_handler(CallbackQueryHandler(_ob_ses_callback, pattern=f"^{onboarding.CB_PREFIX_SES}"))
    app.add_handler(
        CallbackQueryHandler(_ob_score_callback, pattern=f"^{onboarding.CB_PREFIX_SCORE}")
    )
    app.add_handler(MessageHandler(filters.COMMAND, _unknown))
    return app


def run() -> None:
    """Entry point: load config, choose the repo, build the app, and start long-polling."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config = load_bot_config()
    repo: UserRepository
    if config.database_url is not None:
        from .db_postgres import connect_and_prepare  # lazy: psycopg optional at import time

        repo = connect_and_prepare(config.database_url)
        logger.info("User registry: PostgresUserRepository")
    else:
        repo = InMemoryUserRepository()
        logger.warning("DATABASE_URL not set — using InMemoryUserRepository (data lost on restart)")
    app = build_application(config, repo=repo)
    logger.info("Starting NovaxFX product bot (polling); admins=%s", sorted(config.admin_ids))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
