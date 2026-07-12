"""CLI: scan WeeklyBOSRetest signal on the most recent H4 bars.

Loads bars from local Parquet files (or fetches live from Twelve Data),
runs the signal scanner, and optionally sends a Telegram notification.

Usage:

  # Scan from local data (already ingested):
  .venv/bin/python scripts/scan_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      --data-dir data/market

  # Fetch live and scan (requires API key via env var TWELVEDATA_API_KEY):
  .venv/bin/python scripts/scan_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      --live \\
      --lookback-days 30

  # With Telegram alert (requires TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars):
  .venv/bin/python scripts/scan_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      --live \\
      --telegram

Security note: Never pass --api-key or --telegram-token as plain CLI args in
production; use environment variables instead to avoid key exposure in shell
history or process listings.
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
from novax.data.loader.bar_loader import load_bars
from novax.engine import Signal
from novax.live import SignalScanner


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


def _format_signal(result: novax.live.ScanResult) -> str:  # type: ignore[name-defined]  # noqa: F821
    lines = [
        f"*WeeklyBOSRetest Signal* — {result.symbol} {result.timeframe}",
        f"As of: {result.ts.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Signal : `{result.signal}`",
        f"BOS    : `{result.bos_state}` | OB: {'yes' if result.has_ob else 'no'}",
    ]
    if result.has_ob:
        lines.append(f"OB zone: {result.ob_low:.2f} – {result.ob_high:.2f}")
    if result.prev_week_high is not None:
        lines.append(
            f"Prev week: H={result.prev_week_high:.2f}  L={result.prev_week_low:.2f}"
        )
    if result.signal != Signal.FLAT and result.sl is not None:
        lines.append(f"SL={result.sl:.2f}  TP={result.tp:.2f}")
    lines.append(f"Bars used: {result.n_bars_used}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan WeeklyBOSRetest signal on H4 bars."
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Instrument (default: XAUUSD)")
    parser.add_argument("--timeframe", default="4h", help="Timeframe (default: 4h)")

    # Data source (mutually exclusive)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--data-dir",
        default=None,
        help="Load from local Parquet files at this root directory",
    )
    source.add_argument(
        "--live",
        action="store_true",
        help="Fetch most recent bars live from Twelve Data",
    )

    # Live-fetch options
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Days of history to fetch in live mode (default: 90)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Start date YYYY-MM-DD for local Parquet load (required with --data-dir)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date YYYY-MM-DD for local Parquet load (defaults to today)",
    )
    # Strategy params
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)

    # Notification
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send result via Telegram (reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from env)",
    )

    args = parser.parse_args()
    symbol = args.symbol.upper()

    # Resolve bars
    if args.live or args.data_dir is None:
        api_key = os.environ.get("TWELVEDATA_API_KEY", "")
        if not api_key:
            print(
                "ERROR: TWELVEDATA_API_KEY env var is not set (required for live fetch).",
                file=sys.stderr,
            )
            sys.exit(1)
        now = datetime.now(tz=UTC)
        fetch_start = now - timedelta(days=args.lookback_days)
        print(f"Fetching live {symbol} {args.timeframe} bars from Twelve Data …")
        bars = fetch_bars(
            symbol=symbol,
            interval=args.timeframe,
            start=fetch_start,
            end=now,
            api_key=api_key,
        )
    else:
        end_dt = (
            datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)
            if args.end
            else datetime.now(tz=UTC)
        )
        if args.start is None:
            print(
                "ERROR: --start is required when using --data-dir.",
                file=sys.stderr,
            )
            sys.exit(1)
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
        root = Path(args.data_dir)
        print(f"Loading {symbol} {args.timeframe} bars from {root} …")
        bars = load_bars(root, symbol, args.timeframe, start_dt, end_dt)

    if not bars:
        print("ERROR: no bars loaded — check data source.", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(bars):,} bars  [{bars[0].ts.date()} → {bars[-1].ts.date()}]")

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
    formatted = _format_signal(result)

    print()
    print(formatted.replace("*", "").replace("`", ""))

    if args.telegram:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            print(
                "ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars required for --telegram.",
                file=sys.stderr,
            )
            sys.exit(1)
        _send_telegram(token, chat_id, formatted)
        print("Telegram notification sent.")


if __name__ == "__main__":
    main()
