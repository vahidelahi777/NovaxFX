"""End-to-end research script: load bars → quality check → backtest → metrics.

Usage (after data has been ingested with ingest_dukascopy.py):

  .venv/bin/python scripts/run_research.py \\
      --symbol EURUSD \\
      --start  2018-01-01 \\
      --end    2024-12-31 \\
      --fast   20 \\
      --slow   50 \\
      --data-dir data/market

Output: train + OOS metrics, plus a data-quality summary.
The 70/30 train/test split is applied to the bar sequence (SimpleWalkForward).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.data.storage.parquet_store import ParquetStore
from novax.dataquality import run_data_quality
from novax.engine import BacktestEngine
from novax.metrics import compute_basic_metrics
from novax.strategies.ema_cross import EMACross
from novax.walkforward import SimpleWalkForward


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _fmt(label: str, value: float, unit: str = "") -> str:
    return f"  {label:<30} {value:>12.4f}{unit}"


def _print_metrics(metrics: dict[str, float], prefix: str = "") -> None:
    n = int(metrics["trade_count"])
    print(f"{prefix}  Trades         : {n}")
    print(f"{prefix}  Total PnL      : ${metrics['total_return']:>10.2f}")
    print(f"{prefix}  Avg trade PnL  : ${metrics['avg_trade_pnl']:>10.2f}")
    print(f"{prefix}  Win rate       : {metrics['win_rate']:>10.1%}")
    print(f"{prefix}  Sharpe (raw)   : {metrics['sharpe_ratio']:>10.4f}")
    print(f"{prefix}  Max DD (abs)   : ${metrics['max_drawdown_abs']:>10.2f}")
    print(f"{prefix}  Max DD (pct)   : {metrics['max_drawdown_pct']:>10.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run EMA-cross strategy on Dukascopy 1-minute bars."
    )
    parser.add_argument("--symbol", required=True, help="Instrument, e.g. EURUSD")
    parser.add_argument("--start", required=True, help="Data start date (YYYY-MM-DD, inclusive)")
    parser.add_argument("--end", required=True, help="Data end date (YYYY-MM-DD, inclusive)")
    parser.add_argument("--fast", type=int, default=20, help="Fast EMA period (default 20)")
    parser.add_argument("--slow", type=int, default=50, help="Slow EMA period (default 50)")
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.7,
        help="Fraction of bars used for training (default 0.7)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/market",
        help="Root directory of Parquet files (default: data/market)",
    )
    parser.add_argument(
        "--timeframe",
        default="1m",
        help="Timeframe label (default: 1m)",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.90,
        help="Minimum bar-coverage for data-quality gate (default 0.90)",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    print(f"\n{'='*60}")
    print(f"  {symbol}  EMA({args.fast}/{args.slow})  {args.start} → {args.end}")
    print(f"{'='*60}")

    # ── 1. Load bars ──────────────────────────────────────────────────────────
    root = Path(args.data_dir)
    bars = load_bars(root, symbol, args.timeframe, start, end)

    if len(bars) < args.slow * 2:
        print(f"ERROR: only {len(bars)} bars loaded — not enough for warmup. Is data ingested?",
              file=sys.stderr)
        sys.exit(1)

    print(f"\nLoaded {len(bars):,} bars")
    print(f"  First : {bars[0].ts.isoformat()}")
    print(f"  Last  : {bars[-1].ts.isoformat()}")

    # ── 2. Data-quality check ─────────────────────────────────────────────────
    report = run_data_quality(
        symbol, args.timeframe, bars, min_coverage=args.min_coverage
    )
    status = "PASSED" if report.passed else "FAILED"
    print(f"\nData quality : {status}  ({len(report.checks)} checks)")
    for c in report.checks:
        icon = "✓" if c.passed else "✗"
        sev = f"[{c.severity}]" if not c.passed else ""
        print(f"  {icon} {c.name:<35} {c.detail} {sev}")

    if not report.passed:
        print("\nERROR: data-quality gate failed — engine will refuse to run.", file=sys.stderr)
        print("Tip: try --min-coverage 0.0 for exploratory work.", file=sys.stderr)
        sys.exit(1)

    # ── 3. Train / test split (SimpleWalkForward) ─────────────────────────────
    wf = SimpleWalkForward(train_ratio=args.train_ratio)
    train_bars, test_bars = wf.split(bars)

    print(f"\nSplit ({args.train_ratio:.0%} train / {1 - args.train_ratio:.0%} test)")
    print(f"  Train: {len(train_bars):>8,} bars  [{train_bars[0].ts.date()} → {train_bars[-1].ts.date()}]")
    print(f"  Test : {len(test_bars):>8,} bars  [{test_bars[0].ts.date()} → {test_bars[-1].ts.date()}]")

    engine = BacktestEngine(symbol, args.timeframe)

    # ── 4. Train run ──────────────────────────────────────────────────────────
    train_report = run_data_quality(
        symbol, args.timeframe, train_bars, min_coverage=args.min_coverage
    )
    if not train_report.passed:
        print("\nWARN: train data-quality check failed — continuing anyway.")

    train_result = engine.run(train_bars, EMACross(fast=args.fast, slow=args.slow), train_report)
    train_m = compute_basic_metrics(train_result)

    print(f"\n--- TRAIN ({args.start} → {train_bars[-1].ts.date()}) ---")
    _print_metrics(train_m)

    # ── 5. OOS (test) run ─────────────────────────────────────────────────────
    test_report = run_data_quality(
        symbol, args.timeframe, test_bars, min_coverage=args.min_coverage
    )
    if not test_report.passed:
        print("\nWARN: test data-quality check failed — continuing anyway.")

    test_result = engine.run(test_bars, EMACross(fast=args.fast, slow=args.slow), test_report)
    test_m = compute_basic_metrics(test_result)

    print(f"\n--- OOS TEST ({test_bars[0].ts.date()} → {args.end}) ---")
    _print_metrics(test_m)

    # ── 6. Summary ────────────────────────────────────────────────────────────
    oos_sharpe = test_m["sharpe_ratio"]
    oos_pnl = test_m["total_return"]
    degradation = (
        (train_m["sharpe_ratio"] - oos_sharpe) / abs(train_m["sharpe_ratio"])
        if train_m["sharpe_ratio"] != 0 else float("nan")
    )

    print(f"\n--- SUMMARY ---")
    print(f"  OOS Sharpe        : {oos_sharpe:.4f}")
    print(f"  OOS Total PnL     : ${oos_pnl:.2f}")
    print(f"  Sharpe degradation: {degradation:+.1%}  (train → OOS)")
    if train_m["trade_count"] > 0 and test_m["trade_count"] > 0:
        hold_ratio = test_m["trade_count"] / train_m["trade_count"]
        print(f"  Trade-count ratio : {hold_ratio:.2f}  (OOS / train)")

    verdict = "PROMISING" if oos_sharpe > 0.2 and oos_pnl > 0 else "WEAK / NEEDS WORK"
    print(f"\n  Preliminary verdict: {verdict}")
    print(f"  (Run full gate validation before drawing any conclusions.)\n")


if __name__ == "__main__":
    main()
