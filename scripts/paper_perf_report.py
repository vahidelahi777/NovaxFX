"""CLI: print performance report from a paper-trading JSONL journal.

No API keys or network access required — reads a local JSONL file only.

Usage:
  .venv/bin/python scripts/paper_perf_report.py \\
      --journal-file data/journal_XAUUSD.jsonl \\
      --symbol XAUUSD \\
      --timeframe 4h \\
      [--since 2024-06-01]
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

from novax.live import TradeJournal, compute_performance

_SEP = "═" * 46


def _fmt_float(val: float, fmt: str, prefix: str = "") -> str:
    if math.isnan(val):
        return "n/a"
    if math.isinf(val):
        return "∞" if val > 0 else "-∞"
    sign = "+" if val >= 0 else ""
    return f"{prefix}{sign}{val:{fmt}}"


def _print_report(symbol: str, timeframe: str, journal_path: Path, since: datetime | None) -> None:
    journal = TradeJournal(journal_path)
    trades = journal.load()

    if since is not None:
        trades = [t for t in trades if t.exit_ts >= since]

    if not trades:
        suffix = f" since {since.date()}" if since else ""
        print(f"No trades found in {journal_path}{suffix}.")
        return

    report = compute_performance(trades, symbol=symbol, timeframe=timeframe)

    first = report.first_trade_ts
    last = report.last_trade_ts
    days = (last - first).days if first and last else 0

    print(f"\nWeeklyBOSRetest Paper Performance — {report.symbol} {report.timeframe}")
    if first and last:
        print(f"Period: {first.date()} → {last.date()}  ({days} days, {report.trade_count} trades)")
    print(_SEP)

    win_str = f"{report.win_rate:.1%}" if not math.isnan(report.win_rate) else "n/a"
    pnl_str = _fmt_float(report.total_pnl, ".2f", "$")
    avg_str = _fmt_float(report.avg_pnl, ".2f", "$")
    pf_str = _fmt_float(report.profit_factor, ".2f")
    dd_str = (
        f"-${report.max_drawdown_abs:.2f}" if report.max_drawdown_abs > 0
        else "$0.00"
    )
    sr_str = _fmt_float(report.sharpe_ratio, ".2f")

    print(f"  Win rate       : {win_str:>10}")
    print(f"  Total PnL      : {pnl_str:>10}")
    print(f"  Avg trade PnL  : {avg_str:>10}")
    print(f"  Profit factor  : {pf_str:>10}")
    print(f"  Max DD (abs)   : {dd_str:>10}")
    print(f"  Sharpe (raw)   : {sr_str:>10}")
    print(_SEP)

    for kind, count in sorted(report.exit_counts.items()):
        pct = count / report.trade_count
        print(f"  {kind:<15}: {count:>3}  ({pct:.1%})")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print performance report from a paper-trading JSONL journal."
    )
    parser.add_argument(
        "--journal-file",
        required=True,
        help="Path to JSONL trade journal (e.g. data/journal_XAUUSD.jsonl)",
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Instrument label (default: XAUUSD)")
    parser.add_argument("--timeframe", default="4h", help="Timeframe label (default: 4h)")
    parser.add_argument(
        "--since",
        default=None,
        help="Filter trades exited on or after this date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    journal_path = Path(args.journal_file)
    if not journal_path.exists():
        print(f"Journal file not found: {journal_path}")
        sys.exit(0)

    since_dt: datetime | None = None
    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)

    _print_report(args.symbol.upper(), args.timeframe, journal_path, since_dt)


if __name__ == "__main__":
    main()
