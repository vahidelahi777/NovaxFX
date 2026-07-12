"""Long-running daemon: paper-trade WeeklyBOSRetest on H4 bar closes.

Computes the next H4 bar close, sleeps until it arrives, then runs one
fetch→scan→paper-trade cycle.  Repeats until SIGTERM or SIGINT.

Usage:
  .venv/bin/python scripts/daemon_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      [--lookback-days 90] \\
      [--state-file data/paper_state_XAUUSD.json] \\
      [--journal-file data/journal_XAUUSD.jsonl] \\
      [--log-file logs/daemon_XAUUSD.log] \\
      [--telegram] \\
      [--ema-fast 20] [--ema-slow 50] \\
      [--ob-buffer-pips 5.0] [--max-risk-pips 80.0] [--risk-reward 2.0]

Required env vars:
  TWELVEDATA_API_KEY   — Twelve Data API key (never pass as CLI arg)

Required env vars for --telegram:
  TELEGRAM_TOKEN       — Bot token
  TELEGRAM_CHAT_ID     — Target chat ID

Security: API key and Telegram token are never logged or printed.
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
from novax.live import (
    EventKind,
    H4BarScheduler,
    PaperEvent,
    PaperTrader,
    SignalScanner,
    TradeJournal,
)

_shutdown = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    _shutdown.set()


def _setup_logging(log_file: str | None) -> logging.Logger:
    log = logging.getLogger("daemon_weekly_bos_retest")
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


def _sleep_until(target: datetime) -> None:
    """Sleep until *target* UTC, waking every second to check for shutdown."""
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


def _format_telegram(event: PaperEvent) -> str:
    lines = [
        f"*WeeklyBOSRetest Daemon* — {event.symbol}",
        f"Event : `{event.kind}`",
        f"Price : {event.price:.2f}",
    ]
    if event.kind in (EventKind.ENTRY_LONG, EventKind.ENTRY_SHORT):
        lines.append(f"SL    : {event.sl:.2f}" if event.sl is not None else "SL    : n/a")
        lines.append(f"TP    : {event.tp:.2f}" if event.tp is not None else "TP    : n/a")
    if event.pnl is not None:
        sign = "+" if event.pnl >= 0 else ""
        lines.append(f"PnL   : {sign}${event.pnl:.2f}")
    sign_c = "+" if event.cumulative_pnl >= 0 else ""
    lines.append(f"Cum PnL: {sign_c}${event.cumulative_pnl:.2f}")
    return "\n".join(lines)


_NOTIFY_KINDS = frozenset({
    EventKind.ENTRY_LONG,
    EventKind.ENTRY_SHORT,
    EventKind.EXIT_TP,
    EventKind.EXIT_SL,
    EventKind.EXIT_SIGNAL,
})


def _run_cycle(
    *,
    symbol: str,
    timeframe: str,
    lookback_days: int,
    state_path: Path,
    journal_path: Path,
    strategy_params: dict[str, object],
    api_key: str,
    telegram: bool,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    """Run one fetch→scan→paper-trade→journal cycle."""
    now = datetime.now(tz=UTC)
    fetch_start = now - timedelta(days=lookback_days)
    log.info("Fetching %s %s bars (%dd) …", symbol, timeframe, lookback_days)

    bars = fetch_bars(
        symbol=symbol,
        interval=timeframe,
        start=fetch_start,
        end=now,
        api_key=api_key,
    )
    if not bars:
        raise RuntimeError(f"No bars returned for {symbol} — check symbol and API key")
    log.info("  %d bars  [%s → %s]", len(bars), bars[0].ts.date(), bars[-1].ts.date())

    scanner = SignalScanner(
        symbol=symbol,
        timeframe=timeframe,
        strategy_params=strategy_params,
    )
    result = scanner.scan(bars)

    trader = PaperTrader(state_path)
    saved_dir: str = trader.position.direction
    saved_entry_price: float | None = trader.position.entry_price
    saved_entry_ts: str | None = trader.position.entry_ts
    saved_sl: float | None = trader.position.sl
    saved_tp: float | None = trader.position.tp

    event = trader.update(result, last_bar=bars[-1])
    log.info(
        "%s | %s | %s | price=%.2f cum_pnl=%+.2f",
        event.ts.strftime("%Y-%m-%d %H:%M UTC"),
        event.symbol,
        event.kind.value,
        event.price,
        event.cumulative_pnl,
    )

    if (
        event.kind in {EventKind.EXIT_TP, EventKind.EXIT_SL, EventKind.EXIT_SIGNAL}
        and saved_dir != "FLAT"
        and saved_entry_price is not None
        and saved_entry_ts is not None
    ):
        journal = TradeJournal(journal_path)
        journal.record_exit(
            symbol=symbol,
            direction=saved_dir,
            entry_price=saved_entry_price,
            entry_ts=saved_entry_ts,
            sl_at_entry=saved_sl,
            tp_at_entry=saved_tp,
            exit_event=event,
        )
        log.info("Trade recorded to %s", journal_path)

    if telegram and event.kind in _NOTIFY_KINDS:
        if not telegram_token or not telegram_chat_id:
            log.error("--telegram requires TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars")
        else:
            _send_telegram(telegram_token, telegram_chat_id, _format_telegram(event), log)
            log.info("Telegram notification sent.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daemon: paper-trade WeeklyBOSRetest on H4 bar closes."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--state-file", default=None)
    parser.add_argument("--journal-file", default=None)
    parser.add_argument("--log-file", default=None, help="Optional rotating log file path")
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send Telegram alerts on ENTRY/EXIT events",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    state_path = (
        Path(args.state_file) if args.state_file
        else Path(f"data/paper_state_{symbol}.json")
    )
    journal_path = (
        Path(args.journal_file) if args.journal_file
        else Path(f"data/journal_{symbol}.jsonl")
    )

    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print("ERROR: TWELVEDATA_API_KEY env var is not set.", file=sys.stderr)
        sys.exit(1)

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "") if args.telegram else ""
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "") if args.telegram else ""

    log = _setup_logging(args.log_file)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    strategy_params: dict[str, object] = {
        "ema_fast": args.ema_fast,
        "ema_slow": args.ema_slow,
        "ob_buffer_pips": args.ob_buffer_pips,
        "max_risk_pips": args.max_risk_pips,
        "risk_reward": args.risk_reward,
    }

    log.info("Daemon started — %s %s  state=%s", symbol, args.timeframe, state_path)

    while not _shutdown.is_set():
        nxt = H4BarScheduler.next_bar_close(datetime.now(tz=UTC))
        log.info("Next H4 close: %s UTC — sleeping …", nxt.strftime("%Y-%m-%d %H:%M:%S"))
        _sleep_until(nxt)

        if _shutdown.is_set():
            break

        try:
            _run_cycle(
                symbol=symbol,
                timeframe=args.timeframe,
                lookback_days=args.lookback_days,
                state_path=state_path,
                journal_path=journal_path,
                strategy_params=strategy_params,
                api_key=api_key,
                telegram=args.telegram,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
                log=log,
            )
        except Exception:  # noqa: BLE001
            log.exception("Cycle failed — will retry at next bar close")

    log.info("Daemon stopped.")


if __name__ == "__main__":
    main()
