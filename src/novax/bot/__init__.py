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
    onboarding_done_text,
    onboarding_pairs_text,
    onboarding_score_text,
    onboarding_sessions_text,
    render_command,
    start_text,
    unknown_text,
)
from .models import DEFAULT_MIN_SCORE, SubscriptionTier, User, UserPrefs
from .onboarding import (
    AVAILABLE_PAIRS,
    AVAILABLE_SESSIONS,
    CB_DONE,
    CB_PREFIX_PAIR,
    CB_PREFIX_SCORE,
    CB_PREFIX_SES,
    SCORE_OPTIONS,
    OnboardingState,
    OnboardingStep,
    advance_pairs,
    advance_sessions,
    initial_state,
    pairs_keyboard,
    prefs_to_state,
    score_keyboard,
    sessions_keyboard,
    set_score,
    state_to_prefs,
    toggle_pair,
    toggle_session,
)
from .registry import (
    InMemoryUserRepository,
    UserNotFoundError,
    UserRepository,
    ensure_user,
)

__all__ = [
    "AVAILABLE_PAIRS",
    "AVAILABLE_SESSIONS",
    "CB_DONE",
    "CB_PREFIX_PAIR",
    "CB_PREFIX_SCORE",
    "CB_PREFIX_SES",
    "DEFAULT_MIN_SCORE",
    "DISCLAIMER",
    "BotConfig",
    "InMemoryUserRepository",
    "MissingTokenError",
    "OnboardingState",
    "OnboardingStep",
    "SCORE_OPTIONS",
    "SubscriptionTier",
    "User",
    "UserNotFoundError",
    "UserPrefs",
    "UserRepository",
    "advance_pairs",
    "advance_sessions",
    "disclaimer_text",
    "ensure_user",
    "help_text",
    "initial_state",
    "load_bot_config",
    "onboarding_done_text",
    "onboarding_pairs_text",
    "onboarding_score_text",
    "onboarding_sessions_text",
    "pairs_keyboard",
    "prefs_to_state",
    "render_command",
    "score_keyboard",
    "sessions_keyboard",
    "set_score",
    "start_text",
    "state_to_prefs",
    "toggle_pair",
    "toggle_session",
    "unknown_text",
]
