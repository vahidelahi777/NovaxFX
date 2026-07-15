"""Backtest the fixed multi-TF scanner on historical XAUUSD data.

Validates that the new EMA50-based confluence gate generates enough signals
with acceptable win rate before deploying to production.

Usage:
  .venv/bin/python scripts/run_multitf_scanner_backtest.py \\
      --data-dir data/market \\
      --start 2023-07-01 \\
      --end 2026-07-12

Go / No-Go thresholds:
  Confluence signals : >= 50
  Win rate (TP hits) : >= 45 %   (breakeven at RR=2 is 33%)
  Total PnL          : > 0 pips
  Max drawdown       : <= 30 %
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.data_sources import Bar
from novax.live.multi_tf_scanner import MultiTFScanner

_SYMBOL = "XAUUSD"
_PIP    = 0.1     # XAU/USD: 1 pip = $0.10

_MIN_SIGNALS  = 50
_MIN_WIN_RATE = 0.45
_MAX_DD_PCT   = 0.30

# Sliding window size for each scan (lookback in days)
_LB_H4  = 90
_LB_H1  = 45
_LB_M15 = 14


@dataclass
class Signal_Record:
    ts: datetime
    direction: str
    entry: float
    sl: float
    tp: float

    @property
    def risk_pips(self) -> float:
        return abs(self.entry - self.sl) / _PIP

    @property
    def reward_pips(self) -> float:
        return abs(self.tp - self.entry) / _PIP

    @property
    def rr(self) -> float:
        return self.reward_pips / self.risk_pips if self.risk_pips > 0 else 0.0


def _simulate(
    bars_h4: list[Bar],
    bars_h1: list[Bar],
    bars_m15: list[Bar],
    scanner: MultiTFScanner,
) -> list[tuple[Signal_Record, str, float]]:
    """Walk forward through 1H bars and scan at each step.

    Returns list of (signal, outcome, pnl_pips) where outcome is "TP"|"SL"|"OPEN".
    Only signals with valid SL and TP are included.
    We use subsequent 1H bars to determine TP/SL outcome.
    """
    results: list[tuple[Signal_Record, str, float]] = []
    n_h1 = len(bars_h1)

    for i in range(50, n_h1):  # skip first 50 bars for warmup
        now = bars_h1[i].ts

        # Slice lookback windows ending at current bar
        h4_cut = [b for b in bars_h4 if b.ts <= now][-(_LB_H4 * 6):]
        h1_cut = [b for b in bars_h1 if b.ts <= now][-(_LB_H1 * 24):]
        m15_cut = [b for b in bars_m15 if b.ts <= now][-(_LB_M15 * 96):]

        if len(h4_cut) < 2 or len(h1_cut) < 2 or len(m15_cut) < 2:
            continue

        result = scanner.scan(h4_cut, h1_cut, m15_cut)

        if not result.confluence:
            continue
        if result.sl is None or result.tp is None or result.entry_price is None:
            continue

        sig = Signal_Record(
            ts=now,
            direction=result.direction.value,
            entry=result.entry_price,
            sl=result.sl,
            tp=result.tp,
        )

        # Look ahead in 1H bars to find outcome (max 10 bars = 10 hours)
        outcome = "OPEN"
        pnl_pips = 0.0
        for fut in bars_h1[i + 1: i + 11]:
            if sig.direction == "LONG":
                if fut.low <= sig.sl:
                    outcome = "SL"
                    pnl_pips = -sig.risk_pips
                    break
                if fut.high >= sig.tp:
                    outcome = "TP"
                    pnl_pips = sig.reward_pips
                    break
            else:  # SHORT
                if fut.high >= sig.sl:
                    outcome = "SL"
                    pnl_pips = -sig.risk_pips
                    break
                if fut.low <= sig.tp:
                    outcome = "TP"
                    pnl_pips = sig.reward_pips
                    break

        results.append((sig, outcome, pnl_pips))

    return results


def _report(
    symbol: str,
    start: str,
    end: str,
    results: list[tuple[Signal_Record, str, float]],
) -> None:
    n = len(results)
    closed = [(s, o, p) for s, o, p in results if o in ("TP", "SL")]
    open_  = [(s, o, p) for s, o, p in results if o == "OPEN"]
    tp_    = [(s, o, p) for s, o, p in closed if o == "TP"]
    sl_    = [(s, o, p) for s, o, p in closed if o == "SL"]

    print(f"\n{'='*60}")
    print(f"  {symbol}  Multi-TF Scanner (EMA50 confluence)  {start} → {end}")
    print(f"{'='*60}")
    print(f"  Total confluence signals : {n}")
    print(f"  Closed (TP or SL hit)   : {len(closed)}")
    print(f"  Still open (10H window) : {len(open_)}")

    if not closed:
        print("  No closed signals — cannot evaluate performance.")
        return

    pnls    = [p for _, _, p in closed]
    wr      = len(tp_) / len(closed)
    total   = sum(pnls)
    mean    = total / len(pnls)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum  += p
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    max_dd_pct = max_dd / (abs(peak) or 1.0) if max_dd > 0 else 0.0

    lng = sum(1 for s, _, _ in closed if s.direction == "LONG")
    sht = sum(1 for s, _, _ in closed if s.direction == "SHORT")

    print(f"\n  Win rate     : {wr:>7.1%}  (TP={len(tp_)}  SL={len(sl_)})")
    print(f"  Total PnL    : {total:>+8.1f} pips")
    print(f"  Avg trade    : {mean:>+8.1f} pips")
    print(f"  Max drawdown : {max_dd_pct:>7.1%}")
    print(f"  Direction    : LONG={lng}  SHORT={sht}")

    # Sample table (last 20)
    show = closed[-20:]
    if len(closed) > 20:
        print(f"\n  (showing last 20 of {len(closed)} closed trades)")
    print(f"\n  {'Date':<12} {'Dir':<6} {'Entry':>8} {'SL':>8} {'TP':>8} "
          f"{'RR':>4} {'PnL':>7} Out")
    print(f"  {'-'*62}")
    for s, o, p in show:
        mark = "✓" if o == "TP" else "✗"
        print(
            f"  {s.ts.strftime('%Y-%m-%d'):<12} {s.direction:<6} "
            f"{s.entry:>8.2f} {s.sl:>8.2f} {s.tp:>8.2f} "
            f"{s.rr:>4.1f} {p:>+7.1f} {o:<4} {mark}"
        )

    # Verdict
    fails = []
    if n < _MIN_SIGNALS:
        fails.append(f"signals {n} < {_MIN_SIGNALS}")
    if wr < _MIN_WIN_RATE:
        fails.append(f"win_rate {wr:.1%} < {_MIN_WIN_RATE:.0%}")
    if total <= 0:
        fails.append(f"total_pnl {total:.1f} pips ≤ 0")
    if max_dd_pct > _MAX_DD_PCT:
        fails.append(f"max_drawdown {max_dd_pct:.1%} > {_MAX_DD_PCT:.0%}")

    print(f"\n{'='*60}")
    if not fails:
        print("  VERDICT:  ✅  GO — deploy to production")
        print(f"    {n} signals  {wr:.1%} win  {total:+.0f} pips  dd={max_dd_pct:.1%}")
    else:
        print("  VERDICT:  ❌  NO-GO")
        for f in fails:
            print(f"    • {f}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-TF scanner backtest")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--symbol",   default=_SYMBOL)
    parser.add_argument("--start",    default="2023-07-01")
    parser.add_argument("--end",      default="2026-07-12")
    args = parser.parse_args()

    root   = Path(args.data_dir)
    symbol = args.symbol.upper()
    start  = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end    = datetime.strptime(args.end,   "%Y-%m-%d").replace(tzinfo=UTC)

    print(f"\nLoading {symbol} bars {args.start} → {args.end} …")

    bars_h4  = load_bars(root, symbol, "4h",  start, end)
    bars_h1  = load_bars(root, symbol, "1h",  start, end)
    bars_m15 = load_bars(root, symbol, "15m", start, end)

    if not bars_h4 or not bars_h1:
        print("ERROR: missing bars — run ingestion first.")
        return

    print(f"  4H : {len(bars_h4)} bars  [{bars_h4[0].ts.date()} → {bars_h4[-1].ts.date()}]")
    print(f"  1H : {len(bars_h1)} bars  [{bars_h1[0].ts.date()} → {bars_h1[-1].ts.date()}]")
    print(f"  15M: {len(bars_m15)} bars  [{bars_m15[0].ts.date() if bars_m15 else 'n/a'} → "
          f"{bars_m15[-1].ts.date() if bars_m15 else 'n/a'}]")

    scanner = MultiTFScanner(symbol)

    print("\nRunning backtest (this may take a minute) …")
    results = _simulate(bars_h4, bars_h1, bars_m15, scanner)

    _report(symbol, args.start, args.end, results)


if __name__ == "__main__":
    main()
