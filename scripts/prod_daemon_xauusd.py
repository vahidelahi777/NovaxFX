"""Production daemon: multi-TF signal scanner with Telegram bot.

Event schedule (all UTC → IRST = UTC+3:30):
  Every 15M bar close  — Multi-TF confluence scan + alert (if confluence + score ≥ 70)
  Every 4H mark        — Market update (price + bias) even without a signal
  Sunday    22:00 UTC  — Market-open report                           (01:30 IRST Mon)
  Mon-Fri   08:00 UTC  — London-open session alert                   (11:30 IRST)
  Mon-Fri   13:00 UTC  — NY-open session alert                       (16:30 IRST)
  Mon-Fri   20:00 UTC  — Daily summary report                        (23:30 IRST)
  Friday    21:00 UTC  — Market-close + weekly report + P&L summary  (00:30 IRST Sat)

Bot commands (users can type in the Telegram bot chat):
  /start   — welcome message + command list
  /signal  — current market state on demand
  /stats   — this week's win rate and P&L
  /help    — same as /start

Required env vars:
  TWELVEDATA_API_KEY       — never passed as CLI arg or logged
  TELEGRAM_TOKEN           — bot token, never logged
  TELEGRAM_CHAT_ID         — trading signals channel
  TELEGRAM_NOTIF_CHAT_ID   — maintenance channel (startup/shutdown/errors)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from novax.bot.dispatch import dispatch_signal
from novax.bot.registry import UserRepository
from novax.data.ingest.twelvedata import fetch_bars
from novax.data.retry import retry_fetch
from novax.data.stream.resilient_stream import ResilientStream
from novax.data_sources import Bar
from novax.engine import BarView, Position, Signal
from novax.live import (
    STATIC_WEIGHTS,
    AlertStateStore,
    EventKind,
    EventScheduler,
    EventType,
    LevelStore,
    MultiTFScanner,
    MultiTFScanResult,
    NewsGate,
    PaperTrader,
    RiskGovernor,
    ScanResult,
    SignalRecord,
    SignalStatus,
    SignalStore,
    StoredSignal,
    WeeklyLevel,
    compute_day_levels,
    compute_week_levels,
    confidence_label,
    current_week_start,
    fmt_cmd_signal,
    fmt_cmd_start,
    fmt_cmd_stats,
    fmt_confluence_alert,
    fmt_daily_report,
    fmt_market_close,
    fmt_market_open,
    fmt_market_update_4h,
    fmt_session_open,
    fmt_shutdown,
    fmt_startup,
    fmt_sweep_alert,
    fmt_weekly_performance,
    fmt_weekly_report,
    make_signal_id,
    reconcile_on_boot,
    score_signal,
)
from novax.live.london_sweep_scanner import LondonSweepScanner
from novax.sessions import primary_session
from novax.strategies.weekly_bos_retest import WeeklyBOSRetest

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_ALERT_SCORE_THRESHOLD = 70  # raised from 65 — cut MEDIUM signals
_XAUUSD_PIP = 0.1

# ---------------------------------------------------------------------------
# Shared state (passed to command handlers via context.bot_data)
# ---------------------------------------------------------------------------


class _State:
    """All mutable daemon state in one place."""

    def __init__(
        self,
        symbol: str,
        scanner: MultiTFScanner,
        sweep_scanner: LondonSweepScanner,
        alert_store: AlertStateStore,
        level_store: LevelStore,
        signal_store: SignalStore,
        news_gate: NewsGate,
        paper_trader: PaperTrader,
        risk_governor: RiskGovernor,
        event_sched: EventScheduler,
        lookback_h4: int,
        lookback_h1: int,
        lookback_m15: int,
        api_key: str,
        chat_id: str,
        notif_chat_id: str,
        score_threshold: int,
        state_dir: Path,
        log: logging.Logger,
    ) -> None:
        self.symbol = symbol
        self.scanner = scanner
        self.sweep_scanner = sweep_scanner
        self.alert_store = alert_store
        self.level_store = level_store
        self.signal_store = signal_store
        self.news_gate = news_gate
        self.paper_trader = paper_trader
        self.risk_governor = risk_governor
        self.event_sched = event_sched
        self.lookback_h4 = lookback_h4
        self.lookback_h1 = lookback_h1
        self.lookback_m15 = lookback_m15
        self.api_key = api_key
        self.chat_id = chat_id
        self.notif_chat_id = notif_chat_id
        self.score_threshold = score_threshold
        self.state_dir = state_dir
        self.log = log
        self.consecutive_failures: int = 0
        self.last_result: MultiTFScanResult | None = None
        self.last_price: float | None = None
        self.repo: UserRepository | None = None
        self.stream_mode: bool = False
        self.stream_fallback: bool = False  # True when stream crashed → use scheduler


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging(log_file: str | None) -> logging.Logger:
    log = logging.getLogger("prod_daemon_xauusd")
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        rh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        rh.setFormatter(fmt)
        log.addHandler(rh)
    return log


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _fetch_all(
    symbol: str,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    api_key: str,
    log: logging.Logger | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[list[object], list[object], list[object]]:
    now = datetime.now(tz=UTC)

    def _do() -> tuple[list[object], list[object], list[object]]:
        h4 = fetch_bars(
            symbol=symbol,
            interval="4h",
            start=now - timedelta(days=lookback_h4),
            end=now,
            api_key=api_key,
        )
        h1 = fetch_bars(
            symbol=symbol,
            interval="1h",
            start=now - timedelta(days=lookback_h1),
            end=now,
            api_key=api_key,
        )
        m15 = fetch_bars(
            symbol=symbol,
            interval="15min",
            start=now - timedelta(days=lookback_m15),
            end=now,
            api_key=api_key,
        )
        return h4, h1, m15

    return retry_fetch(_do, log=log, sleep_fn=sleep_fn)


def _fetch_bars_with_retry(
    symbol: str,
    interval: str,
    lookback_days: int,
    api_key: str,
    log: logging.Logger | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[object]:
    now = datetime.now(tz=UTC)
    return retry_fetch(
        lambda: fetch_bars(
            symbol=symbol,
            interval=interval,
            start=now - timedelta(days=lookback_days),
            end=now,
            api_key=api_key,
        ),
        log=log,
        sleep_fn=sleep_fn,
    )


def _bos_state_from_h4(bars_h4: list[object]) -> str:
    strat = WeeklyBOSRetest()
    flat = Position(direction="FLAT")
    for i in range(len(bars_h4)):
        strat.on_bar(BarView(bars=tuple(bars_h4[: i + 1])), flat)
    bos = strat._bos.value  # noqa: SLF001
    return bos.state.value if bos is not None else "idle"


# ---------------------------------------------------------------------------
# Paper trader helpers
# ---------------------------------------------------------------------------


def _paper_signal(result: MultiTFScanResult, pos_direction: str) -> Signal:
    if pos_direction == "FLAT":
        return result.direction if result.confluence else Signal.FLAT
    return result.h4_trend


def _to_scan_result(result: MultiTFScanResult, sig: Signal) -> ScanResult:
    return ScanResult(
        ts=result.scanned_at,
        symbol=result.symbol,
        timeframe="m15",
        signal=sig,
        bos_state="unknown",
        has_ob=False,
        ob_high=None,
        ob_low=None,
        prev_week_high=None,
        prev_week_low=None,
        sl=result.sl,
        tp=result.tp,
        n_bars_used=0,
    )


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    state: _State = context.bot_data["state"]
    await update.message.reply_text(
        fmt_cmd_start(state.symbol),
        parse_mode="Markdown",
    )


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _cmd_start(update, context)


async def _cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    state: _State = context.bot_data["state"]

    if state.last_result is None or state.last_price is None:
        await update.message.reply_text("⏳ Scanner warming up — try again in a few minutes.")
        return

    msg = fmt_cmd_signal(state.symbol, state.last_result, state.last_price, datetime.now(tz=UTC))
    await update.message.reply_text(msg, parse_mode="Markdown")


async def _cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    state: _State = context.bot_data["state"]

    try:
        # Pull all closed signals from signal_store
        total = state.signal_store.total_count()
        wins = state.signal_store.count_by_status(SignalStatus.WIN)
        losses = state.signal_store.count_by_status(SignalStatus.LOSS)
        open_count = state.signal_store.count_by_status(SignalStatus.ACTIVE)
        cum_pips = state.signal_store.cumulative_pnl_pips()
    except Exception:  # noqa: BLE001
        state.log.exception("cmd_stats: signal_store query failed")
        await update.message.reply_text("⚠️ Could not load stats — try again later.")
        return

    msg = fmt_cmd_stats(
        state.symbol, total, wins, losses, open_count, cum_pips, datetime.now(tz=UTC)
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Event handlers (called from the scheduler loop)
# ---------------------------------------------------------------------------


async def _handle_15m(bot: Bot, state: _State) -> None:
    now = datetime.now(tz=UTC)
    state.log.info(
        "Fetching %s bars — 4H:%dd  1H:%dd  15M:%dd",
        state.symbol,
        state.lookback_h4,
        state.lookback_h1,
        state.lookback_m15,
    )
    try:
        bars_h4, bars_h1, bars_m15 = await asyncio.to_thread(
            _fetch_all,
            state.symbol,
            state.lookback_h4,
            state.lookback_h1,
            state.lookback_m15,
            state.api_key,
            state.log,
        )
    except Exception as exc:  # noqa: BLE001
        state.consecutive_failures += 1
        state.log.error(
            "All fetch retries failed (consecutive=%d): %s",
            state.consecutive_failures,
            exc,
        )
        if state.consecutive_failures == 1 or state.consecutive_failures % 4 == 0:
            await bot.send_message(
                chat_id=state.notif_chat_id,
                text=(
                    f"⚠️ {state.symbol} Network Error\n"
                    f"Cannot reach TwelveData ({state.consecutive_failures} "
                    f"consecutive failures).\n{type(exc).__name__}: {exc}"
                ),
            )
        return

    state.consecutive_failures = 0
    state.log.info(
        "Bars fetched — 4H:%d  1H:%d  15M:%d",
        len(bars_h4),
        len(bars_h1),
        len(bars_m15),
    )

    result: MultiTFScanResult = state.scanner.scan(bars_h4, bars_h1, bars_m15)

    # Cache for /signal command
    if bars_m15:
        state.last_result = result
        state.last_price = bars_m15[-1].close

    sc = score_signal(
        result,
        now,
        w_structure=STATIC_WEIGHTS.structure,
        w_momentum=STATIC_WEIGHTS.momentum,
        w_session=STATIC_WEIGHTS.session,
        w_cost=STATIC_WEIGHTS.cost,
    )

    conf_pct, conf_n, conf_stored_label = state.signal_store.confidence(sc.total, regime="unknown")

    rr: float | None = None
    sl_pips: float | None = None
    if result.entry_price is not None and result.sl is not None:
        sl_pips = abs(result.entry_price - result.sl) / _XAUUSD_PIP
        if result.tp is not None and sl_pips is not None and sl_pips > 0:
            tp_pips = abs(result.tp - result.entry_price) / _XAUUSD_PIP
            rr = tp_pips / sl_pips

    sig = StoredSignal(
        id=make_signal_id(state.symbol, now, "15m_scan"),
        ts=now,
        symbol=state.symbol,
        source="15m_scan",
        direction=result.direction.value if result.direction is not None else None,
        h4_signal=result.h4.signal.value,
        h1_signal=result.h1.signal.value,
        m15_signal=result.m15.signal.value,
        confluence=result.confluence,
        entry_price=result.entry_price,
        sl=result.sl,
        tp=result.tp,
        rr=rr,
        sl_pips=sl_pips,
        score=sc,
        score_weights=STATIC_WEIGHTS,
        confidence_pct=conf_pct,
        confidence_n=conf_n,
        confidence_label=conf_stored_label,
        regime="unknown",
    )
    state.signal_store.insert(sig)

    # Paper trader
    if bars_m15:
        paper_sig = _paper_signal(result, state.paper_trader.position.direction)
        paper_scan = _to_scan_result(result, paper_sig)
        ev = state.paper_trader.update(paper_scan, bars_m15[-1])  # type: ignore[arg-type]

        if ev.kind in (EventKind.ENTRY_LONG, EventKind.ENTRY_SHORT):
            state.paper_trader.set_entry_link(sig.id)
            state.signal_store.update_status(sig.id, SignalStatus.ACTIVE)
            state.log.info(
                "PaperTrader ENTRY %s  entry=%.2f  SL=%s  TP=%s",
                ev.kind,
                ev.price,
                f"{ev.sl:.2f}" if ev.sl else "n/a",
                f"{ev.tp:.2f}" if ev.tp else "n/a",
            )
        elif ev.kind in (EventKind.EXIT_TP, EventKind.EXIT_SL, EventKind.EXIT_SIGNAL):
            pnl_pips = round(ev.pnl / _XAUUSD_PIP, 1) if ev.pnl is not None else None
            status = (
                SignalStatus.WIN
                if ev.kind == EventKind.EXIT_TP
                else SignalStatus.LOSS
                if ev.kind == EventKind.EXIT_SL
                else SignalStatus.EXPIRED
            )
            entry_id = state.paper_trader.position.entry_signal_id
            if entry_id is not None:
                state.signal_store.update_status(entry_id, status, pnl_pips=pnl_pips)
                state.paper_trader.clear_entry_link()
            state.log.info(
                "PaperTrader EXIT  %s  exit=%.2f  pnl=%.1f pips  cum=%.2f",
                ev.kind,
                ev.price,
                pnl_pips if pnl_pips is not None else 0.0,
                ev.cumulative_pnl,
            )
            # Record fill in R-multiples for risk governor
            if pnl_pips is not None and sl_pips is not None and sl_pips > 0:
                pnl_r = pnl_pips / sl_pips
                tripped = state.risk_governor.record_fill(pnl_r, now)
                if tripped:
                    await bot.send_message(
                        chat_id=state.notif_chat_id,
                        text=(
                            f"🛑 {state.symbol} RiskGovernor HALT\n"
                            f"{state.risk_governor.ledger.halt_reason}"
                        ),
                    )

    # Legacy JSONL store
    state.level_store.append_signal(
        SignalRecord(
            ts=now.isoformat(),
            symbol=state.symbol,
            h4_signal=result.h4.signal.value,
            h1_signal=result.h1.signal.value,
            m15_signal=result.m15.signal.value,
            confluence=result.confluence,
            entry_price=result.entry_price,
            sl=result.sl,
            tp=result.tp,
            source="15m_scan",
        )
    )

    state.log.info(
        "[%s] 4H_trend=%s 1H=%s 15M=%s conf=%s score=%d[%s]",
        state.symbol,
        result.h4_trend.value,
        result.h1.signal.value,
        result.m15.signal.value,
        result.confluence,
        sc.total,
        sc.label,
    )

    if not result.confluence:
        state.log.info(
            "No confluence — 4H_trend=%s BOS=%s 1H=%s",
            result.h4_trend.value,
            result.h4.signal.value,
            result.h1.signal.value,
        )
        return

    # Risk governor halt gate
    if state.risk_governor.is_halted(now):
        state.log.info("No alert: RiskGovernor halted (%s)", state.risk_governor.ledger.halt_reason)
        return

    # Hard gate: 15M EMACross must confirm direction
    if result.m15.signal != result.direction:
        state.log.info(
            "No alert: 15M=%s does not confirm direction=%s",
            result.m15.signal.value,
            result.direction.value,
        )
        return

    if sc.total < state.score_threshold:
        state.log.info(
            "No alert: score %d < threshold %d [%s]",
            sc.total,
            state.score_threshold,
            sc.label,
        )
        return

    if state.news_gate.is_blocked(now):
        state.log.info(
            "No alert: signal blocked by news gate (%s %s)",
            state.symbol,
            now.strftime("%H:%M UTC"),
        )
        return

    alert_state = state.alert_store.load()
    if alert_state.is_duplicate(result.direction.value, result.h4.last_bar_ts):
        state.log.info(
            "No alert: same signal already sent for this H4 bar (%s)",
            result.h4.last_bar_ts,
        )
        return

    score_lines = (
        f"\n\n*Signal Score: {sc.total}/100 [{sc.label}]*"
        f"\n  structure={sc.structure}  momentum={sc.momentum}"
        f"\n  session={sc.session}  cost={sc.cost}"
        f"\n{confidence_label(conf_pct, conf_n)}"
    )
    msg = fmt_confluence_alert(result) + score_lines
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    alert_state.update(result.direction.value, result.h4.last_bar_ts)
    state.alert_store.save(alert_state)
    state.log.info("Alert sent: %s %s score=%d", state.symbol, result.direction.value, sc.total)

    if state.repo is not None:

        async def _send(uid: int, text: str) -> None:
            await bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")

        try:
            n = await dispatch_signal(
                sig,
                state.repo,
                _send,
                primary_session,
                killswitch=lambda: state.risk_governor.is_halted(),
            )
            state.log.info("Fan-out dispatched to %d user(s)", n)
        except Exception as exc:
            state.log.error("Fan-out error (non-fatal): %s", exc)


async def _handle_market_update_4h(bot: Bot, state: _State) -> None:
    """4H market update — price + bias, no trade required."""
    now = datetime.now(tz=UTC)
    try:
        bars_h4, bars_h1, bars_m15 = await asyncio.to_thread(
            _fetch_all,
            state.symbol,
            state.lookback_h4,
            state.lookback_h1,
            state.lookback_m15,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("market_update_4h: fetch failed")
        return

    if not bars_m15:
        return

    result = state.scanner.scan(bars_h4, bars_h1, bars_m15)
    current_price = bars_m15[-1].close  # type: ignore[attr-defined]
    state.last_result = result
    state.last_price = current_price

    msg = fmt_market_update_4h(state.symbol, result, current_price, now)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("4H market update sent: %s price=%.2f", state.symbol, current_price)


async def _handle_london_sweep(bot: Bot, state: _State) -> None:
    """London open sweep-and-reject scan — fires at 08:00 UTC Mon–Fri."""
    try:
        bars_h1 = await asyncio.to_thread(
            _fetch_bars_with_retry,
            state.symbol,
            "1h",
            7,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("london_sweep: fetch failed")
        return

    if not bars_h1:
        state.log.warning("london_sweep: no 1H bars returned")
        return

    result = state.sweep_scanner.scan(bars_h1)  # type: ignore[arg-type]
    state.log.info(
        "London sweep scan: signal=%s  asian_h=%s  asian_l=%s",
        result.signal.value,
        f"{result.asian_high:.2f}" if result.asian_high is not None else "n/a",
        f"{result.asian_low:.2f}" if result.asian_low is not None else "n/a",
    )

    if not result.confluence:
        state.log.info("London sweep: no sweep signal (FLAT)")
        return

    msg = fmt_sweep_alert(result)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("London sweep alert sent: %s %s", state.symbol, result.direction.value)


async def _handle_market_open(bot: Bot, state: _State) -> None:
    now = datetime.now(tz=UTC)
    try:
        bars_h4 = await asyncio.to_thread(
            _fetch_bars_with_retry,
            state.symbol,
            "4h",
            state.lookback_h4,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("market_open: fetch failed")
        return
    if not bars_h4:
        state.log.warning("market_open: no 4H bars returned")
        return

    prev_week_start = current_week_start(now) - timedelta(weeks=1)
    prev_week_end = current_week_start(now)
    prev_bars = [
        b
        for b in bars_h4
        if prev_week_start <= b.ts.astimezone(UTC) < prev_week_end  # type: ignore[attr-defined]
    ]
    prev_week = compute_week_levels(prev_bars, prev_week_start) if prev_bars else None
    bos_state = _bos_state_from_h4(bars_h4)
    last_close = bars_h4[-1].close  # type: ignore[attr-defined]

    if prev_week is not None:
        state.level_store.append_level(
            WeeklyLevel(
                week_start=prev_week_start.strftime("%Y-%m-%d"),
                symbol=state.symbol,
                prev_high=prev_week.high,
                prev_low=prev_week.low,
                week_high=None,
                week_low=None,
                recorded_at=now.isoformat(),
            )
        )

    msg = fmt_market_open(state.symbol, prev_week, last_close, bos_state, now)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("market_open report sent: %s", state.symbol)


async def _handle_market_close(bot: Bot, state: _State) -> None:
    now = datetime.now(tz=UTC)
    try:
        bars_h4 = await asyncio.to_thread(
            _fetch_bars_with_retry,
            state.symbol,
            "4h",
            state.lookback_h4,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("market_close: fetch failed")
        return
    if not bars_h4:
        state.log.warning("market_close: no 4H bars returned")
        return

    ws = current_week_start(now)
    current_week = compute_week_levels(bars_h4, ws)
    last_close = bars_h4[-1].close  # type: ignore[attr-defined]

    if current_week is not None:
        state.level_store.append_level(
            WeeklyLevel(
                week_start=ws.strftime("%Y-%m-%d"),
                symbol=state.symbol,
                prev_high=None,
                prev_low=None,
                week_high=current_week.high,
                week_low=current_week.low,
                recorded_at=now.isoformat(),
            )
        )

    msg = fmt_market_close(state.symbol, current_week, last_close, now)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("market_close report sent: %s", state.symbol)


async def _handle_weekly_report(bot: Bot, state: _State) -> None:
    now = datetime.now(tz=UTC)
    try:
        bars_h4 = await asyncio.to_thread(
            _fetch_bars_with_retry,
            state.symbol,
            "4h",
            state.lookback_h4,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("weekly_report: fetch failed")
        return
    if not bars_h4:
        state.log.warning("weekly_report: no 4H bars returned")
        return

    ws = current_week_start(now)
    current_week = compute_week_levels(bars_h4, ws)
    bos_state = _bos_state_from_h4(bars_h4)
    last_close = bars_h4[-1].close  # type: ignore[attr-defined]

    msg = fmt_weekly_report(state.symbol, current_week, bos_state, last_close, now)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")

    # Weekly P&L summary
    try:
        wins = state.signal_store.count_by_status(SignalStatus.WIN)
        losses = state.signal_store.count_by_status(SignalStatus.LOSS)
        total = state.signal_store.total_count()
        cum_pips = state.signal_store.cumulative_pnl_pips()
        perf_msg = fmt_weekly_performance(state.symbol, total, wins, losses, cum_pips, now)
        await bot.send_message(chat_id=state.chat_id, text=perf_msg, parse_mode="Markdown")
    except Exception:  # noqa: BLE001
        state.log.exception("weekly P&L summary failed")

    state.log.info("weekly_report + P&L sent: %s", state.symbol)


async def _handle_session_open(bot: Bot, state: _State, session: str) -> None:
    now = datetime.now(tz=UTC)
    try:
        bars_h4, bars_h1, bars_m15 = await asyncio.to_thread(
            _fetch_all,
            state.symbol,
            14,
            7,
            state.lookback_m15,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("%s_open: fetch failed", session.lower())
        return
    if not bars_m15:
        state.log.warning("%s_open: no bars", session.lower())
        return

    result = state.scanner.scan(bars_h4, bars_h1, bars_m15)
    current_price = bars_m15[-1].close  # type: ignore[attr-defined]

    msg = fmt_session_open(
        state.symbol,
        session,
        current_price,
        result.h4.signal,
        result.h1.signal,
        now,
    )
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("%s open alert sent: %s price=%.2f", session, state.symbol, current_price)


async def _handle_daily_report(bot: Bot, state: _State) -> None:
    now = datetime.now(tz=UTC)
    try:
        bars_h4, bars_h1, bars_m15 = await asyncio.to_thread(
            _fetch_all,
            state.symbol,
            state.lookback_h4,
            state.lookback_h1,
            state.lookback_m15,
            state.api_key,
            state.log,
        )
    except Exception:  # noqa: BLE001
        state.log.exception("daily_report: fetch failed")
        return

    if not bars_h1:
        state.log.warning("daily_report: no bars")
        return

    result = state.scanner.scan(bars_h4, bars_h1, bars_m15)
    day_levels = compute_day_levels(bars_h1, now)

    msg = fmt_daily_report(state.symbol, result, day_levels, now)
    await bot.send_message(chat_id=state.chat_id, text=msg, parse_mode="Markdown")
    state.log.info("daily_report sent: %s", state.symbol)

    # Monthly archival
    if now.day == 1:
        prev_month = now.month - 1 if now.month > 1 else 12
        prev_year = now.year if now.month > 1 else now.year - 1
        archive_path = (
            state.state_dir
            / "signals_archive"
            / state.symbol
            / f"{prev_year}"
            / f"{prev_month:02d}.parquet"
        )
        try:
            n = state.signal_store.export_month(prev_year, prev_month, archive_path)
            state.signal_store.purge_before(now.year, now.month)
            total = state.signal_store.total_count()
            state.log.info(
                "Monthly archive: exported %d signals → %s  (store now has %d rows)",
                n,
                archive_path,
                total,
            )
        except Exception:  # noqa: BLE001
            state.log.exception("Monthly signal archival failed")


# ---------------------------------------------------------------------------
# Scheduler loop (runs as background async task alongside PTB polling)
# ---------------------------------------------------------------------------


def _touch_heartbeat(state_dir: Path) -> None:
    """Touch the heartbeat file so the Docker healthcheck can verify liveness."""
    hb = state_dir / "heartbeat"
    hb.touch()


def _events_to_fire(events: list[EventType], *, stream_active: bool) -> list[EventType]:
    """Filter scheduled events based on stream mode.

    In stream mode, BAR_CLOSE_15M is driven by the bar queue consumer, not the
    scheduler.  All other events fire normally.
    """
    if not stream_active:
        return list(events)
    return [e for e in events if e != EventType.BAR_CLOSE_15M]


async def _stream_consumer(
    bot: Bot,
    state: _State,
    bar_queue: asyncio.Queue[Bar],
) -> None:
    """Consume bars from the ResilientStream queue and run _handle_15m logic.

    Runs until the task is cancelled or falls back on unhandled crash.
    On crash, sets state.stream_fallback = True so the scheduler resumes 15M events.
    """
    while True:
        _bar: Bar = await bar_queue.get()
        state.log.debug("Stream bar received: %s close=%.2f", _bar.ts, _bar.close)
        try:
            await _handle_15m(bot, state)
        except Exception:
            state.log.exception("_stream_consumer: _handle_15m raised")


async def _scheduler_loop(app: Application, state: _State) -> None:  # type: ignore[type-arg]
    bot: Bot = app.bot
    shutdown: asyncio.Event = app.bot_data["shutdown"]

    state.log.info("Scheduler loop started")
    _touch_heartbeat(state.state_dir)

    while not shutdown.is_set():
        _touch_heartbeat(state.state_dir)
        now = datetime.now(tz=UTC)
        fire_at, events = state.event_sched.next_events(now)

        wait = (fire_at - now).total_seconds()
        state.log.info(
            "Next event(s): %s at %s UTC",
            [e.value for e in events],
            fire_at.strftime("%Y-%m-%d %H:%M:%S"),
        )

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=max(wait, 0.1))
            break  # shutdown triggered
        except TimeoutError:
            pass  # normal — time to fire

        if shutdown.is_set():
            break

        stream_active = state.stream_mode and not state.stream_fallback
        for event in _events_to_fire(events, stream_active=stream_active):
            try:
                if event == EventType.BAR_CLOSE_15M:
                    await _handle_15m(bot, state)
                elif event == EventType.MARKET_UPDATE_4H:
                    await _handle_market_update_4h(bot, state)
                elif event == EventType.MARKET_OPEN:
                    await _handle_market_open(bot, state)
                elif event == EventType.MARKET_CLOSE:
                    await _handle_market_close(bot, state)
                elif event == EventType.WEEKLY_REPORT:
                    await _handle_weekly_report(bot, state)
                elif event == EventType.LONDON_OPEN:
                    await _handle_session_open(bot, state, "London")
                    await _handle_london_sweep(bot, state)
                elif event == EventType.NY_OPEN:
                    await _handle_session_open(bot, state, "NY")
                elif event == EventType.DAILY_REPORT:
                    await _handle_daily_report(bot, state)
            except Exception:  # noqa: BLE001
                state.log.exception("Event handler failed: %s", event.value)

    state.log.info("Scheduler loop exited")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-TF production daemon with Telegram bot commands."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--lookback-4h", type=int, default=90)
    parser.add_argument("--lookback-1h", type=int, default=45)
    parser.add_argument("--lookback-15m", type=int, default=14)
    parser.add_argument("--state-dir", default="data/")
    parser.add_argument("--log-file", default=None)
    parser.add_argument(
        "--score-threshold",
        type=int,
        default=_ALERT_SCORE_THRESHOLD,
        help="Minimum signal score (0–100) for Telegram alert",
    )
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Use WebSocket stream for 15M bars instead of REST polling",
    )
    args = parser.parse_args()

    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print("ERROR: TWELVEDATA_API_KEY env var is not set.", file=sys.stderr)
        sys.exit(1)

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    telegram_notif_chat_id = os.environ.get("TELEGRAM_NOTIF_CHAT_ID", "")
    if not telegram_token or not telegram_chat_id or not telegram_notif_chat_id:
        print(
            "ERROR: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, and TELEGRAM_NOTIF_CHAT_ID "
            "env vars are required.",
            file=sys.stderr,
        )
        sys.exit(1)

    log = _setup_logging(args.log_file)

    database_url = os.environ.get("DATABASE_URL", "").strip() or None
    repo: UserRepository | None = None
    if database_url is not None:
        from novax.bot.db_postgres import connect_and_prepare  # noqa: PLC0415

        repo = connect_and_prepare(database_url)
        log.info("Fan-out: PostgresUserRepository ready")
    else:
        log.info("Fan-out: DATABASE_URL not set — per-user fan-out disabled")

    symbol = args.symbol.upper()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    scanner = MultiTFScanner(
        symbol,
        h4_params={
            "ema_fast": args.ema_fast,
            "ema_slow": args.ema_slow,
            "ob_buffer_pips": args.ob_buffer_pips,
            "max_risk_pips": args.max_risk_pips,
            "risk_reward": args.risk_reward,
        },
    )
    sweep_scanner = LondonSweepScanner(symbol)
    risk_governor = RiskGovernor(state_dir / f"risk_ledger_{symbol}.json")

    state = _State(
        symbol=symbol,
        scanner=scanner,
        sweep_scanner=sweep_scanner,
        alert_store=AlertStateStore(state_dir / f"alert_state_{symbol}.json"),
        level_store=LevelStore(state_dir / f"levels_{symbol}.jsonl"),
        signal_store=SignalStore(state_dir / f"signals_{symbol}.duckdb"),
        news_gate=NewsGate(api_key=api_key),
        paper_trader=PaperTrader(state_dir / f"paper_{symbol}.json"),
        risk_governor=risk_governor,
        event_sched=EventScheduler(),
        lookback_h4=args.lookback_4h,
        lookback_h1=args.lookback_1h,
        lookback_m15=args.lookback_15m,
        api_key=api_key,
        chat_id=telegram_chat_id,
        notif_chat_id=telegram_notif_chat_id,
        score_threshold=args.score_threshold,
        state_dir=state_dir,
        log=log,
    )
    state.repo = repo
    state.stream_mode = args.stream

    shutdown_event = asyncio.Event()

    async def post_init(application: Application) -> None:
        application.bot_data["state"] = state
        application.bot_data["shutdown"] = shutdown_event
        reconcile_on_boot(state.paper_trader, state.signal_store, log)
        first_fire, first_events = state.event_sched.next_events(datetime.now(tz=UTC))
        await application.bot.send_message(
            chat_id=state.notif_chat_id,
            text=fmt_startup(
                symbol=symbol,
                state_dir=str(state_dir),
                next_event_types=[e.value for e in first_events],
                next_event_at=first_fire,
            ),
            parse_mode="Markdown",
        )
        log.info("Startup notification sent: %s", symbol)
        asyncio.create_task(_scheduler_loop(application, state))

        if state.stream_mode:
            bar_queue: asyncio.Queue[Bar] = asyncio.Queue()
            resilient = ResilientStream(
                api_key=api_key,
                symbol=symbol,
                interval_seconds=900,
                bar_queue=bar_queue,
            )

            async def _stream_supervisor() -> None:
                try:
                    await resilient.run()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception(
                        "Stream supervisor crashed — falling back to scheduler 15M events"
                    )
                    state.stream_fallback = True
                    await application.bot.send_message(
                        chat_id=state.notif_chat_id,
                        text=(
                            f"[{symbol}] Stream supervisor crashed. "
                            "Falling back to REST polling for 15M bars."
                        ),
                    )

            asyncio.create_task(_stream_consumer(application.bot, state, bar_queue))
            asyncio.create_task(_stream_supervisor())
            log.info("Stream mode enabled — ResilientStream started for %s", symbol)

    async def post_stop(application: Application) -> None:
        shutdown_event.set()
        await application.bot.send_message(
            chat_id=state.notif_chat_id,
            text=fmt_shutdown(symbol, datetime.now(tz=UTC)),
            parse_mode="Markdown",
        )
        log.info("Daemon stopped.")

    app = (
        Application.builder()
        .token(telegram_token)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("signal", _cmd_signal))
    app.add_handler(CommandHandler("stats", _cmd_stats))

    log.info("Daemon started (V3) — %s  state-dir=%s", symbol, state_dir)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
