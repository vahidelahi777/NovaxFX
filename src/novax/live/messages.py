"""Telegram message formatters for all V2 event types.

All times are shown as 'YYYY-MM-DD HH:MM UTC / HH:MM IRST'.
"""

from __future__ import annotations

from datetime import datetime

from ..engine import Signal
from .intraday_tracker import BarLevels
from .london_sweep_scanner import SweepScanResult
from .multi_tf_scanner import MultiTFScanResult
from .tz_utils import fmt_both

__all__ = [
    "fmt_confluence_alert",
    "fmt_daily_report",
    "fmt_heartbeat",
    "fmt_market_close",
    "fmt_market_open",
    "fmt_market_update_4h",
    "fmt_session_open",
    "fmt_startup",
    "fmt_shutdown",
    "fmt_weekly_report",
    "fmt_weekly_performance",
    "fmt_cmd_start",
    "fmt_cmd_signal",
    "fmt_cmd_stats",
    "fmt_sweep_alert",
]


def fmt_confluence_alert(result: MultiTFScanResult) -> str:
    """Multi-TF confluence alert — fires at every 15M bar close."""
    direction = result.direction.value
    dir_emoji = "🟢" if result.direction == Signal.LONG else "🔴"

    sl_str = f"{result.sl:,.2f}" if result.sl is not None else "n/a"
    tp_str = f"{result.tp:,.2f}" if result.tp is not None else "n/a"

    rr_str = "n/a"
    if result.sl is not None and result.tp is not None and result.entry_price is not None:
        risk = abs(result.entry_price - result.sl)
        reward = abs(result.tp - result.entry_price)
        if risk > 0:
            rr_str = f"{reward / risk:.1f}"

    h1_emoji = "✅" if result.h1.signal == result.direction else "⚠️"
    m15_label = result.m15.signal.value if result.m15.signal != Signal.FLAT else "FLAT"
    entry_str = f"{result.entry_price:,.2f}" if result.entry_price is not None else "n/a"

    # Show 4H EMA trend (confluence gate) and BOS signal (institutional bonus)
    bos_label = result.h4.signal.value
    bos_emoji = "🏛" if result.h4.signal != Signal.FLAT else "—"
    sl_source = "BOS" if result.h4.sl is not None else "ATR"

    lines = [
        f"🔔 *{result.symbol} — Multi-TF Alert*",
        "",
        f"*Direction : {dir_emoji} {direction}*",
        "",
        f"4H EMA Trend  : ✅ {result.h4_trend.value}",
        f"4H BOS Signal : {bos_emoji} {bos_label}",
        f"  SL : {sl_str}  TP : {tp_str}  (RR {rr_str})  [{sl_source}]",
        "",
        f"1H Pullback   : {h1_emoji} {result.h1.signal.value}",
        f"15M EMA Cross : {m15_label}  ⏱",
        "",
        f"Entry ref : {entry_str}",
        f"Scanned   : {fmt_both(result.scanned_at)}",
    ]
    return "\n".join(lines)


