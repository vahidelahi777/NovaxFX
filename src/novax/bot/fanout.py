"""Per-user signal fan-out — pure matching and message formatting (Phase 0 · B1).

No telegram import. No import from novax.live. The signal is consumed through the
``SignalInfo`` / ``ScoreInfo`` structural protocols so this module stays decoupled
from the live package; any object that satisfies the protocol works.

Delivery wiring (asyncio, sleeps) lives in delivery.py.

B2 seam
-------
The next task (B2) will poll SignalStore for new PENDING signals and drive the
full fan-out loop.  The expected call site in the daemon or a background task::

    from novax.bot.fanout import select_recipients
    from novax.bot.delivery import deliver

    users = await repo.list_all()          # or sync list_all()
    recipients = select_recipients(signal, users, primary_session)
    asyncio.create_task(deliver(signal, recipients, bot_send))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .messages import DISCLAIMER
from .models import SubscriptionTier, User

__all__ = [
    "Recipient",
    "ScoreInfo",
    "SignalInfo",
    "format_signal_message",
    "select_recipients",
]


# ---------------------------------------------------------------------------
# Structural protocols — typed adapter so we never import novax.live
# ---------------------------------------------------------------------------


class ScoreInfo(Protocol):
    """Subset of SignalScore needed by fanout."""

    total: int
    label: str


class SignalInfo(Protocol):
    """Subset of StoredSignal needed by fanout."""

    symbol: str
    ts: datetime
    direction: str | None
    entry_price: float | None
    sl: float | None
    tp: float | None
    rr: float | None
    score: ScoreInfo
    confidence_label: str
    regime: str


# ---------------------------------------------------------------------------
# Recipient
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipient:
    """A user selected to receive a signal, with the applicable send delay."""

    user: User
    delay_seconds: int


# ---------------------------------------------------------------------------
# Fan-out selection
# ---------------------------------------------------------------------------


def select_recipients(
    signal: SignalInfo,
    users: list[User],
    session_of: Callable[[datetime], str | None],
    *,
    free_delay_seconds: int = 1800,
) -> list[Recipient]:
    """Return the users who should receive this signal, with per-tier delays.

    Filtering rules (all must hold for inclusion):
    - ``signal.symbol`` is in ``user.prefs.pairs``
    - ``session_of(signal.ts)`` is in ``user.prefs.sessions`` (None → excluded)
    - ``signal.score.total >= user.prefs.min_score``
    - ``user.banned`` is False

    Delay assignment:
    - FREE tier        → ``free_delay_seconds`` (default 30 min; commercial hook)
    - PREMIUM / PRO    → 0 (immediate)

    Args:
        signal: the emitted signal (any object satisfying SignalInfo).
        users: full list of registered users (from ``repo.list_all()``).
        session_of: maps a UTC datetime to a session name (e.g. "LONDON") or
            None when the market is off-hours.  Caller is responsible for
            normalising session names to match UserPrefs conventions.
        free_delay_seconds: delay applied to FREE-tier users.
    """
    session = session_of(signal.ts)
    if session is None:
        return []

    recipients: list[Recipient] = []
    for user in users:
        if user.banned:
            continue
        if signal.symbol not in user.prefs.pairs:
            continue
        if session not in user.prefs.sessions:
            continue
        if signal.score.total < user.prefs.min_score:
            continue
        delay = (
            0
            if user.tier in (SubscriptionTier.PREMIUM, SubscriptionTier.PRO)
            else free_delay_seconds
        )
        recipients.append(Recipient(user=user, delay_seconds=delay))
    return recipients


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_signal_message(sig: SignalInfo) -> str:
    """Format a signal into a user-facing Telegram Markdown message.

    Pure: no network, no side effects.
    """
    direction = sig.direction or "FLAT"
    entry = f"{sig.entry_price:.2f}" if sig.entry_price is not None else "—"
    sl = f"{sig.sl:.2f}" if sig.sl is not None else "—"
    tp = f"{sig.tp:.2f}" if sig.tp is not None else "—"
    rr = f"{sig.rr:.2f}" if sig.rr is not None else "—"

    return (
        f"*{sig.symbol} — {direction}*\n\n"
        f"Entry:  `{entry}`\n"
        f"SL:     `{sl}`\n"
        f"TP:     `{tp}`\n"
        f"R:R:    `{rr}`\n\n"
        f"Score:  {sig.score.total}/100 [{sig.score.label}]\n"
        f"Conf:   {sig.confidence_label}\n"
        f"Regime: {sig.regime}\n\n"
        f"{DISCLAIMER}"
    )
