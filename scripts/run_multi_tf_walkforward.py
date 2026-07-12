"""Multi-TF walk-forward go/no-go for XAU/USD.

Strategy: 4H WeeklyBOSRetest + 1H GoldPullback + 15M EMACross.

Data required (XAU/USD Parquet in data/market):
  4h  — fetch with TwelveData or Dukascopy resample
  1h  — python scripts/ingest_twelvedata.py \\
             --symbol XAUUSD --interval 1h \\
             --start 2023-01-01 --end 2026-07-12 \\
             --output-dir data/market
  15m — python scripts/ingest_twelvedata.py \\
             --symbol XAUUSD --interval 15min \\
             --start 2023-01-01 --end 2026-07-12 \\
             --output-dir data/market

Walk-forward design
-------------------
  - Single 70/30 temporal split on 4H bar count (no cross-validation)
  - Train segment: context only — warms up indicators; no trade counting
  - Test segment: full trade simulation; metrics reported here only
  - Signal: scanner fires at each 4H bar close in the test window
  - Entry: 4H + 1H confluence → enter at 4H bar close price
  - Exit: SL hit, TP hit, or signal reversal — checked on 15M bars within each 4H window
  - Max hold: --max-hold-bars 15M bars (default 96 = 24 h) to cap open exposure

Go / No-Go thresholds
---------------------
  OOS trades        >= 20
  Win rate          >= 52 %
  Total PnL (pips)  >  0
  Max drawdown      <= 20 %

Usage:
  .venv/bin/python scripts/run_multi_tf_walkforward.py \\
      --symbol XAUUSD \\
      --start 2023-07-01 \\
      --end   2025-12-31 \\
      --data-dir data/market
"""

from __future__ import annotations

import argparse
import bisect
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.dataquality import run_data_quality
from novax.engine import Signal
from novax.live import MultiTFScanner
from novax.walkforward import SimpleWalkForward

_SYMBOL_DEFAULT = "XAUUSD"
_XAUUSD_PIP = 0.1

