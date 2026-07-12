"""Telegram message formatters for all V2 event types.

All times are shown as 'YYYY-MM-DD HH:MM UTC / HH:MM IRST'.
"""

from __future__ import annotations

from datetime import datetime

from ..engine import Signal
from .intraday_tracker import BarLevels
from .multi_tf_scanner import MultiTFScanResult
from .tz_utils import fmt_both

__all__ = [
    "fmt_confluence_alert",
    "fmt_daily_report",
    "fmt_market_close",
    "fmt_market_open",
    "fmt_session_open",
    "fmt_weekly_report",
]


def fmt_confluence_alert(result: MultiTFScanResult) -> str:
    """Multi-TF confluence alert — fires at every 15M bar close."""
    direction = result.direction.value
    dir_emoji = "🟢" if result.direction == Signal.LONG else "🔴"

    sl_str = f"{result.sl:,.2f}" if result.sl is not None else "n/a"
    tp_str = f"{result.tp:,.2f}" if result.tp is not None else "n/a"

    rr_str = "n/a"
    if (
        result.sl is not None
        and result.tp is not None
        and result.entry_price is not None
    ):
        risk = abs(result.entry_price - result.sl)
        reward = abs(result.tp - result.entry_price)
        if risk > 0:
            rr_str = f"{reward / risk:.1f}"

    h1_emoji = "✅" if result.h1.signal == result.direction else "⚠️"
    m15_label = result.m15.signal.value if result.m15.signal != Signal.FLAT else "FLAT"
    entry_str = f"{result.entry_price:,.2f}" if result.entry_price is not None else "n/a"

    lines = [
        f"🔔 *{result.symbol} — Multi-TF Alert*",
        "",
        f"*Direction : {dir_emoji} {direction}*",
        "",
        f"4H BOS Retest : ✅ {result.h4.signal.value}",
        f"  SL : {sl_str}",
        f"  TP : {tp_str}  (RR {rr_str})",
        "",
        f"1H Pullback   : {h1_emoji} {result.h1.signal.value}  (confirmed)",
        f"15M EMA Cross : {m15_label}  ⏱ entry timing",
        "",
        f"Entry ref : {entry_str}",
        f"Scanned   : {fmt_both(result.scanned_at)}",
    ]
    return "\n".join(lines)


def fmt_market_open(
    symbol: str,
    prev_week: BarLevels | None,
    last_close: float,
    bos_state: str,
    scanned_at: datetime,
) -> str:
    """Sunday 22:00 UTC — Forex market open with previous-week H/L."""
    lines = [
        f"📈 *{symbol} — Market Open*",
        f"_{fmt_both(scanned_at)}_",
        "",
    ]
    if prev_week is not None:
        rng = prev_week.high - prev_week.low
        lines += [
            "*Previous week H/L:*",
            f"  High : {prev_week.high:,.2f}",
            f"  Low  : {prev_week.low:,.2f}",
            f"  Range: ${rng:.2f}",
            "",
        ]
    else:
        lines += ["Previous week levels: not available", ""]

    lines += [
        f"Last 4H close : {last_close:,.2f}",
        f"4H bias       : {_bos_label(bos_state)}",
        "",
        "Key levels:",
    ]
    if prev_week is not None:
        lines += [
            f"  Resistance : {prev_week.high:,.2f}  (prev week high)",
            f"  Support    : {prev_week.low:,.2f}  (prev week low)",
        ]
    lines += ["", _bos_watch(bos_state, has_ob=False)]
    return "\n".join(lines)


def fmt_market_close(
    symbol: str,
    current_week: BarLevels | None,
    last_close: float,
    scanned_at: datetime,
) -> str:
    """Friday 21:00 UTC — Forex market close with current-week H/L."""
    lines = [
        f"🔒 *{symbol} — Market Close (Week End)*",
        f"_{fmt_both(scanned_at)}_",
        "",
    ]
    if current_week is not None:
        rng = current_week.high - current_week.low
        lines += [
            f"*This week H/L (week of {current_week.label}):*",
            f"  High : {current_week.high:,.2f}",
            f"  Low  : {current_week.low:,.2f}",
            f"  Range: ${rng:.2f}",
        ]
    else:
        lines += ["This week levels: not available"]

    lines += [
        "",
        f"Last 4H close : {last_close:,.2f}",
        "",
        "Market closed.  Next open: Sunday 22:00 UTC / 01:30 IRST",
    ]
    return "\n".join(lines)


