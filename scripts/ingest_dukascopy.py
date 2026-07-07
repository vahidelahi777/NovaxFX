"""CLI: Download Dukascopy tick data, normalize to 1-minute bars, and store as Parquet.

Usage:
  python scripts/ingest_dukascopy.py \\
      --symbol EURUSD \\
      --start 2020-01-01 \\
      --end 2020-01-31 \\
      --output-dir data/market

Each calendar day in [start, end] is processed independently:
  1. Download 24 hourly .bi5 files from Dukascopy.
  2. Parse ticks (LZMA decompress + binary unpack).
  3. Aggregate ticks into 1-minute OHLCV bars (mid-price).
  4. Validate the day (minimum bar count, non-positive prices).
  5. Append bars to the monthly Parquet file.

Days that fail validation are logged as warnings and skipped (not written).
Weekends and market holidays naturally have 0 ticks and are skipped silently.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from novax.data.cleaning.normalize import ticks_to_1m_bars
from novax.data.cleaning.validation import validate_day
from novax.data.ingest.dukascopy import fetch_day_ticks
from novax.data.storage.parquet_store import ParquetStore


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _date_range(start: datetime, end: datetime) -> list[datetime]:
    days: list[datetime] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = cur + timedelta(days=1)
    return days


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Dukascopy tick data and store as 1-minute Parquet bars."
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol, e.g. EURUSD")
    parser.add_argument("--start", required=True, help="Start date inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date inclusive (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Root directory for Parquet files (e.g. data/market)",
    )
    parser.add_argument(
        "--timeframe",
        default="1m",
        help="Timeframe label written into the path (default: 1m)",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=100,
        help="Minimum 1-minute bars required for a day to be written (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.3,
        help="Seconds to sleep between hourly requests to avoid rate-limiting (default: 0.3)",
    )
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if start > end:
        print(f"ERROR: --start {args.start} is after --end {args.end}", file=sys.stderr)
        sys.exit(1)

    root = Path(args.output_dir)
    store = ParquetStore(root)
    days = _date_range(start, end)
    symbol: str = args.symbol.upper()

    print(f"Ingesting {symbol} | {args.start} → {args.end} ({len(days)} days) | output: {root}")

    ok_days = 0
    skipped_days = 0
    failed_days = 0

    for day in days:
        label = day.strftime("%Y-%m-%d")
        try:
            ticks = fetch_day_ticks(
                symbol, day, timeout=args.timeout, request_delay=args.request_delay
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [{label}] ERROR fetching ticks: {exc}", file=sys.stderr)
            failed_days += 1
            continue

        if not ticks:
            # Typical for weekends/holidays — silent skip.
            skipped_days += 1
            continue

        hours_with_data = len({t.ts.replace(minute=0, second=0, microsecond=0) for t in ticks})
        bars = ticks_to_1m_bars(ticks, symbol=symbol)
        report = validate_day(
            symbol,
            day,
            ticks_fetched=len(ticks),
            bars=bars,
            hours_with_data=hours_with_data,
            min_bars=args.min_bars,
        )

        if not report.passed:
            for w in report.warnings:
                print(f"  [{label}] WARN: {w}", file=sys.stderr)
            skipped_days += 1
            continue

        if report.warnings:
            for w in report.warnings:
                print(f"  [{label}] WARN: {w}")

        store.write_bars(symbol, args.timeframe, bars)
        print(
            f"  [{label}] OK — {report.ticks_fetched} ticks, "
            f"{report.bars_generated} bars, {report.hours_with_data}h with data"
        )
        ok_days += 1

    print(
        f"\nDone: {ok_days} written, {skipped_days} skipped, {failed_days} errors "
        f"out of {len(days)} days."
    )
    if failed_days > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
