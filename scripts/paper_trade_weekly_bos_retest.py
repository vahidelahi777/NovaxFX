"""CLI: paper-trade WeeklyBOSRetest on live H4 bars (one invocation per bar close).

Designed to be called by a cron job or systemd timer every 4 hours.
State persists across invocations in a JSON file so no position context is lost
on process restart.

Usage:
  .venv/bin/python scripts/paper_trade_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      --lookback-days 90 \\
      --state-file data/paper_state_XAUUSD.json \\
      [--telegram]

Required env vars:
  TWELVEDATA_API_KEY   — Twelve Data API key (never pass as CLI arg)

Required env vars for --telegram:
  TELEGRAM_TOKEN       — Bot token  (never log or print)
  TELEGRAM_CHAT_ID     — Target chat ID

Security: API key and Telegram token are never logged or printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from novax.data.ingest.twelvedata import fetch_bars
from novax.live import (
    EventKind,
    PaperEvent,
    PaperPosition,
    PaperTrader,
    SignalScanner,
    TradeJournal,
)


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat_id)}"
        f"&text={urllib.parse.quote(text)}"
        f"&parse_mode=Markdown"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                print(f"WARN: Telegram returned HTTP {resp.status}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Telegram send failed: {exc}", file=sys.stderr)


def _log_line(event: PaperEvent, pos: PaperPosition) -> str:
    ts_str = event.ts.strftime("%Y-%m-%d %H:%M UTC")
    kind = event.kind.value
    sym = event.symbol

    if event.kind == EventKind.NO_CHANGE:
        detail = "(flat)"

    elif event.kind in (EventKind.ENTRY_LONG, EventKind.ENTRY_SHORT):
        sl_str = f"{event.sl:.2f}" if event.sl is not None else "n/a"
        tp_str = f"{event.tp:.2f}" if event.tp is not None else "n/a"
        sign = "+" if event.cumulative_pnl >= 0 else ""
        detail = (
            f"price={event.price:.2f}  sl={sl_str}  tp={tp_str}"
            f"  cum_pnl={sign}${event.cumulative_pnl:.2f}"
        )

    elif event.kind == EventKind.HOLD:
        since = (
            pos.entry_ts[:16].replace("T", " ") if pos.entry_ts else "?"
        )
        detail = f"({pos.direction.lower()} since {since})"

    else:  # EXIT_TP / EXIT_SL / EXIT_SIGNAL
        pnl = event.pnl if event.pnl is not None else 0.0
        sign_p = "+" if pnl >= 0 else ""
        sign_c = "+" if event.cumulative_pnl >= 0 else ""
        detail = (
            f"price={event.price:.2f}"
            f"  pnl={sign_p}${pnl:.2f}"
            f"  cum_pnl={sign_c}${event.cumulative_pnl:.2f}"
        )

    return f"{ts_str} | {sym} | {kind:<15} | {detail}"


def _format_telegram(event: PaperEvent) -> str:
    lines = [
        f"*WeeklyBOSRetest Paper Trade* — {event.symbol}",
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paper-trade WeeklyBOSRetest on live H4 bars (one call per bar close)."
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Instrument (default: XAUUSD)")
    parser.add_argument("--timeframe", default="4h", help="Timeframe (default: 4h)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Days of H4 history to fetch (default: 90)",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Path to JSON state file (default: data/paper_state_{SYMBOL}.json)",
    )
    parser.add_argument(
        "--journal-file",
        default=None,
        help="Path to JSONL trade journal (default: data/journal_{SYMBOL}.jsonl)",
    )
    # Strategy params
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    parser.add_argument(
        "--telegram",
        action="store_true",
        help=(
            "Send Telegram alert on ENTRY/EXIT events "
            "(reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from env)"
        ),
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

    # -- Fetch live bars ------------------------------------------------------
    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print(
            "ERROR: TWELVEDATA_API_KEY env var is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    now = datetime.now(tz=UTC)
    fetch_start = now - timedelta(days=args.lookback_days)
    print(f"Fetching {symbol} {args.timeframe} bars ({args.lookback_days}d) …")
    bars = fetch_bars(
        symbol=symbol,
        interval=args.timeframe,
        start=fetch_start,
        end=now,
        api_key=api_key,
    )
    if not bars:
        print("ERROR: no bars returned — check symbol and API key.", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(bars):,} bars  [{bars[0].ts.date()} → {bars[-1].ts.date()}]")

    # -- Scan -----------------------------------------------------------------
    scanner = SignalScanner(
        symbol=symbol,
        timeframe=args.timeframe,
        strategy_params={
            "ema_fast": args.ema_fast,
            "ema_slow": args.ema_slow,
            "ob_buffer_pips": args.ob_buffer_pips,
            "max_risk_pips": args.max_risk_pips,
            "risk_reward": args.risk_reward,
        },
    )
    result = scanner.scan(bars)

    # -- Paper trade ----------------------------------------------------------
    trader = PaperTrader(state_path)

    saved_dir = trader.position.direction
    saved_entry_price = trader.position.entry_price
    saved_entry_ts = trader.position.entry_ts
    saved_sl = trader.position.sl
    saved_tp = trader.position.tp

    event = trader.update(result, last_bar=bars[-1])

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

    # -- Log ------------------------------------------------------------------
    print(_log_line(event, trader.position))

    # -- Telegram (ENTRY / EXIT events only) ----------------------------------
    if args.telegram and event.kind in _NOTIFY_KINDS:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            print(
                "ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars required for --telegram.",
                file=sys.stderr,
            )
            sys.exit(1)
        _send_telegram(token, chat_id, _format_telegram(event))
        print("Telegram notification sent.")


if __name__ == "__main__":
    main()