# Go/No-Go thresholds
_MIN_OOS_TRADES       = 20
_MIN_WIN_RATE         = 0.52
_MAX_DRAWDOWN_PCT     = 0.20
_MIN_SHARPE           = 0.0


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    direction: str       # "LONG" | "SHORT"
    entry_price: float
    exit_price: float
    exit_kind: str       # "TP" | "SL" | "SIGNAL" | "EXPIRED"
    entry_ts: datetime
    exit_ts: datetime

    @property
    def pnl(self) -> float:
        if self.direction == "LONG":
            return self.exit_price - self.entry_price
        return self.entry_price - self.exit_price

    @property
    def pnl_pips(self) -> float:
        return self.pnl / _XAUUSD_PIP

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _trade_metrics(trades: list[Trade]) -> dict[str, float]:
    if not trades:
        return {
            "trade_count": 0, "win_rate": 0.0, "total_pnl_pips": 0.0,
            "avg_pnl_pips": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
        }
    pnls = [t.pnl_pips for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    equity: list[float] = []
    cum = 0.0
    for p in pnls:
        cum += p
        equity.append(cum)
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    max_dd_pct = max_dd / (abs(peak) or 1.0) if max_dd > 0 else 0.0
    mean = sum(pnls) / len(pnls)
    std = (sum((p - mean) ** 2 for p in pnls) / len(pnls)) ** 0.5
    sharpe = mean / std if std > 0 else 0.0
    return {
        "trade_count": float(len(trades)),
        "win_rate": wins / len(trades),
        "total_pnl_pips": sum(pnls),
        "avg_pnl_pips": mean,
        "max_drawdown_pct": max_dd_pct,
        "sharpe": sharpe,
    }


def _print_metrics(label: str, m: dict[str, float]) -> None:
    n = int(m["trade_count"])
    print(f"\n--- {label} ---")
    print(f"  Trades          : {n}")
    if n == 0:
        print("  (no trades — check data / lookback settings)")
        return
    print(f"  Win rate        : {m['win_rate']:>8.1%}")
    print(f"  Total PnL       : {m['total_pnl_pips']:>8.1f} pips")
    print(f"  Avg trade PnL   : {m['avg_pnl_pips']:>8.1f} pips")
    print(f"  Max drawdown    : {m['max_drawdown_pct']:>8.1%}")
    print(f"  Sharpe (trade)  : {m['sharpe']:>8.4f}")


# ---------------------------------------------------------------------------
# Walk-forward simulation
# ---------------------------------------------------------------------------

def _simulate_trades(
    *,
    scanner: MultiTFScanner,
    all_h4: list,
    all_h1: list,
    all_m15: list,
    test_start_idx_h4: int,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    max_hold_bars_m15: int,
) -> list[Trade]:
    """Step through 4H bars in the test window; simulate entries and track SL/TP on 15M bars."""
    # Pre-build timestamp lists for bisect
    h1_ts = [b.ts for b in all_h1]
    m15_ts = [b.ts for b in all_m15]

    trades: list[Trade] = []
    in_trade = False
    entry_price: float = 0.0
    entry_sl: float | None = None
    entry_tp: float | None = None
    entry_dir: str = ""
    entry_ts: datetime | None = None
    bars_held: int = 0

    prev_h4_ts: datetime | None = (
        all_h4[test_start_idx_h4 - 1].ts if test_start_idx_h4 > 0 else None
    )

    for i_abs in range(test_start_idx_h4, len(all_h4)):
        h4_bar = all_h4[i_abs]

        # Lookback-bounded windows for each TF, ending at h4_bar.ts
        h4_window = all_h4[max(0, i_abs + 1 - lookback_h4) : i_abs + 1]

        i_h1 = bisect.bisect_right(h1_ts, h4_bar.ts)
        h1_window = all_h1[max(0, i_h1 - lookback_h1) : i_h1]

        i_m15 = bisect.bisect_right(m15_ts, h4_bar.ts)
        m15_window = all_m15[max(0, i_m15 - lookback_m15) : i_m15]

        # Collect 15M bars that closed within this 4H window
        m15_in_window: list = []
        if prev_h4_ts is not None:
            lo = bisect.bisect_right(m15_ts, prev_h4_ts)
            hi = bisect.bisect_right(m15_ts, h4_bar.ts)
            m15_in_window = all_m15[lo:hi]

        # --- SL/TP check on 15M bars before running the scanner ---
        if in_trade:
            for m15_bar in m15_in_window:
                if entry_dir == "LONG":
                    if entry_sl is not None and m15_bar.low <= entry_sl:
                        trades.append(Trade(
                            direction=entry_dir,
                            entry_price=entry_price,
                            exit_price=entry_sl,
                            exit_kind="SL",
                            entry_ts=entry_ts,  # type: ignore[arg-type]
                            exit_ts=m15_bar.ts,
                        ))
                        in_trade = False
                        break
                    if entry_tp is not None and m15_bar.high >= entry_tp:
                        trades.append(Trade(
                            direction=entry_dir,
                            entry_price=entry_price,
                            exit_price=entry_tp,
                            exit_kind="TP",
                            entry_ts=entry_ts,  # type: ignore[arg-type]
                            exit_ts=m15_bar.ts,
                        ))
                        in_trade = False
                        break
                else:  # SHORT
                    if entry_sl is not None and m15_bar.high >= entry_sl:
                        trades.append(Trade(
                            direction=entry_dir,
                            entry_price=entry_price,
                            exit_price=entry_sl,
                            exit_kind="SL",
                            entry_ts=entry_ts,  # type: ignore[arg-type]
                            exit_ts=m15_bar.ts,
                        ))
                        in_trade = False
                        break
                    if entry_tp is not None and m15_bar.low <= entry_tp:
                        trades.append(Trade(
                            direction=entry_dir,
                            entry_price=entry_price,
                            exit_price=entry_tp,
                            exit_kind="TP",
                            entry_ts=entry_ts,  # type: ignore[arg-type]
                            exit_ts=m15_bar.ts,
                        ))
                        in_trade = False
                        break
                bars_held += 1

            # Max-hold expiry
            if in_trade and bars_held >= max_hold_bars_m15:
                trades.append(Trade(
                    direction=entry_dir,
                    entry_price=entry_price,
                    exit_price=h4_bar.close,
                    exit_kind="EXPIRED",
                    entry_ts=entry_ts,  # type: ignore[arg-type]
                    exit_ts=h4_bar.ts,
                ))
                in_trade = False

        # --- Scanner at 4H bar close ---
        if len(h4_window) < 2 or len(h1_window) < 2 or len(m15_window) < 2:
            prev_h4_ts = h4_bar.ts
            continue

        result = scanner.scan(h4_window, h1_window, m15_window)

        # Signal reversal exit
        if in_trade:
            reversal = (
                (entry_dir == "LONG"  and result.h4.signal == Signal.SHORT) or
                (entry_dir == "SHORT" and result.h4.signal == Signal.LONG)
            )
            if reversal:
                trades.append(Trade(
                    direction=entry_dir,
                    entry_price=entry_price,
                    exit_price=h4_bar.close,
                    exit_kind="SIGNAL",
                    entry_ts=entry_ts,  # type: ignore[arg-type]
                    exit_ts=h4_bar.ts,
                ))
                in_trade = False

        # New entry on fresh confluence (one trade at a time)
        if not in_trade and result.confluence and result.sl is not None and result.tp is not None:
            in_trade = True
            entry_price = h4_bar.close
            entry_sl = result.sl
            entry_tp = result.tp
            entry_dir = result.direction.value
            entry_ts = h4_bar.ts
            bars_held = 0

        prev_h4_ts = h4_bar.ts

    return trades


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-TF walk-forward go/no-go: 4H + 1H + 15M XAU/USD."
    )
    parser.add_argument("--symbol", default=_SYMBOL_DEFAULT)
    parser.add_argument("--start", required=True, help="Data start date (YYYY-MM-DD)")
    parser.add_argument("--end",   required=True, help="Data end date (YYYY-MM-DD)")
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--lookback-4h", type=int, default=540,
                        help="Max 4H bars fed to scanner (default 540 = 90 days)")
    parser.add_argument("--lookback-1h", type=int, default=1080,
                        help="Max 1H bars fed to scanner (default 1080 = 45 days)")
    parser.add_argument("--lookback-15m", type=int, default=1344,
                        help="Max 15M bars fed to scanner (default 1344 = 14 days)")
    parser.add_argument("--max-hold-bars", type=int, default=96,
                        help="Max 15M bars a position can be held (default 96 = 24 h)")
    # Strategy params
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    start  = _parse_date(args.start)
    end    = _parse_date(args.end)
    root   = Path(args.data_dir)

    width = 64
    print(f"\n{'='*width}")
    print(f"  {symbol}  Multi-TF Walk-Forward  {args.start} → {args.end}")
    print(f"  EMA({args.ema_fast}/{args.ema_slow})  OB-buf={args.ob_buffer_pips}pip"
          f"  RR={args.risk_reward}  MaxRisk={args.max_risk_pips}pip")
    print(f"{'='*width}")

    # ── Load bars ─────────────────────────────────────────────────────────
    print("\nLoading bars …")
    bars_h4  = load_bars(root, symbol, "4h",   start, end)
    bars_h1  = load_bars(root, symbol, "1h",   start, end)
    bars_m15 = load_bars(root, symbol, "15min", start, end)

    missing: list[str] = []
    if not bars_h4:
        missing.append("4h")
    if not bars_h1:
        missing.append("1h")
    if not bars_m15:
        missing.append("15min")

    if missing:
        print(f"\nERROR: Missing data for timeframe(s): {missing}", file=sys.stderr)
        print("\nIngest the missing timeframes with TwelveData:", file=sys.stderr)
        for tf in missing:
            print(
                f"  .venv/bin/python scripts/ingest_twelvedata.py \\\n"
                f"      --symbol {symbol} --interval {tf} \\\n"
                f"      --start {args.start} --end {args.end} \\\n"
                f"      --output-dir {args.data_dir}",
                file=sys.stderr,
            )
        print(
            "\nOr from 1-minute Dukascopy data:\n"
            "  from novax.data.cleaning.normalize import resample_bars\n"
            "  bars_15m = resample_bars(bars_1m, interval_minutes=15)\n"
            "  bars_1h  = resample_bars(bars_1m, interval_minutes=60)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  4H  bars: {len(bars_h4):>7,}  [{bars_h4[0].ts.date()} → {bars_h4[-1].ts.date()}]")
    print(f"  1H  bars: {len(bars_h1):>7,}  [{bars_h1[0].ts.date()} → {bars_h1[-1].ts.date()}]")
    print(f"  15M bars: {len(bars_m15):>7,}  [{bars_m15[0].ts.date()} → {bars_m15[-1].ts.date()}]")

    # ── Data quality (4H is the primary check) ────────────────────────────
    dq = run_data_quality(symbol, "4h", bars_h4, min_coverage=0.5)
    status = "PASSED" if dq.passed else "FAILED"
    print(f"\nData quality (4H): {status}  ({len(dq.checks)} checks)")
    for c in dq.checks:
        icon = "✓" if c.passed else "✗"
        sev = f" [{c.severity}]" if not c.passed else ""
        print(f"  {icon} {c.name:<35} {c.detail}{sev}")
    if not dq.passed:
        print("\nWARN: Data quality failed — continuing anyway.")

    # ── Walk-forward split on 4H bar count ───────────────────────────────
    wf = SimpleWalkForward(train_ratio=args.train_ratio)
    train_h4, test_h4 = wf.split(bars_h4)
    split_ts = test_h4[0].ts
    test_start_idx_h4 = len(train_h4)

    print(
        f"\nSplit ({args.train_ratio:.0%} train / {1 - args.train_ratio:.0%} test)"
        f"  |  split date: {split_ts.date()}"
    )
    print(f"  4H  train: {len(train_h4):>5,} bars   test: {len(test_h4):>5,} bars")
    print(f"  1H  in test window : {sum(1 for b in bars_h1  if b.ts >= split_ts):>5,} bars")
    print(f"  15M in test window : {sum(1 for b in bars_m15 if b.ts >= split_ts):>5,} bars")

    # ── Run simulation ────────────────────────────────────────────────────
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

    print(f"\nSimulating {len(test_h4)} test 4H bars …  (this may take 30–90 s)")
    trades = _simulate_trades(
        scanner=scanner,
        all_h4=bars_h4,
        all_h1=bars_h1,
        all_m15=bars_m15,
        test_start_idx_h4=test_start_idx_h4,
        lookback_h4=args.lookback_4h,
        lookback_h1=args.lookback_1h,
        lookback_m15=args.lookback_15m,
        max_hold_bars_m15=args.max_hold_bars,
    )
    print(f"Simulation complete — {len(trades)} trades generated.")

    # ── Breakdown by exit kind ────────────────────────────────────────────
    if trades:
        from collections import Counter
        kinds = Counter(t.exit_kind for t in trades)
        print("\n  Exit breakdown: " + "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        long_trades  = [t for t in trades if t.direction == "LONG"]
        short_trades = [t for t in trades if t.direction == "SHORT"]
        print(f"  Direction split: LONG={len(long_trades)}  SHORT={len(short_trades)}")

    # ── Metrics ───────────────────────────────────────────────────────────
    m = _trade_metrics(trades)
    _print_metrics(f"OOS TEST ({split_ts.date()} → {args.end})", m)

    # ── Go / No-Go decision ───────────────────────────────────────────────
    n = int(m["trade_count"])
    failed: list[str] = []
    if n < _MIN_OOS_TRADES:
        failed.append(f"trades {n} < {_MIN_OOS_TRADES} (insufficient sample)")
    if m["win_rate"] < _MIN_WIN_RATE:
        failed.append(f"win_rate {m['win_rate']:.1%} < {_MIN_WIN_RATE:.0%}")
    if m["total_pnl_pips"] <= 0:
        failed.append(f"total_pnl {m['total_pnl_pips']:.1f} pips ≤ 0 (negative expectancy)")
    if m["max_drawdown_pct"] > _MAX_DRAWDOWN_PCT:
        failed.append(f"max_drawdown {m['max_drawdown_pct']:.1%} > {_MAX_DRAWDOWN_PCT:.0%}")

    print(f"\n{'='*width}")
    if not failed:
        print("  VERDICT:  ✅  GO")
        thresholds = (
            f"≥{_MIN_OOS_TRADES} trades, ≥{_MIN_WIN_RATE:.0%} win,"
            f" positive PnL, DD ≤ {_MAX_DRAWDOWN_PCT:.0%}"
        )
        print(f"  All criteria passed: {thresholds}")
    else:
        print("  VERDICT:  ❌  NO_GO")
        for reason in failed:
            print(f"    • {reason}")
    print(f"{'='*width}\n")


if __name__ == "__main__":
    main()
