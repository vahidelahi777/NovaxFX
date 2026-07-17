"""Onboarding flow — pure state machine and keyboard builders (Phase 0 · A3).

No telegram imports. State lives in ``context.user_data["ob_state"]`` inside
the bot application; ``app.py`` converts the keyboard rows into Telegram
``InlineKeyboardMarkup`` objects.

Callback-data format (parsed by ``app.py`` pattern handlers):
  ob_pair:<PAIR>        toggle a currency pair
  ob_pair:__DONE__      confirm pair selection → advance to sessions step
  ob_ses:<SESSION>      toggle a trading session
  ob_ses:__DONE__       confirm session selection → advance to score step
  ob_score:<INT>        select min-score threshold → complete onboarding
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .models import DEFAULT_MIN_SCORE, UserPrefs

__all__ = [
    "AVAILABLE_PAIRS",
    "AVAILABLE_SESSIONS",
    "CB_DONE",
    "CB_PREFIX_PAIR",
    "CB_PREFIX_SCORE",
    "CB_PREFIX_SES",
    "OnboardingState",
    "OnboardingStep",
    "SCORE_OPTIONS",
    "advance_pairs",
    "advance_sessions",
    "initial_state",
    "pairs_keyboard",
    "prefs_to_state",
    "score_keyboard",
    "sessions_keyboard",
    "set_score",
    "state_to_prefs",
    "toggle_pair",
    "toggle_session",
]

AVAILABLE_PAIRS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
AVAILABLE_SESSIONS: tuple[str, ...] = ("ASIA", "LONDON", "NEWYORK", "OVERLAP")

_SESSION_LABELS: dict[str, str] = {"NEWYORK": "New York"}
SCORE_OPTIONS: tuple[int, ...] = (50, 60, 70, 80, 90)

CB_PREFIX_PAIR = "ob_pair:"
CB_PREFIX_SES = "ob_ses:"
CB_PREFIX_SCORE = "ob_score:"
CB_DONE = "__DONE__"  # sentinel appended to pair/session "Done" buttons


class OnboardingStep(StrEnum):
    PAIRS = "pairs"
    SESSIONS = "sessions"
    SCORE = "score"
    DONE = "done"


@dataclass(frozen=True)
class OnboardingState:
    """Immutable snapshot of where a user is in the onboarding flow."""

    selected_pairs: frozenset[str] = frozenset()
    selected_sessions: frozenset[str] = frozenset()
    selected_score: int | None = None
    step: OnboardingStep = OnboardingStep.PAIRS


def initial_state() -> OnboardingState:
    return OnboardingState()


def prefs_to_state(prefs: UserPrefs) -> OnboardingState:
    """Build an OnboardingState pre-populated from existing UserPrefs (for /settings)."""
    return OnboardingState(
        selected_pairs=prefs.pairs,
        selected_sessions=prefs.sessions,
        selected_score=prefs.min_score,
        step=OnboardingStep.PAIRS,
    )


def toggle_pair(state: OnboardingState, pair: str) -> OnboardingState:
    """Toggle ``pair`` in/out of the selection. No-op for unrecognised pairs."""
    if pair not in AVAILABLE_PAIRS:
        return state
    return replace(state, selected_pairs=state.selected_pairs ^ frozenset({pair}))


def toggle_session(state: OnboardingState, session: str) -> OnboardingState:
    """Toggle ``session`` in/out of the selection. No-op for unrecognised sessions."""
    if session not in AVAILABLE_SESSIONS:
        return state
    return replace(state, selected_sessions=state.selected_sessions ^ frozenset({session}))


def advance_pairs(state: OnboardingState) -> OnboardingState:
    """Confirm pair selection and advance to the sessions step.

    Raises:
        ValueError: if no pairs are selected.
    """
    if not state.selected_pairs:
        raise ValueError("Select at least one pair before continuing.")
    return replace(state, step=OnboardingStep.SESSIONS)


def advance_sessions(state: OnboardingState) -> OnboardingState:
    """Confirm session selection and advance to the score step.

    Raises:
        ValueError: if no sessions are selected.
    """
    if not state.selected_sessions:
        raise ValueError("Select at least one session before continuing.")
    return replace(state, step=OnboardingStep.SCORE)


def set_score(state: OnboardingState, score: int) -> OnboardingState:
    """Record the min-score threshold and mark onboarding complete.

    Raises:
        ValueError: if ``score`` is not in ``SCORE_OPTIONS``.
    """
    if score not in SCORE_OPTIONS:
        raise ValueError(f"score must be one of {SCORE_OPTIONS}, got {score}")
    return replace(state, selected_score=score, step=OnboardingStep.DONE)


def state_to_prefs(state: OnboardingState) -> UserPrefs:
    """Convert onboarding state to ``UserPrefs`` (uses defaults for empty selections)."""
    pairs = state.selected_pairs or frozenset({"XAUUSD"})
    sessions = state.selected_sessions or frozenset({"LONDON", "NEWYORK"})
    score = state.selected_score if state.selected_score is not None else DEFAULT_MIN_SCORE
    return UserPrefs(pairs=pairs, sessions=sessions, min_score=score)


# ---------------------------------------------------------------------------
# Keyboard builders — return list[list[tuple[label, callback_data]]]
# ---------------------------------------------------------------------------


def pairs_keyboard(state: OnboardingState) -> list[list[tuple[str, str]]]:
    """One button per pair (one per row) then a Done button."""
    rows: list[list[tuple[str, str]]] = []
    for pair in AVAILABLE_PAIRS:
        prefix = "✅ " if pair in state.selected_pairs else ""
        rows.append([(f"{prefix}{pair}", f"{CB_PREFIX_PAIR}{pair}")])
    rows.append([("✔ Done", f"{CB_PREFIX_PAIR}{CB_DONE}")])
    return rows


def sessions_keyboard(state: OnboardingState) -> list[list[tuple[str, str]]]:
    """One button per session (one per row) then a Done button."""
    rows: list[list[tuple[str, str]]] = []
    for ses in AVAILABLE_SESSIONS:
        label = _SESSION_LABELS.get(ses, ses)
        prefix = "✅ " if ses in state.selected_sessions else ""
        rows.append([(f"{prefix}{label}", f"{CB_PREFIX_SES}{ses}")])
    rows.append([("✔ Done", f"{CB_PREFIX_SES}{CB_DONE}")])
    return rows


def score_keyboard() -> list[list[tuple[str, str]]]:
    """Score options in two rows (3 + 2), no Done needed (auto-advances)."""
    opts = [(str(s), f"{CB_PREFIX_SCORE}{s}") for s in SCORE_OPTIONS]
    return [opts[:3], opts[3:]]