def fmt_sweep_alert(result: SweepScanResult) -> str:
    """London open sweep-and-reject alert."""
    direction = result.direction.value
    dir_emoji = "🟢" if result.signal == Signal.LONG else "🔴"

    sl_str = f"{result.sl:,.2f}" if result.sl is not None else "n/a"
    tp_str = f"{result.tp:,.2f}" if result.tp is not None else "n/a"
    entry_str = f"{result.entry_price:,.2f}" if result.entry_price is not None else "n/a"
    ah_str = f"{result.asian_high:,.2f}" if result.asian_high is not None else "n/a"
    al_str = f"{result.asian_low:,.2f}" if result.asian_low is not None else "n/a"

    rr_str = "n/a"
    if result.sl is not None and result.tp is not None and result.entry_price is not None:
        risk = abs(result.entry_price - result.sl)
        reward = abs(result.tp - result.entry_price)
        if risk > 0:
            rr_str = f"{reward / risk:.1f}"

    lines = [
        f"🔔 *{result.symbol} — London Sweep Alert*",
        "",
        f"*Direction : {dir_emoji} {direction}*",
        "",
        f"Asian Range   : {al_str} — {ah_str}",
        f"Entry ref     : {entry_str}",
        f"SL : {sl_str}  TP : {tp_str}  (RR {rr_str})",
        "",
        f"Scanned : {fmt_both(result.scanned_at)}",
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
            f"Week H/L : {current_week.high:,.2f} / {current_week.low:,.2f}  (range ${rng:.2f})",
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
            f"Today H/L : {day_levels.high:,.2f} / {day_levels.low:,.2f}  (range ${rng:.2f})",
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


def fmt_heartbeat(
    symbol: str,
    now: datetime,
    next_event_types: list[str],
    next_event_at: datetime,
) -> str:
    """Hourly heartbeat — confirms the daemon is still alive."""
    next_str = ", ".join(next_event_types) if next_event_types else "unknown"
    lines = [
        "💓 *Novax FX Daemon — Heartbeat*",
        "",
        f"Symbol    : {symbol}",
        f"Time      : {fmt_both(now)}",
        f"Next event: *{next_str}*",
        f"Fires at  : {next_event_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


def fmt_startup(
    symbol: str,
    state_dir: str,
    next_event_types: list[str],
    next_event_at: datetime,
) -> str:
    """Sent once at daemon startup — confirms the container is alive."""
    next_str = ", ".join(next_event_types) if next_event_types else "unknown"
    lines = [
        "🟢 *Novax FX Daemon — STARTED*",
        "",
        f"Symbol    : {symbol}",
        f"Time      : {fmt_both(next_event_at)}",
        f"State dir : {state_dir}",
        "",
        f"Next event: *{next_str}*",
        f"Fires at  : {next_event_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


def fmt_shutdown(symbol: str, now: datetime) -> str:
    """Sent on clean SIGTERM / SIGINT shutdown."""
    lines = [
        "🔴 *Novax FX Daemon — STOPPED*",
        "",
        f"Symbol : {symbol}",
        f"Time   : {fmt_both(now)}",
        "",
        "Daemon received shutdown signal and exited cleanly.",
    ]
    return "\n".join(lines)


def fmt_market_update_4h(
    symbol: str,
    result: MultiTFScanResult,
    current_price: float,
    now: datetime,
) -> str:
    """4H market update — posted every 4H even when no trade signal."""
    trend_emoji = _signal_emoji(result.h4_trend)
    h1_emoji = _signal_emoji(result.h1.signal)
    m15_label = result.m15.signal.value if result.m15.signal != Signal.FLAT else "FLAT"

    bias_line = (
        f"*Confluence active: {trend_emoji} {result.direction.value}*"
        if result.confluence
        else "No confluence — watching for setup"
    )

    lines = [
        f"🕐 *{symbol} — 4H Market Update*",
        f"_{fmt_both(now)}_",
        "",
        f"Price     : {current_price:,.2f}",
        f"4H Trend  : {trend_emoji} {result.h4_trend.value}",
        f"1H Signal : {h1_emoji} {result.h1.signal.value}",
        f"15M       : {m15_label}",
        "",
        bias_line,
    ]
    if result.confluence and result.sl and result.tp:
        lines += [
            f"SL : {result.sl:,.2f}  TP : {result.tp:,.2f}",
        ]
    return "\n".join(lines)


def fmt_weekly_performance(
    symbol: str,
    total_signals: int,
    wins: int,
    losses: int,
    cum_pnl_pips: float,
    now: datetime,
) -> str:
    """Weekly P&L summary from paper trader — posted Friday."""
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0.0
    pnl_emoji = "🟢" if cum_pnl_pips >= 0 else "🔴"

    lines = [
        f"📈 *{symbol} — Weekly Performance*",
        f"_{fmt_both(now)}_",
        "",
        f"Signals this week : {total_signals}",
        f"Closed trades     : {closed}",
        f"Win / Loss        : {wins}W  {losses}L",
        f"Win rate          : {win_rate:.1f}%",
        f"P&L               : {pnl_emoji} {cum_pnl_pips:+.1f} pips",
        "",
        "_Paper trading results — not financial advice._",
    ]
    return "\n".join(lines)


def fmt_cmd_start(symbol: str) -> str:
    """Response to /start command."""
    lines = [
        "👋 *Welcome to Novax FX Signals*",
        "",
        f"Symbol: *{symbol}* (XAU/USD Gold)",
        "",
        "*Available commands:*",
        "/signal — current market state + active setup",
        "/stats  — signal performance this week",
        "/help   — show this message",
        "",
        "Signals fire automatically on confluence.",
        "Stay patient — quality over quantity.",
    ]
    return "\n".join(lines)


def fmt_cmd_signal(
    symbol: str,
    result: MultiTFScanResult,
    current_price: float,
    now: datetime,
) -> str:
    """Response to /signal command — current market state on demand."""
    trend_emoji = _signal_emoji(result.h4_trend)
    h1_emoji = _signal_emoji(result.h1.signal)
    m15_emoji = _signal_emoji(result.m15.signal)

    lines = [
        f"📊 *{symbol} — Current State*",
        f"_{fmt_both(now)}_",
        "",
        f"Price     : *{current_price:,.2f}*",
        "",
        f"4H Trend  : {trend_emoji} {result.h4_trend.value}",
        f"4H BOS    : {_signal_emoji(result.h4.signal)} {result.h4.signal.value}",
        f"1H Signal : {h1_emoji} {result.h1.signal.value}",
        f"15M       : {m15_emoji} {result.m15.signal.value}",
        "",
    ]
    if result.confluence:
        dir_emoji = "🟢" if result.direction == Signal.LONG else "🔴"
        sl_str = f"{result.sl:,.2f}" if result.sl else "n/a"
        tp_str = f"{result.tp:,.2f}" if result.tp else "n/a"
        lines += [
            f"*{dir_emoji} CONFLUENCE: {result.direction.value}*",
            f"SL : {sl_str}  TP : {tp_str}",
        ]
    else:
        lines.append("⚪ No confluence — waiting for alignment")
    return "\n".join(lines)


def fmt_cmd_stats(
    symbol: str,
    total: int,
    wins: int,
    losses: int,
    open_count: int,
    cum_pips: float,
    now: datetime,
) -> str:
    """Response to /stats command."""
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0.0
    pnl_emoji = "🟢" if cum_pips >= 0 else "🔴"

    lines = [
        f"📉 *{symbol} — Signal Stats*",
        f"_{fmt_both(now)}_",
        "",
        f"Total signals  : {total}",
        f"Closed trades  : {closed}",
        f"  ✅ TP hits   : {wins}",
        f"  ❌ SL hits   : {losses}",
        f"  ⏳ Open      : {open_count}",
        f"Win rate       : {win_rate:.1f}%",
        f"Cumulative P&L : {pnl_emoji} {cum_pips:+.1f} pips",
        "",
        "_Paper trading — not financial advice._",
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