def fmt_weekly_report(
    symbol: str,
    current_week: BarLevels | None,
    bos_state: str,
    last_close: float,
    scanned_at: datetime,
) -> str:
    """Friday 21:00 UTC — Weekly analysis summary."""
    lines = [
        f"📊 *{symbol} — Weekly Report*",
        f"_{fmt_both(scanned_at)}_",
        "",
        f"4H Bias  : {_bos_label(bos_state)}",
    ]
    if current_week is not None:
        rng = current_week.high - current_week.low
        lines += [
            f"Week H/L : {current_week.high:,.2f} / {current_week.low:,.2f}"
            f"  (range ${rng:.2f})",
        ]
    lines += [
        f"Last close: {last_close:,.2f}",
        "",
        _bos_watch(bos_state, has_ob=False),
    ]
    return "\n".join(lines)


def fmt_session_open(
    symbol: str,
    session: str,
    current_price: float,
    h4_signal: Signal,
    h1_signal: Signal,
    scanned_at: datetime,
) -> str:
    """London (08:00 UTC / 11:30 IRST) or NY (13:00 UTC / 16:30 IRST) open alert."""
    if session == "London":
        teh_time = "11:30 IRST"
        flag = "🇬🇧"
    else:
        teh_time = "16:30 IRST"
        flag = "🇺🇸"

    h4_emoji = _signal_emoji(h4_signal)
    h1_emoji = _signal_emoji(h1_signal)
    agreement = "✅ Aligned" if h4_signal == h1_signal and h4_signal != Signal.FLAT else "⚠️ Mixed"

    lines = [
        f"{flag} *{symbol} — {session} Open*",
        f"_{fmt_both(scanned_at)} / {teh_time}_",
        "",
        f"Current price : {current_price:,.2f}",
        "",
        f"4H bias : {h4_emoji} {h4_signal.value}",
        f"1H bias : {h1_emoji} {h1_signal.value}",
        f"Signal  : {agreement}",
    ]
    return "\n".join(lines)


def fmt_daily_report(
    symbol: str,
    result: MultiTFScanResult,
    day_levels: BarLevels | None,
    scanned_at: datetime,
) -> str:
    """Daily report at 20:00 UTC / 23:30 IRST."""
    h4_emoji = _signal_emoji(result.h4.signal)
    h1_emoji = _signal_emoji(result.h1.signal)
    m15_label = result.m15.signal.value if result.m15.signal != Signal.FLAT else "FLAT"

    lines = [
        f"🌙 *{symbol} — Daily Report*",
        f"_{fmt_both(scanned_at)} / 23:30 IRST_",
        "",
    ]
    if day_levels is not None:
        rng = day_levels.high - day_levels.low
        lines += [
            f"Today H/L : {day_levels.high:,.2f} / {day_levels.low:,.2f}"
            f"  (range ${rng:.2f})",
        ]
    lines += [
        f"Last close: {result.h4.last_close:,.2f}",
        "",
        f"4H bias : {h4_emoji} {result.h4.signal.value}",
        f"1H bias : {h1_emoji} {result.h1.signal.value}",
        f"15M     : {m15_label}",
    ]
    if result.confluence:
        dir_emoji = "🟢" if result.direction == Signal.LONG else "🔴"
        sl_str = f"{result.sl:,.2f}" if result.sl else "n/a"
        tp_str = f"{result.tp:,.2f}" if result.tp else "n/a"
        lines += [
            "",
            f"*Confluence: {dir_emoji} {result.direction.value}*",
            f"  SL: {sl_str}  TP: {tp_str}",
        ]
    return "\n".join(lines)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _signal_emoji(sig: Signal) -> str:
    if sig == Signal.LONG:
        return "🟢"
    if sig == Signal.SHORT:
        return "🔴"
    return "⚪"


def _bos_label(state: str) -> str:
    return {
        "bos_up": "BOS_UP (bullish bias)",
        "bos_down": "BOS_DOWN (bearish bias)",
        "idle": "IDLE (no BOS yet)",
    }.get(state.lower(), state)


def _bos_watch(state: str, *, has_ob: bool) -> str:
    if state.lower() == "idle":
        return "Watch for: No clear bias — monitor for BOS."
    if state.lower() == "bos_up":
        note = "retest of OB → LONG entry" if has_ob else "pullback to support → LONG"
        return f"Watch for: BOS_UP — {note}"
    note = "retest of OB → SHORT entry" if has_ob else "bounce from resistance → SHORT"
    return f"Watch for: BOS_DOWN — {note}"
