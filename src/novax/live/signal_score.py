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

__all__ = ["SignalScore", "score_signal", "confidence_label"]

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
    """Immutable signal quality score with per-component breakdown.

    total = structure + momentum + session + cost
    Each component uses the weight passed to score_signal() as its ceiling.
    Default ceiling matches STATIC_WEIGHTS (imported from signal_store).
    """

    total: int  # 0–100
    structure: int  # 0–weight.structure
    momentum: int  # 0–weight.momentum
    session: int  # 0–weight.session
    cost: int  # 0–weight.cost

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
            f"— structure={self.structure} "
            f"momentum={self.momentum} "
            f"session={self.session} "
            f"cost={self.cost}"
        )


def confidence_label(confidence_pct: float, sample_size: int) -> str:
    """Human-readable confidence label for display in Telegram alerts."""
    if sample_size < 20:
        return f"⚪ Unproven ({sample_size} samples)"
    pct = round(confidence_pct * 100)
    if confidence_pct >= 0.65:
        return f"🟢 High ({pct}% win rate, n={sample_size})"
    if confidence_pct >= 0.52:
        return f"🟡 Moderate ({pct}% win rate, n={sample_size})"
    return f"🔴 Low ({pct}% win rate, n={sample_size})"


def score_signal(
    result: MultiTFScanResult,
    now: datetime,
    *,
    w_structure: int = 30,
    w_momentum: int = 30,
    w_session: int = 20,
    w_cost: int = 20,
) -> SignalScore:
    """Compute a decomposable score for a MultiTFScanResult.

    Each component's maximum points equals the corresponding weight parameter,
    so the total is always ≤ w_structure + w_momentum + w_session + w_cost.
    Pass optimised weights from SignalStore.suggest_weights() once available.

    All four components are computed independently so that any one of them
    can be improved without touching the others.
    """
    structure = _score_structure(result, w_structure)
    momentum = _score_momentum(result, w_momentum)
    session = _score_session(now, w_session)
    cost = _score_cost(result, w_cost)

    total = structure + momentum + session + cost
    return SignalScore(
        total=min(total, 100),
        structure=structure,
        momentum=momentum,
        session=session,
        cost=cost,
    )


# ── Component scorers ────────────────────────────────────────────────────────


def _score_structure(result: MultiTFScanResult, ceiling: int) -> int:
    """Structure component — 0 to ceiling (default 30).

    Points are distributed proportionally to ceiling so that changing
    the weight via suggest_weights() scales all components together.

    Uses h4_trend (EMA50 direction) — the same signal that gates confluence —
    so scoring and confluence gate are always evaluating the same condition.

    Rules (at ceiling=30)
    ---------------------
    50%  4H EMA50 trend is non-FLAT
    33%  1H GoldPullback confirms same direction
    17%  15M EMACross also confirms (triple-TF)
    """
    raw = 0
    if result.h4_trend != Signal.FLAT:
        raw += 15
    if result.h1.signal == result.h4_trend and result.h4_trend != Signal.FLAT:
        raw += 10
    if result.m15.signal == result.h4_trend and result.h4_trend != Signal.FLAT:
        raw += 5
    # Scale: raw is out of 30; scale to ceiling
    return min(round(raw * ceiling / 30), ceiling)


def _score_momentum(result: MultiTFScanResult, ceiling: int) -> int:
    """Momentum component — 0 to ceiling (default 30).

    Rules (at ceiling=30)
    ---------------------
    50%  Entry price produced (strategy has a level)
    33%  SL defined at a logical level
    17%  TP defined (complete setup)
    """
    raw = 0
    if result.entry_price is not None:
        raw += 15
    if result.sl is not None:
        raw += 10
    if result.tp is not None:
        raw += 5
    return min(round(raw * ceiling / 30), ceiling)


def _score_session(now: datetime, ceiling: int) -> int:
    """Session context component — 0 to ceiling (default 20).

    London–NY overlap > London > NY > Asia > off-hours.
    Proportionally scaled to ceiling.
    """
    utc = now.astimezone(UTC)
    weekday = utc.weekday()  # 0=Mon … 4=Fri
    hour = utc.hour

    if weekday >= 5:
        return 0

    # Raw out of 20
    if 13 <= hour < 17:
        raw = 20  # London–NY overlap
    elif 8 <= hour < 13:
        raw = 16  # London only
    elif 17 <= hour < 22:
        raw = 14  # NY only
    elif 0 <= hour < 8:
        raw = 8  # Asia
    else:
        raw = 0  # dead zone 22–24

    return min(round(raw * ceiling / 20), ceiling)


def _score_cost(result: MultiTFScanResult, ceiling: int) -> int:
    """Cost / risk-reward component — 0 to ceiling (default 20).

    Rules (at ceiling=20)
    ---------------------
    50%  SL ≥ MIN_SL_PIPS from entry (trade covers spread cost)
    50%  R:R ≥ MIN_RR (reward justifies the risk)
    """
    if result.entry_price is None or result.sl is None:
        return 0

    raw = 0
    sl_pips = abs(result.entry_price - result.sl) / _XAUUSD_PIP
    if sl_pips >= _MIN_SL_PIPS:
        raw += 10
    if result.tp is not None and sl_pips > 0:
        tp_pips = abs(result.tp - result.entry_price) / _XAUUSD_PIP
        if tp_pips / sl_pips >= _MIN_RR:
            raw += 10

    return min(round(raw * ceiling / 20), ceiling)
