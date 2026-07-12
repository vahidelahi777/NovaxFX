"""CLI: Run GoldPullback strategy on real XAU/USD H4 data and print metrics.

Usage:
    .venv/bin/python scripts/run_gold_pullback.py

Loads all available XAU/USD 4h bars from data/market/, runs a 70/30
walk-forward split, and prints train + test performance metrics.

Note: pip_value_per_lot for XAU/USD is a nominal placeholder ($10/pip).
Real gold = $100/pip per lot (100oz × $1/pip/oz). All PnL figures are
therefore understated by 10×. This is a known Phase 1 limitation.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.dataquality import run_data_quality
from novax.engine import BacktestEngine
from novax.metrics import compute_basic_metrics
from novax.strategies.gold_pullback import GoldPullback
from novax.walkforward import SimpleWalkForward

_DATA_ROOT = Path("data/market")
_SYMBOL = "XAU/USD"
_TIMEFRAME = "4h"
_START = datetime(2023, 1, 1, tzinfo=UTC)
_END = datetime(2026, 12, 31, tzinfo=UTC)


def _print_metrics(label: str, bars: list, metrics: dict) -> None:  # type: ignore[type-arg]
    first_ts = bars[0].ts.strftime("%Y-%m-%d")
    last_ts = bars[-1].ts.strftime("%Y-%m-%d")
    print(f"\n  {label}  {first_ts} → {last_ts}    {len(bars):,} bars")
    print("  " + "─" * 53)
    print(f"  trades        : {int(metrics['trade_count'])}")
    print(f"  win_rate      : {metrics['win_rate'] * 100:.1f}%")
    print(f"  total_return  : ${metrics['total_return']:,.2f}")
    print(f"  avg_trade_pnl : ${metrics['avg_trade_pnl']:,.2f}")
    print(f"  sharpe_ratio  : {metrics['sharpe_ratio']:.2f}")
    print(f"  max_drawdown  : {metrics['max_drawdown_pct'] * 100:.1f}%")


def main() -> None:
    print(f"\nLoading {_SYMBOL} {_TIMEFRAME} bars from {_DATA_ROOT} …")
    bars = load_bars(_DATA_ROOT, _SYMBOL, _TIMEFRAME, _START, _END)
    if not bars:
        print(f"ERROR: no bars found under {_DATA_ROOT}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(bars):,} bars  ({bars[0].ts.date()} → {bars[-1].ts.date()})")

    report = run_data_quality(_SYMBOL, _TIMEFRAME, bars, min_coverage=0.8)
    status = "PASSED" if report.passed else "FAILED"
    print(f"Data quality  : {status}  ({len(report.checks)} checks)")
    if not report.passed:
        for c in report.failures():
            print(f"  ✗ {c.name}: {c.detail}", file=sys.stderr)
        sys.exit(1)

    train_bars, test_bars = SimpleWalkForward(train_ratio=0.7).split(bars)

    engine = BacktestEngine(symbol=_SYMBOL, timeframe=_TIMEFRAME)

    print(f"\n{'=' * 49}")
    print(f"  GoldPullback  {_SYMBOL} {_TIMEFRAME}")
    print(f"{'=' * 49}")

    train_result = engine.run(train_bars, GoldPullback(), report)
    train_metrics = compute_basic_metrics(train_result)
    _print_metrics("TRAIN", train_bars, train_metrics)

    test_result = engine.run(test_bars, GoldPullback(), report)
    test_metrics = compute_basic_metrics(test_result)
    _print_metrics("TEST ", test_bars, test_metrics)

    print(
        "\n  Note: pip_value_per_lot=$10 (nominal placeholder)."
        " Real XAU/USD = $100/pip/lot.\n"
        "  Multiply all $ figures by 10 for realistic PnL estimates.\n"
    )


if __name__ == "__main__":
    main()
