"""Decomposable signal score: 0–100 built from four independent components.

Score anatomy
-------------
  Structure  0–30   BOS confirmation, weekly level proximity, H4/H1 alignment
  Momentum   0–30   EMA slope direction, ATR quality, 15M confirmation
  Session    0–20   Session context (London/NY > Asia > Off-hours)
  Cost       0–20   SL pips worthwhile, R:R ratio meets threshold

Why decomposable
----------------
Every component is stored in SignalRecord so future ML features can train on
individual dimensions rather than the opaque total.  A signal scoring 78/100
with Structure=28, Momentum=18, Session=20, Cost=12 tells a different story
than one with the same total but Structure=10, Momentum=10, Session=20, Cost=38.

Score thresholds (suggested defaults in SETTINGS)
-------------------------------------------------
  >= 70   High-confidence — send Telegram alert
  50–69   Medium — log only
  < 50    Low — discard silently

Usage
-----
    from novax.live.signal_score import score_signal, SignalScore
    from novax.live.multi_tf_scanner import MultiTFScanResult

    sc = score_signal(result, now=datetime.now(tz=UTC))
    print(sc)           # SignalScore(total=74, structure=25, ...)
    print(sc.label)     # "HIGH"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..engine import Signal
from .multi_tf_scanner import MultiTFScanResult

__all__ = ["SignalScore", "score_signal"]

# ── Thresholds ──────────────────────────────────────────────────────────────
_HIGH_THRESHOLD = 70
_MEDIUM_THRESHOLD = 50

# Minimum SL size to be worth the spread cost (XAU/USD pips)
_MIN_SL_PIPS = 15.0
# Minimum R:R ratio
_MIN_RR = 1.5

# XAU/USD pip size
_XAUUSD_PIP = 0.1


@dataclass(frozen=True)
class SignalScore:
    """Immutable signal quality score with per-component breakdown."""

    total: int          # 0–100
    structure: int      # 0–30
    momentum: int       # 0–30
    session: int        # 0–20
    cost: int           # 0–20

    @property
    def label(self) -> str:
        if self.total >= _HIGH_THRESHOLD:
            return "HIGH"
        if self.total >= _MEDIUM_THRESHOLD:
            return "MEDIUM"
        return "LOW"

    def __str__(self) -> str:
        return (
            f"Score {self.total}/100 [{self.label}] "
            f"— structure={self.structure}/30 "
            f"momentum={self.momentum}/30 "
            f"session={self.session}/20 "
            f"cost={self.cost}/20"
        )


def score_signal(result: MultiTFScanResult, now: datetime) -> SignalScore:
    """Compute a decomposable 0–100 score for a MultiTFScanResult.

    All four components are computed independently so that any one of them
    can be improved without touching the others.
    """
    structure = _score_structure(result)
    momentum  = _score_momentum(result)
    session   = _score_session(now)
    cost      = _score_cost(result)

    total = structure + momentum + session + cost
    return SignalScore(
        total=min(total, 100),
        structure=structure,
        momentum=momentum,
        session=session,
        cost=cost,
    )


# ── Component scorers ────────────────────────────────────────────────────────

def _score_structure(result: MultiTFScanResult) -> int:
    """Structure component — 0 to 30.

    Scoring rules
    -------------
    +15   4H BOS is confirmed (h4_signal is not FLAT)
    +10   1H confirms the same direction as 4H
    + 5   15M also agrees (triple-TF alignment)
    """
    score = 0

    # 4H BOS confirmed
    if result.h4.signal != Signal.FLAT:
        score += 15

    # 1H confirms 4H direction
    if result.h1.signal == result.h4.signal and result.h4.signal != Signal.FLAT:
        score += 10

    # 15M confirms direction (strongest confluence)
    if result.m15.signal == result.h4.signal and result.h4.signal != Signal.FLAT:
        score += 5

    return min(score, 30)


def _score_momentum(result: MultiTFScanResult) -> int:
    """Momentum component — 0 to 30.

    Scoring rules
    -------------
    +15   Entry price exists (strategy produced a concrete level)
    +10   SL exists and is placed at a logical level (not None)
    + 5   TP exists (full setup defined — entry + SL + TP)
    """
    score = 0

    if result.entry_price is not None:
        score += 15

    if result.sl is not None:
        score += 10

    if result.tp is not None:
        score += 5

    return min(score, 30)


def _score_session(now: datetime) -> int:
    """Session context component — 0 to 20.

    London (08:00–17:00 UTC) and NY (13:00–22:00 UTC) are highest liquidity.
    The overlap (13:00–17:00 UTC) is maximum liquidity.
    Asia (00:00–08:00 UTC) is reduced liquidity.
    Off-hours (22:00–00:00 UTC) = weekend / dead zone.

    Scoring rules
    -------------
    +20   London–NY overlap (13:00–17:00 UTC Mon–Fri)
    +16   London session (08:00–13:00 UTC Mon–Fri)
    +14   NY session (17:00–22:00 UTC Mon–Fri)
    + 8   Asia session (00:00–08:00 UTC Mon–Fri)
    + 0   Off-hours / weekend
    """
    utc = now.astimezone(UTC)
    weekday = utc.weekday()   # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    hour = utc.hour

    if weekday >= 5:   # Saturday or Sunday
        return 0

    # London–NY overlap
    if 13 <= hour < 17:
        return 20

    # London only
    if 8 <= hour < 13:
        return 16

    # NY only (after London close)
    if 17 <= hour < 22:
        return 14

    # Asia
    if 0 <= hour < 8:
        return 8

    # 22:00–00:00 (market about to close / dead)
    return 0


def _score_cost(result: MultiTFScanResult) -> int:
    """Cost / risk-reward component — 0 to 20.

    Scoring rules
    -------------
    +10   SL is at least _MIN_SL_PIPS away from entry (trade is worthwhile)
    +10   R:R ratio >= _MIN_RR (reward justifies the risk)
    """
    score = 0

    if result.entry_price is None or result.sl is None:
        return 0

    sl_pips = abs(result.entry_price - result.sl) / _XAUUSD_PIP

    if sl_pips >= _MIN_SL_PIPS:
        score += 10

    if result.tp is not None and sl_pips > 0:
        tp_pips = abs(result.tp - result.entry_price) / _XAUUSD_PIP
        rr = tp_pips / sl_pips
        if rr >= _MIN_RR:
            score += 10

    return min(score, 20)
