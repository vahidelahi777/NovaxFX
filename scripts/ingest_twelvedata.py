"""CLI: Download Twelve Data bars, validate, and store as Parquet.

Usage:
  export TWELVEDATA_API_KEY=<your_key>
  .venv/bin/python scripts/ingest_twelvedata.py \\
      --symbol EURUSD \\
      --interval 4h \\
      --start 2023-01-01 \\
      --end 2026-07-08 \\
      --output-dir data/market

The API key is read from TWELVEDATA_API_KEY env var (preferred) or --api-key.
Never pass the key as a positional arg or embed it in scripts committed to git.

Twelve Data interval → internal timeframe label mapping:
  1min → 1m  |  5min → 5m  |  1h → 1h  |  4h → 4h  |  1day → 1d

Basic plan limits: 800 credits/day, 8 req/min.
For 4h bars the full 3-year history fits in a single API call (< 5000 bars).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from novax.data.ingest.twelvedata import fetch_bars
from novax.data.storage.parquet_store import ParquetStore
from novax.dataquality import run_data_quality
from novax.instruments import get_instrument
from novax.market_calendar import DEFAULT_FX_CALENDAR

# Maps Twelve Data interval strings to our internal timeframe labels.
_TD_TO_TF: dict[str, str] = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1h": "1h",
    "4h": "4h",
    "1day": "1d",
}


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Twelve Data bars and store as Parquet."
    )
    parser.add_argument("--symbol", required=True, help="Instrument, e.g. EURUSD or EUR/USD")
    parser.add_argument(
        "--interval",
        default="4h",
        choices=list(_TD_TO_TF),
        help="Twelve Data interval (default: 4h)",
    )
    parser.add_argument("--start", required=True, help="Start date inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date inclusive (YYYY-MM-DD)")
    parser.add_argument("--output-dir", required=True, help="Root directory for Parquet files")
    parser.add_argument(
        "--api-key",
        default="",
        help="Twelve Data API key (prefer TWELVEDATA_API_KEY env var)",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="Min bar coverage for data-quality gate (default 0.0 = skip coverage check)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=8.0,
        help="Seconds between paginated requests (default 8.0 respects 8 req/min limit)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print(
            "ERROR: provide --api-key or set TWELVEDATA_API_KEY env var",
            file=sys.stderr,
        )
        sys.exit(1)

    symbol = args.symbol.upper()
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    timeframe = _TD_TO_TF[args.interval]

    try:
        inst = get_instrument(symbol)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nIngesting {inst.symbol}  |  {args.interval} ({timeframe})"
          f"  |  {args.start} → {args.end}")
    print(f"Output root: {args.output_dir}\n")

    bars = fetch_bars(
        symbol,
        args.interval,
        start,
        end,
        api_key,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )

    if not bars:
        print(
            f"ERROR: no bars returned for {inst.symbol} {args.interval} "
            f"({args.start}→{args.end}).\n"
            "Check symbol, interval, date range, and plan depth.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetched {len(bars):,} bars")
    print(f"  First : {bars[0].ts.isoformat()}")
    print(f"  Last  : {bars[-1].ts.isoformat()}")

    # Strip bars outside FX market hours (weekend boundaries, holidays).
    # 4h bars near Sunday-open / Friday-close fall outside is_open() depending on DST.
    before = len(bars)
    bars = [b for b in bars if DEFAULT_FX_CALENDAR.is_open(b.ts)]
    dropped = before - len(bars)
    if dropped:
        print(f"  Dropped {dropped} bars outside FX market hours (weekends/holidays)")

    if not bars:
        print("ERROR: no bars remain after market-hours filter.", file=sys.stderr)
        sys.exit(1)

    report = run_data_quality(
        inst.symbol, timeframe, bars, min_coverage=args.min_coverage
    )
    status = "PASSED" if report.passed else "FAILED"
    print(f"\nData quality : {status}  ({len(report.checks)} checks)")
    for c in report.checks:
        icon = "✓" if c.passed else "✗"
        sev = f" [{c.severity}]" if not c.passed else ""
        print(f"  {icon} {c.name:<35} {c.detail}{sev}")

    if not report.passed:
        print("\nERROR: data-quality gate failed — bars NOT written.", file=sys.stderr)
        sys.exit(1)

    store = ParquetStore(Path(args.output_dir))
    store.write_bars(inst.symbol, timeframe, bars)

    print(f"\nOK — {len(bars):,} bars written to {args.output_dir}/{inst.symbol}/{timeframe}/")


if __name__ == "__main__":
    main()
