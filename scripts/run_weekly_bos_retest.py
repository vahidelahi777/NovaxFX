"""CLI: run WeeklyBOSRetest strategy on H4 Dukascopy/Twelve Data bars.

Usage (after data has been ingested):

  .venv/bin/python scripts/run_weekly_bos_retest.py \\
      --symbol XAUUSD \\
      --start  2022-01-01 \\
      --end    2025-12-31 \\
      --data-dir data/market

Output: train + OOS metrics, 70/30 walk-forward split.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.dataquality import run_data_quality
from novax.engine import BacktestEngine
from novax.metrics import compute_basic_metrics
from novax.strategies.weekly_bos_retest import WeeklyBOSRetest
from novax.walkforward import SimpleWalkForward


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


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
        description="Run WeeklyBOSRetest strategy on H4 bars."
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Instrument (default: XAUUSD)")
    parser.add_argument("--start", required=True, help="Data start date (YYYY-MM-DD, inclusive)")
    parser.add_argument("--end", required=True, help="Data end date (YYYY-MM-DD, inclusive)")
    parser.add_argument(
        "--data-dir", default="data/market", help="Root directory of Parquet files"
    )
    parser.add_argument("--timeframe", default="4h", help="Timeframe label (default: 4h)")
    parser.add_argument(
        "--train-ratio", type=float, default=0.7, help="Train fraction (default: 0.7)"
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.80,
        help="Minimum bar-coverage for data-quality gate (default 0.80)",
    )
    # Strategy params
    parser.add_argument("--ema-fast", type=int, default=20, help="Fast EMA period (default 20)")
    parser.add_argument("--ema-slow", type=int, default=50, help="Slow EMA period (default 50)")
    parser.add_argument(
        "--ob-buffer-pips",
        type=float,
        default=5.0,
        help="Pips beyond OB edge for SL (default 5.0)",
    )
    parser.add_argument(
        "--max-risk-pips",
        type=float,
        default=80.0,
        help="Max SL distance in pips (default 80.0)",
    )
    parser.add_argument(
        "--risk-reward", type=float, default=2.0, help="TP risk-reward ratio (default 2.0)"
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    print(f"\n{'='*60}")
    print(f"  {symbol}  WeeklyBOSRetest  {args.start} → {args.end}")
    print(f"  EMA({args.ema_fast}/{args.ema_slow})  OB-buf={args.ob_buffer_pips}pip"
          f"  MaxRisk={args.max_risk_pips}pip  RR={args.risk_reward}")
    print(f"{'='*60}")

    root = Path(args.data_dir)
    bars = load_bars(root, symbol, args.timeframe, start, end)

    if len(bars) < args.ema_slow * 4:
        print(
            f"ERROR: only {len(bars)} bars — not enough for warmup. Is data ingested?",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\nLoaded {len(bars):,} bars")
    print(f"  First : {bars[0].ts.isoformat()}")
    print(f"  Last  : {bars[-1].ts.isoformat()}")

    report = run_data_quality(symbol, args.timeframe, bars, min_coverage=args.min_coverage)
    status = "PASSED" if report.passed else "FAILED"
    print(f"\nData quality : {status}  ({len(report.checks)} checks)")
    for c in report.checks:
        icon = "✓" if c.passed else "✗"
        sev = f" [{c.severity}]" if not c.passed else ""
        print(f"  {icon} {c.name:<35} {c.detail}{sev}")

    if not report.passed:
        print("\nERROR: data-quality gate failed — engine will refuse to run.", file=sys.stderr)
        print("Tip: try --min-coverage 0.0 for exploratory work.", file=sys.stderr)
        sys.exit(1)

    wf = SimpleWalkForward(train_ratio=args.train_ratio)
    train_bars, test_bars = wf.split(bars)

    print(f"\nSplit ({args.train_ratio:.0%} train / {1 - args.train_ratio:.0%} test)")
    print(
        f"  Train: {len(train_bars):>8,} bars"
        f"  [{train_bars[0].ts.date()} → {train_bars[-1].ts.date()}]"
    )
    print(
        f"  Test : {len(test_bars):>8,} bars"
        f"  [{test_bars[0].ts.date()} → {test_bars[-1].ts.date()}]"
    )

    def _make_strategy() -> WeeklyBOSRetest:
        return WeeklyBOSRetest(
            ema_fast=args.ema_fast,
            ema_slow=args.ema_slow,
            ob_buffer_pips=args.ob_buffer_pips,
            max_risk_pips=args.max_risk_pips,
            risk_reward=args.risk_reward,
        )

    engine = BacktestEngine(symbol, args.timeframe)

    train_report = run_data_quality(
        symbol, args.timeframe, train_bars, min_coverage=args.min_coverage
    )
    if not train_report.passed:
        print("\nWARN: train data-quality check failed — continuing anyway.")

    train_result = engine.run(train_bars, _make_strategy(), train_report)
    train_m = compute_basic_metrics(train_result)

    print(f"\n--- TRAIN ({args.start} → {train_bars[-1].ts.date()}) ---")
    _print_metrics(train_m)

    test_report = run_data_quality(
        symbol, args.timeframe, test_bars, min_coverage=args.min_coverage
    )
    if not test_report.passed:
        print("\nWARN: test data-quality check failed — continuing anyway.")

    test_result = engine.run(test_bars, _make_strategy(), test_report)
    test_m = compute_basic_metrics(test_result)

    print(f"\n--- OOS TEST ({test_bars[0].ts.date()} → {args.end}) ---")
    _print_metrics(test_m)

    oos_sharpe = test_m["sharpe_ratio"]
    oos_pnl = test_m["total_return"]
    degradation = (
        (train_m["sharpe_ratio"] - oos_sharpe) / abs(train_m["sharpe_ratio"])
        if train_m["sharpe_ratio"] != 0 else float("nan")
    )

    print("\n--- SUMMARY ---")
    print(f"  OOS Sharpe        : {oos_sharpe:.4f}")
    print(f"  OOS Total PnL     : ${oos_pnl:.2f}")
    print(f"  Sharpe degradation: {degradation:+.1%}  (train → OOS)")
    if train_m["trade_count"] > 0 and test_m["trade_count"] > 0:
        hold_ratio = test_m["trade_count"] / train_m["trade_count"]
        print(f"  Trade-count ratio : {hold_ratio:.2f}  (OOS / train)")

    oos_win = test_m["win_rate"]
    verdict = (
        "PROMISING" if oos_sharpe > 0.3 and oos_win >= 0.65 and oos_pnl > 0
        else "WEAK / NEEDS WORK"
    )
    print(f"\n  Preliminary verdict: {verdict}")
    print("  Target: Sharpe>0.3, WinRate≥65%, positive PnL on OOS.")
    print("  (Run full gate validation before drawing conclusions.)\n")


if __name__ == "__main__":
    main()
