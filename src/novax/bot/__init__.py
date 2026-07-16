"""NovaxFX product bot — Phase 0 (interactive, multi-user).

Customer-facing surface layered on top of the existing research engine and live
daemon. Importing this package does NOT require the optional ``bot`` dependency
(python-telegram-bot / psycopg): only ``app.py`` imports telegram and only
``db_postgres.py`` imports psycopg, so pure logic (``config``, ``messages``,
``models``, ``registry``) stays testable without the network/DB stack installed.
"""

from __future__ import annotations

from .config import BotConfig, MissingTokenError, load_bot_config
from .messages import (
    DISCLAIMER,
    disclaimer_text,
    help_text,
    render_command,
    start_text,
    unknown_text,
)
from .models import DEFAULT_MIN_SCORE, SubscriptionTier, User, UserPrefs
from .registry import (
    InMemoryUserRepository,
    UserNotFoundError,
    UserRepository,
    ensure_user,
)

__all__ = [
    "DEFAULT_MIN_SCORE",
    "DISCLAIMER",
    "BotConfig",
    "InMemoryUserRepository",
    "MissingTokenError",
    "SubscriptionTier",
    "User",
    "UserNotFoundError",
    "UserPrefs",
    "UserRepository",
    "disclaimer_text",
    "ensure_user",
    "help_text",
    "load_bot_config",
    "render_command",
    "start_text",
    "unknown_text",
]
