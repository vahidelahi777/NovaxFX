"""Production daemon: multi-TF signal scanner with Telegram alerts.

Event schedule (all UTC → IRST = UTC+3:30):
  Every 15M bar close  — Multi-TF confluence scan + Telegram alert (if applicable)
  Sunday    22:00 UTC  — Market-open report with previous-week H/L  (01:30 IRST Mon)
  Mon-Fri   08:00 UTC  — London-open session alert                  (11:30 IRST)
  Mon-Fri   13:00 UTC  — NY-open session alert                      (16:30 IRST)
  Mon-Fri   20:00 UTC  — Daily summary report                       (23:30 IRST)
  Friday    21:00 UTC  — Market-close + weekly report               (00:30 IRST Sat)

Usage:
  python scripts/prod_daemon_xauusd.py \\
      --symbol XAUUSD \\
      [--lookback-4h 90] \\
      [--lookback-1h 45] \\
      [--lookback-15m 14] \\
      [--state-dir data/] \\
      [--log-file logs/daemon_XAUUSD.log]
      [--score-threshold 50]

Required env vars:
  TWELVEDATA_API_KEY   — never passed as a CLI arg or logged
  TELEGRAM_TOKEN       — never logged
  TELEGRAM_CHAT_ID     — never logged
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from novax.data.ingest.twelvedata import fetch_bars
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
    fmt_confluence_alert,
    fmt_daily_report,
    fmt_heartbeat,
    fmt_market_close,
    fmt_market_open,
    fmt_session_open,
    fmt_shutdown,
    fmt_startup,
    fmt_weekly_report,
    make_signal_id,
    score_signal,
)
from novax.strategies.weekly_bos_retest import WeeklyBOSRetest

HEARTBEAT_INTERVAL = timedelta(hours=1)

# Minimum score to send a Telegram alert (50 = MEDIUM threshold)
_ALERT_SCORE_THRESHOLD = 50

_shutdown = threading.Event()

_XAUUSD_PIP = 0.1


def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    _shutdown.set()


def _setup_logging(log_file: str | None) -> logging.Logger:
    log = logging.getLogger("prod_daemon_xauusd")
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
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


def _sleep_until(target: datetime) -> None:
    while not _shutdown.is_set():
        remaining = (target - datetime.now(tz=UTC)).total_seconds()
        if remaining <= 0:
            break
        _shutdown.wait(timeout=min(1.0, remaining))


def _send_telegram(token: str, chat_id: str, text: str, log: logging.Logger) -> None:
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat_id)}"
        f"&text={urllib.parse.quote(text)}"
        f"&parse_mode=Markdown"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                log.warning("Telegram returned HTTP %s", resp.status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram send failed: %s", exc)


def _fetch_all(
    symbol: str,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    api_key: str,
) -> tuple[list, list, list]:
    now = datetime.now(tz=UTC)
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=lookback_h4),
        end=now,
        api_key=api_key,
    )
    bars_h1 = fetch_bars(
        symbol=symbol,
        interval="1h",
        start=now - timedelta(days=lookback_h1),
        end=now,
        api_key=api_key,
    )
    bars_m15 = fetch_bars(
        symbol=symbol,
        interval="15min",
        start=now - timedelta(days=lookback_m15),
        end=now,
        api_key=api_key,
    )
    return bars_h4, bars_h1, bars_m15


def _bos_state_from_h4(bars_h4: list) -> str:
    """Replay WeeklyBOSRetest on 4H bars and return the BOS state string."""
    strat = WeeklyBOSRetest()
    flat = Position(direction="FLAT")
    for i in range(len(bars_h4)):
        strat.on_bar(BarView(bars=tuple(bars_h4[: i + 1])), flat)
    bos = strat._bos.value  # noqa: SLF001
    return bos.state.value if bos is not None else "idle"


def _paper_signal(result: MultiTFScanResult, pos_direction: str) -> Signal:
    """Determine the Signal to pass to PaperTrader based on multi-TF state.

    Entry: only on confirmed multi-TF confluence.
    Hold/exit: driven by 4H direction so positions survive brief 15M/1H
    consolidation without premature exit.
    """
    if pos_direction == "FLAT":
        return result.direction if result.confluence else Signal.FLAT
    return result.h4.signal


def _to_scan_result(result: MultiTFScanResult, sig: Signal) -> ScanResult:
    """Convert MultiTFScanResult to ScanResult for PaperTrader.update()."""
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


def _send_heartbeat(
    *,
    symbol: str,
    now: datetime,
    next_event_types: list[str],
    next_event_at: datetime,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    msg = fmt_heartbeat(symbol, now, next_event_types, next_event_at)
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("Heartbeat sent: %s", symbol)


# ------------------------------------------------------------------
# Event handlers
# ------------------------------------------------------------------

def _handle_15m(
    *,
    symbol: str,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    scanner: MultiTFScanner,
    alert_store: AlertStateStore,
    level_store: LevelStore,
    signal_store: SignalStore,
    news_gate: NewsGate,
    paper_trader: PaperTrader,
    paper_entry_id: list[str | None],
    score_threshold: int,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    log.info(
        "Fetching %s bars — 4H:%dd  1H:%dd  15M:%dd",
        symbol, lookback_h4, lookback_h1, lookback_m15,
    )
    bars_h4, bars_h1, bars_m15 = _fetch_all(
        symbol, lookback_h4, lookback_h1, lookback_m15, api_key
    )
    log.info(
        "Bars fetched — 4H:%d  1H:%d  15M:%d",
        len(bars_h4), len(bars_h1), len(bars_m15),
    )

    result: MultiTFScanResult = scanner.scan(bars_h4, bars_h1, bars_m15)

    # Score this scan
    sc = score_signal(result, now,
                      w_structure=STATIC_WEIGHTS.structure,
                      w_momentum=STATIC_WEIGHTS.momentum,
                      w_session=STATIC_WEIGHTS.session,
                      w_cost=STATIC_WEIGHTS.cost)

    # Historical confidence from the signal store
    conf_pct, conf_n, conf_stored_label = signal_store.confidence(sc.total, regime="unknown")

    # Derived risk metrics
    rr: float | None = None
    sl_pips: float | None = None
    if result.entry_price is not None and result.sl is not None:
        sl_pips = abs(result.entry_price - result.sl) / _XAUUSD_PIP
        if result.tp is not None and sl_pips > 0:
            tp_pips = abs(result.tp - result.entry_price) / _XAUUSD_PIP
            rr = tp_pips / sl_pips

    # Persist signal to DuckDB — always, regardless of confluence or score
    sig = StoredSignal(
        id=make_signal_id(symbol, now, "15m_scan"),
        ts=now,
        symbol=symbol,
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
    signal_store.insert(sig)

    # Paper trader — run every bar to track virtual P&L
    if bars_m15:
        paper_sig = _paper_signal(result, paper_trader.position.direction)
        paper_scan = _to_scan_result(result, paper_sig)
        ev = paper_trader.update(paper_scan, bars_m15[-1])

        if ev.kind in (EventKind.ENTRY_LONG, EventKind.ENTRY_SHORT):
            paper_entry_id[0] = sig.id
            signal_store.update_status(sig.id, SignalStatus.ACTIVE)
            log.info(
                "PaperTrader ENTRY %s  entry=%.2f  SL=%s  TP=%s",
                ev.kind, ev.price,
                f"{ev.sl:.2f}" if ev.sl else "n/a",
                f"{ev.tp:.2f}" if ev.tp else "n/a",
            )
        elif ev.kind in (EventKind.EXIT_TP, EventKind.EXIT_SL, EventKind.EXIT_SIGNAL):
            pnl_pips = round(ev.pnl / _XAUUSD_PIP, 1) if ev.pnl is not None else None
            status = (
                SignalStatus.WIN if ev.kind == EventKind.EXIT_TP
                else SignalStatus.LOSS if ev.kind == EventKind.EXIT_SL
                else SignalStatus.EXPIRED
            )
            if paper_entry_id[0] is not None:
                signal_store.update_status(paper_entry_id[0], status, pnl_pips=pnl_pips)
                paper_entry_id[0] = None
            log.info(
                "PaperTrader EXIT  %s  exit=%.2f  pnl=%.1f pips  cum=%.2f",
                ev.kind, ev.price,
                pnl_pips if pnl_pips is not None else 0.0,
                ev.cumulative_pnl,
            )

    # Legacy JSONL store — kept for backward compatibility
    level_store.append_signal(
        SignalRecord(
            ts=now.isoformat(),
            symbol=symbol,
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

    log.info(
        "[%s] 4H=%s 1H=%s 15M=%s conf=%s score=%d[%s] SL=%s TP=%s conf_label=%s",
        symbol,
        result.h4.signal.value,
        result.h1.signal.value,
        result.m15.signal.value,
        result.confluence,
        sc.total,
        sc.label,
        f"{result.sl:.2f}" if result.sl is not None else "n/a",
        f"{result.tp:.2f}" if result.tp is not None else "n/a",
        conf_stored_label,
    )

    if not result.confluence:
        log.info(
            "No confluence — 4H=%s 1H=%s",
            result.h4.signal.value,
            result.h1.signal.value,
        )
        return

    # Score gate — low-confidence setups never reach Telegram
    if sc.total < score_threshold:
        log.info(
            "No alert: score %d < threshold %d [%s]",
            sc.total, score_threshold, sc.label,
        )
        return

    # News gate — suppress during high-impact events
    if news_gate.is_blocked(now):
        log.info("No alert: signal blocked by news gate (%s %s)", symbol, now.strftime("%H:%M UTC"))
        return

    # Duplicate gate — one alert per H4 bar per direction
    state = alert_store.load()
    if state.is_duplicate(result.direction.value, result.h4.last_bar_ts):
        log.info(
            "No alert: same signal already sent for this H4 bar (%s)",
            result.h4.last_bar_ts,
        )
        return

    score_lines = (
        f"\n\n*Signal Score: {sc.total}/100 [{sc.label}]*"
        f"\n  structure={sc.structure}  momentum={sc.momentum}"
        f"  session={sc.session}  cost={sc.cost}"
        f"\n{confidence_label(conf_pct, conf_n)}"
    )
    msg = fmt_confluence_alert(result) + score_lines
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    state.update(result.direction.value, result.h4.last_bar_ts)
    alert_store.save(state)
    log.info("Alert sent: %s %s score=%d", symbol, result.direction.value, sc.total)


def _handle_market_open(
    *,
    symbol: str,
    lookback_h4: int,
    level_store: LevelStore,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=lookback_h4),
        end=now,
        api_key=api_key,
    )
    if not bars_h4:
        log.warning("market_open: no 4H bars returned")
        return

    prev_week_start = current_week_start(now) - timedelta(weeks=1)
    prev_week_end = current_week_start(now)
    prev_bars = [
        b for b in bars_h4
        if prev_week_start <= b.ts.astimezone(UTC) < prev_week_end
    ]
    prev_week = compute_week_levels(prev_bars, prev_week_start) if prev_bars else None

    bos_state = _bos_state_from_h4(bars_h4)
    last_close = bars_h4[-1].close

    if prev_week is not None:
        level_store.append_level(
            WeeklyLevel(
                week_start=prev_week_start.strftime("%Y-%m-%d"),
                symbol=symbol,
                prev_high=prev_week.high,
                prev_low=prev_week.low,
                week_high=None,
                week_low=None,
                recorded_at=now.isoformat(),
            )
        )

    msg = fmt_market_open(symbol, prev_week, last_close, bos_state, now)
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("market_open report sent: %s", symbol)


def _handle_market_close(
    *,
    symbol: str,
    lookback_h4: int,
    level_store: LevelStore,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=lookback_h4),
        end=now,
        api_key=api_key,
    )
    if not bars_h4:
        log.warning("market_close: no 4H bars returned")
        return

    ws = current_week_start(now)
    current_week = compute_week_levels(bars_h4, ws)
    last_close = bars_h4[-1].close

    if current_week is not None:
        level_store.append_level(
            WeeklyLevel(
                week_start=ws.strftime("%Y-%m-%d"),
                symbol=symbol,
                prev_high=None,
                prev_low=None,
                week_high=current_week.high,
                week_low=current_week.low,
                recorded_at=now.isoformat(),
            )
        )

    msg = fmt_market_close(symbol, current_week, last_close, now)
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("market_close report sent: %s", symbol)


def _handle_weekly_report(
    *,
    symbol: str,
    lookback_h4: int,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=lookback_h4),
        end=now,
        api_key=api_key,
    )
    if not bars_h4:
        log.warning("weekly_report: no 4H bars returned")
        return

    ws = current_week_start(now)
    current_week = compute_week_levels(bars_h4, ws)
    bos_state = _bos_state_from_h4(bars_h4)
    last_close = bars_h4[-1].close

    msg = fmt_weekly_report(symbol, current_week, bos_state, last_close, now)
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("weekly_report sent: %s", symbol)


def _handle_session_open(
    *,
    session: str,
    symbol: str,
    lookback_m15: int,
    scanner: MultiTFScanner,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    bars_m15 = fetch_bars(
        symbol=symbol,
        interval="15min",
        start=now - timedelta(days=lookback_m15),
        end=now,
        api_key=api_key,
    )
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=14),
        end=now,
        api_key=api_key,
    )
    bars_h1 = fetch_bars(
        symbol=symbol,
        interval="1h",
        start=now - timedelta(days=7),
        end=now,
        api_key=api_key,
    )
    if not bars_m15:
        log.warning("%s_open: no bars", session.lower())
        return

    result = scanner.scan(bars_h4, bars_h1, bars_m15)
    current_price = bars_m15[-1].close

    msg = fmt_session_open(
        symbol, session, current_price, result.h4.signal, result.h1.signal, now
    )
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("%s open alert sent: %s price=%.2f", session, symbol, current_price)


def _handle_daily_report(
    *,
    symbol: str,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    scanner: MultiTFScanner,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)
    bars_h4, bars_h1, bars_m15 = _fetch_all(
        symbol, lookback_h4, lookback_h1, lookback_m15, api_key
    )
    if not bars_h1:
        log.warning("daily_report: no bars")
        return

    result = scanner.scan(bars_h4, bars_h1, bars_m15)
    day_levels = compute_day_levels(bars_h1, now)

    msg = fmt_daily_report(symbol, result, day_levels, now)
    _send_telegram(telegram_token, telegram_chat_id, msg, log)
    log.info("daily_report sent: %s", symbol)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-TF production daemon: 4H BOS + 1H Pullback + 15M EMA."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--lookback-4h", type=int, default=90)
    parser.add_argument("--lookback-1h", type=int, default=45)
    parser.add_argument("--lookback-15m", type=int, default=14)
    parser.add_argument("--state-dir", default="data/")
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--score-threshold", type=int, default=_ALERT_SCORE_THRESHOLD,
                        help="Minimum signal score (0–100) required to send a Telegram alert")
    # H4 strategy params
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    args = parser.parse_args()

    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print("ERROR: TWELVEDATA_API_KEY env var is not set.", file=sys.stderr)
        sys.exit(1)

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not telegram_token or not telegram_chat_id:
        print(
            "ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars are required.",
            file=sys.stderr,
        )
        sys.exit(1)

    log = _setup_logging(args.log_file)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    symbol = args.symbol.upper()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    alert_store    = AlertStateStore(state_dir / f"alert_state_{symbol}.json")
    level_store    = LevelStore(state_dir / f"levels_{symbol}.jsonl")
    signal_store   = SignalStore(state_dir / f"signals_{symbol}.duckdb")
    news_gate      = NewsGate(api_key=api_key)
    paper_trader   = PaperTrader(state_dir / f"paper_{symbol}.json")
    paper_entry_id: list[str | None] = [None]
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
    event_sched = EventScheduler()

    log.info("Daemon started (V2) — %s  state-dir=%s", symbol, state_dir)

    # Send startup Telegram — first peek at the event queue for the message
    first_fire, first_events = event_sched.next_events(datetime.now(tz=UTC))
    _send_telegram(
        telegram_token,
        telegram_chat_id,
        fmt_startup(
            symbol=symbol,
            state_dir=str(state_dir),
            next_event_types=[e.value for e in first_events],
            next_event_at=first_fire,
        ),
        log,
    )
    log.info("Startup notification sent: %s", symbol)

    last_heartbeat = datetime.now(tz=UTC)

    while not _shutdown.is_set():
        now = datetime.now(tz=UTC)
        fire_at, events = event_sched.next_events(now)

        # Hourly heartbeat — fires at the top of any loop iteration where it's due
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            _send_heartbeat(
                symbol=symbol,
                now=now,
                next_event_types=[e.value for e in events],
                next_event_at=fire_at,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
                log=log,
            )
            last_heartbeat = now

        log.info(
            "Next event(s): %s at %s UTC",
            [e.value for e in events],
            fire_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        _sleep_until(fire_at)

        if _shutdown.is_set():
            break

        for event in events:
            try:
                if event == EventType.BAR_CLOSE_15M:
                    _handle_15m(
                        symbol=symbol,
                        lookback_h4=args.lookback_4h,
                        lookback_h1=args.lookback_1h,
                        lookback_m15=args.lookback_15m,
                        scanner=scanner,
                        alert_store=alert_store,
                        level_store=level_store,
                        signal_store=signal_store,
                        news_gate=news_gate,
                        paper_trader=paper_trader,
                        paper_entry_id=paper_entry_id,
                        score_threshold=args.score_threshold,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.MARKET_OPEN:
                    _handle_market_open(
                        symbol=symbol,
                        lookback_h4=args.lookback_4h,
                        level_store=level_store,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.MARKET_CLOSE:
                    _handle_market_close(
                        symbol=symbol,
                        lookback_h4=args.lookback_4h,
                        level_store=level_store,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.WEEKLY_REPORT:
                    _handle_weekly_report(
                        symbol=symbol,
                        lookback_h4=args.lookback_4h,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.LONDON_OPEN:
                    _handle_session_open(
                        session="London",
                        symbol=symbol,
                        lookback_m15=args.lookback_15m,
                        scanner=scanner,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.NY_OPEN:
                    _handle_session_open(
                        session="NY",
                        symbol=symbol,
                        lookback_m15=args.lookback_15m,
                        scanner=scanner,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
                elif event == EventType.DAILY_REPORT:
                    _handle_daily_report(
                        symbol=symbol,
                        lookback_h4=args.lookback_4h,
                        lookback_h1=args.lookback_1h,
                        lookback_m15=args.lookback_15m,
                        scanner=scanner,
                        api_key=api_key,
                        telegram_token=telegram_token,
                        telegram_chat_id=telegram_chat_id,
                        log=log,
                    )
            except Exception:  # noqa: BLE001
                log.exception("Event handler failed: %s", event.value)

    # Clean shutdown — notify Telegram
    _send_telegram(
        telegram_token,
        telegram_chat_id,
        fmt_shutdown(symbol, datetime.now(tz=UTC)),
        log,
    )
    log.info("Daemon stopped.")


if __name__ == "__main__":
    main()
