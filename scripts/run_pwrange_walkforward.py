"""Walk-forward go/no-go for PrevWeekRange strategy on XAU/USD H1.

Strategy: Previous-Week High/Low levels + EMA/TSI confirmation.
  Pullback to PWL → LONG   |   Pullback to PWH → SHORT
  Break above PWH → LONG   |   Break below PWL → SHORT
  Session filter: London (07-12 UTC) + NY (13-20 UTC)

Usage:
  .venv/bin/python scripts/run_pwrange_walkforward.py \\
      --symbol XAUUSD \\
      --start  2023-07-01 \\
      --end    2025-12-31 \\
      --data-dir data/market

Go / No-Go thresholds
---------------------
  OOS trades    >= 30
  Win rate      >= 52 %
  Total PnL     >  0 pips
  Max drawdown  <= 25 %
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.engine import BarView, Position, Signal
from novax.strategies.prev_week_range import PrevWeekRange
from novax.walkforward import SimpleWalkForward

_SYMBOL_DEFAULT = "XAUUSD"
_XAUUSD_PIP = 0.1

_MIN_OOS_TRADES  = 30
_MIN_WIN_RATE    = 0.52
_MAX_DRAWDOWN    = 0.25


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    direction: str
    entry_price: float
    exit_price: float
    exit_kind: str      # "TP" | "SL" | "EOD"
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

def _metrics(trades: list[Trade]) -> dict[str, float]:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "total_pips": 0.0,
                "avg_pips": 0.0, "max_dd_pct": 0.0, "sharpe": 0.0}
    pnls = [t.pnl_pips for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    max_dd_pct = max_dd / (abs(peak) or 1.0) if max_dd > 0 else 0.0
    mean = sum(pnls) / len(pnls)
    std = (sum((p - mean) ** 2 for p in pnls) / len(pnls)) ** 0.5
    sharpe = mean / std if std > 0 else 0.0
    return {
        "n": float(len(trades)),
        "win_rate": wins / len(trades),
        "total_pips": sum(pnls),
        "avg_pips": mean,
        "max_dd_pct": max_dd_pct,
        "sharpe": sharpe,
    }


def _print_metrics(label: str, trades: list[Trade], m: dict[str, float]) -> None:
    n = int(m["n"])
    print(f"\n--- {label} ---")
    print(f"  Trades        : {n}")
    if n == 0:
        print("  (no trades)")
        return
    n_tp  = sum(1 for t in trades if t.exit_kind == "TP")
    n_sl  = sum(1 for t in trades if t.exit_kind == "SL")
    n_eod = sum(1 for t in trades if t.exit_kind == "EOD")
    n_lng = sum(1 for t in trades if t.direction == "LONG")
    n_sht = sum(1 for t in trades if t.direction == "SHORT")
    print(f"  Win rate      : {m['win_rate']:>8.1%}")
    print(f"  Total PnL     : {m['total_pips']:>8.1f} pips")
    print(f"  Avg trade     : {m['avg_pips']:>8.1f} pips")
    print(f"  Max drawdown  : {m['max_dd_pct']:>8.1%}")
    print(f"  Sharpe        : {m['sharpe']:>8.4f}")
    print(f"  Exit breakdown: TP={n_tp}  SL={n_sl}  EOD={n_eod}")
    print(f"  Direction     : LONG={n_lng}  SHORT={n_sht}")


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

from novax.data_sources import Bar as _Bar  # noqa: E402


def _simulate(bars_h1: list[_Bar], params: dict[str, object]) -> list[Trade]:
    strat = PrevWeekRange(**params)  # type: ignore[arg-type,call-arg]
    trades: list[Trade] = []

    pos_direction = "FLAT"
    entry_price = 0.0
    entry_ts: datetime | None = None
    trade_sl: float | None = None
    trade_tp: float | None = None

    for bar in bars_h1:
        view = BarView(bars=(bar,))
        pos = Position(direction=pos_direction)
        signal = strat.on_bar(view, pos)

        # Detect exits: strategy returns FLAT when SL/TP is hit
        if pos_direction != "FLAT" and signal == Signal.FLAT:
            if pos_direction == "LONG":
                if trade_sl is not None and bar.low <= trade_sl:
                    xprice, xkind = trade_sl, "SL"
                elif trade_tp is not None and bar.high >= trade_tp:
                    xprice, xkind = trade_tp, "TP"
                else:
                    xprice, xkind = bar.close, "EOD"
            else:  # SHORT
                if trade_sl is not None and bar.high >= trade_sl:
                    xprice, xkind = trade_sl, "SL"
                elif trade_tp is not None and bar.low <= trade_tp:
                    xprice, xkind = trade_tp, "TP"
                else:
                    xprice, xkind = bar.close, "EOD"
            assert entry_ts is not None
            trades.append(Trade(
                direction=pos_direction,
                entry_price=entry_price,
                exit_price=xprice,
                exit_kind=xkind,
                entry_ts=entry_ts,
                exit_ts=bar.ts,
            ))
            pos_direction = "FLAT"
            trade_sl = trade_tp = None

        # New entry
        if pos_direction == "FLAT" and signal in (Signal.LONG, Signal.SHORT):
            pos_direction = signal.value
            entry_price = bar.close
            entry_ts = bar.ts
            trade_sl = strat._sl  # noqa: SLF001
            trade_tp = strat._tp  # noqa: SLF001

    return trades


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PrevWeekRange walk-forward on XAUUSD H1"
    )
    parser.add_argument("--symbol",    default=_SYMBOL_DEFAULT)
    parser.add_argument("--start",     required=True)
    parser.add_argument("--end",       required=True)
    parser.add_argument("--data-dir",  required=True)
    parser.add_argument("--train-pct", type=float, default=0.70)
    parser.add_argument("--touch-buf",   type=float, default=3.0,
                        help="Pips within PWH/PWL that count as a touch (default 3)")
    parser.add_argument("--break-buf",   type=float, default=2.0,
                        help="Pips beyond PWH/PWL that count as a breakout (default 2)")
    parser.add_argument("--sl-atr-mult", type=float, default=1.0,
                        help="SL = sl_atr_mult × ATR(14) beyond the level (default 1.0)")
    parser.add_argument("--max-risk",    type=float, default=150.0,
                        help="Max SL distance in pips (default 150)")
    parser.add_argument("--rr",        type=float, default=2.0,
                        help="Risk:Reward ratio (default 2.0)")
    parser.add_argument("--no-london", action="store_true")
    parser.add_argument("--no-ny",     action="store_true")
    args = parser.parse_args()

    root   = Path(args.data_dir)
    symbol = args.symbol.upper()
    start  = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end    = datetime.strptime(args.end,   "%Y-%m-%d").replace(tzinfo=UTC)

    print("=" * 60)
    print(f"  {symbol}  PrevWeekRange Walk-Forward  {args.start} → {args.end}")
    print(f"  touch={args.touch_buf}pip  break={args.break_buf}pip  "
          f"sl={args.sl_atr_mult}×ATR  RR={args.rr}")
    sessions = []
    if not args.no_london:
        sessions.append("London")
    if not args.no_ny:
        sessions.append("NY")
    print(f"  Sessions: {' + '.join(sessions) or 'ALL'}")
    print("=" * 60)

    bars_h1 = load_bars(root, symbol, "1h", start, end)
    if not bars_h1:
        print("\nERROR: No 1H bars found. Ingest first:", file=sys.stderr)
        print(f"  .venv/bin/python scripts/ingest_twelvedata.py "
              f"--symbol {symbol} --interval 1h "
              f"--start {args.start} --end {args.end} --output-dir {args.data_dir}",
              file=sys.stderr)
        sys.exit(1)

    print(f"\n1H bars : {len(bars_h1)}  [{bars_h1[0].ts.date()} → {bars_h1[-1].ts.date()}]")

    # ── Split ────────────────────────────────────────────────────────────────
    wf = SimpleWalkForward(train_ratio=args.train_pct)
    train_bars, test_bars = wf.split(bars_h1)
    split_ts = test_bars[0].ts if test_bars else end
    print(f"\nSplit ({args.train_pct:.0%} train / {1-args.train_pct:.0%} test)  "
          f"| split date: {split_ts.date()}")
    print(f"  Train: {len(train_bars)} bars   Test: {len(test_bars)} bars")

    params = dict(
        touch_buf_pips=args.touch_buf,
        break_buf_pips=args.break_buf,
        sl_atr_mult=args.sl_atr_mult,
        max_risk_pips=args.max_risk,
        risk_reward=args.rr,
        london=not args.no_london,
        ny=not args.no_ny,
    )

    # ── IS simulation (train) ────────────────────────────────────────────────
    print("\nSimulating train window …")
    is_trades = _simulate(train_bars, params)
    is_m = _metrics(is_trades)
    _print_metrics(
        f"IN-SAMPLE (train: {train_bars[0].ts.date()} → {train_bars[-1].ts.date()})",
        is_trades, is_m,
    )

    # ── OOS simulation (test) ────────────────────────────────────────────────
    print("\nSimulating test window …")
    oos_trades = _simulate(test_bars, params)
    m = _metrics(oos_trades)
    _print_metrics(f"OOS TEST ({split_ts.date()} → {bars_h1[-1].ts.date()})", oos_trades, m)

    # ── Verdict ──────────────────────────────────────────────────────────────
    n = int(m["n"])
    fails = []
    if n < _MIN_OOS_TRADES:
        fails.append(f"trades {n} < {_MIN_OOS_TRADES} (insufficient sample)")
    if m["win_rate"] < _MIN_WIN_RATE:
        fails.append(f"win_rate {m['win_rate']:.1%} < {_MIN_WIN_RATE:.0%}")
    if m["total_pips"] <= 0:
        fails.append(f"total_pnl {m['total_pips']:.1f} pips ≤ 0 (negative expectancy)")
    if m["max_dd_pct"] > _MAX_DRAWDOWN:
        fails.append(f"max_drawdown {m['max_dd_pct']:.1%} > {_MAX_DRAWDOWN:.0%}")

    print("\n" + "=" * 60)
    if not fails:
        print("  VERDICT:  ✅  GO")
        print(f"    All thresholds passed ({n} trades, "
              f"{m['win_rate']:.1%} win, {m['total_pips']:.0f} pips)")
    else:
        print("  VERDICT:  ❌  NO_GO")
        for f in fails:
            print(f"    • {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
