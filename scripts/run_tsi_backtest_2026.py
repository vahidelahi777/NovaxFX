"""TSIMomentum backtest on XAUUSD — 2026 data, both 1H and 15M.

Runs the four-signal TSIMomentum strategy on H1 and 15M bars for 2026,
prints per-trade results and summary metrics for each timeframe.

Usage:
  .venv/bin/python scripts/run_tsi_backtest_2026.py --data-dir data/market
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novax.data.loader.bar_loader import load_bars
from novax.data_sources import Bar
from novax.engine import BarView, Position, Signal
from novax.strategies.tsi_momentum import TSIMomentum

_SYMBOL = "XAUUSD"
_PIP    = 0.1   # XAU/USD — 1 pip = $0.10


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    direction: str
    entry_price: float
    exit_price: float
    exit_kind: str      # "TP" | "SL" | "REV" (reversal)
    entry_ts: datetime
    exit_ts: datetime
    signal_type: str    # "crossover" | "ob_os" | "divergence" | "unknown"

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) if self.direction == "LONG" \
               else (self.entry_price - self.exit_price)

    @property
    def pnl_pips(self) -> float:
        return self.pnl / _PIP

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _simulate(bars: list[Bar], params: dict) -> list[Trade]:  # type: ignore[type-arg]
    strat = TSIMomentum(**params)  # type: ignore[arg-type,call-arg]
    trades: list[Trade] = []

    pos_dir   = "FLAT"
    entry_px  = 0.0
    entry_ts: datetime | None  = None
    trade_sl: float | None = None
    trade_tp: float | None = None

    for bar in bars:
        view   = BarView(bars=(bar,))
        pos    = Position(direction=pos_dir)
        signal = strat.on_bar(view, pos)

        # Detect exit
        if pos_dir != "FLAT" and signal == Signal.FLAT:
            if pos_dir == "LONG":
                if trade_sl is not None and bar.low <= trade_sl:
                    xpx, xkind = trade_sl, "SL"
                elif trade_tp is not None and bar.high >= trade_tp:
                    xpx, xkind = trade_tp, "TP"
                else:
                    xpx, xkind = bar.close, "REV"
            else:
                if trade_sl is not None and bar.high >= trade_sl:
                    xpx, xkind = trade_sl, "SL"
                elif trade_tp is not None and bar.low <= trade_tp:
                    xpx, xkind = trade_tp, "TP"
                else:
                    xpx, xkind = bar.close, "REV"
            assert entry_ts is not None
            trades.append(Trade(
                direction=pos_dir,
                entry_price=entry_px,
                exit_price=xpx,
                exit_kind=xkind,
                entry_ts=entry_ts,
                exit_ts=bar.ts,
                signal_type="unknown",
            ))
            pos_dir = "FLAT"
            trade_sl = trade_tp = None

        # Detect entry
        if pos_dir == "FLAT" and signal in (Signal.LONG, Signal.SHORT):
            pos_dir  = signal.value
            entry_px = bar.close
            entry_ts = bar.ts
            trade_sl = strat._sl  # noqa: SLF001
            trade_tp = strat._tp  # noqa: SLF001

    return trades


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _report(tf: str, trades: list[Trade]) -> dict[str, float]:
    n = len(trades)
    print(f"\n{'='*56}")
    print(f"  {_SYMBOL}  TSIMomentum  [{tf}]  2026")
    print(f"{'='*56}")
    print(f"  Trades : {n}")
    if n == 0:
        print("  (no trades — check data and session hours)")
        return {}

    pnls = [t.pnl_pips for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    n_tp  = sum(1 for t in trades if t.exit_kind == "TP")
    n_sl  = sum(1 for t in trades if t.exit_kind == "SL")
    n_rev = sum(1 for t in trades if t.exit_kind == "REV")
    n_lng = sum(1 for t in trades if t.direction == "LONG")
    n_sht = sum(1 for t in trades if t.direction == "SHORT")

    wr   = wins / n
    mean = sum(pnls) / n
    std  = (sum((p - mean)**2 for p in pnls) / n) ** 0.5

    print(f"  Win rate      : {wr:>7.1%}")
    print(f"  Total PnL     : {sum(pnls):>8.1f} pips")
    print(f"  Avg trade     : {mean:>8.1f} pips")
    print(f"  Best trade    : {max(pnls):>8.1f} pips")
    print(f"  Worst trade   : {min(pnls):>8.1f} pips")
    print(f"  Max drawdown  : {max_dd:>8.1f} pips")
    print(f"  Sharpe        : {mean/std if std > 0 else 0:>8.4f}")
    print(f"  Exit breakdown: TP={n_tp}  SL={n_sl}  REV={n_rev}")
    print(f"  Direction     : LONG={n_lng}  SHORT={n_sht}")

    # Per-trade table (last 20 only to keep output readable)
    show = trades[-20:] if len(trades) > 20 else trades
    if len(trades) > 20:
        print(f"\n  (showing last 20 of {n} trades)")
    print(f"\n  {'Date':<12} {'Dir':<6} {'Entry':>8} {'Exit':>8} "
          f"{'PnL':>7} {'Exit'}  ")
    print(f"  {'-'*55}")
    for t in show:
        mark = "✓" if t.is_win else "✗"
        print(
            f"  {t.entry_ts.strftime('%Y-%m-%d'):<12} "
            f"{t.direction:<6} "
            f"{t.entry_price:>8.2f} "
            f"{t.exit_price:>8.2f} "
            f"{t.pnl_pips:>+7.1f} "
            f"{t.exit_kind:<4} {mark}"
        )
    return {"n": n, "win_rate": wr, "total_pips": sum(pnls), "max_dd_pips": max_dd}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="TSIMomentum backtest 2026")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--start",    default="2026-01-01")
    parser.add_argument("--end",      default="2026-07-12")
    parser.add_argument("--sl-mult",  type=float, default=1.5,
                        help="SL = ATR × sl_mult (default 1.5)")
    parser.add_argument("--tp-mult",  type=float, default=3.0,
                        help="TP = ATR × tp_mult (default 3.0)")
    parser.add_argument("--ob-level", type=float, default=25.0,
                        help="Overbought/Oversold threshold (default 25)")
    parser.add_argument("--threshold", type=float, default=5.0,
                        help="Min |TSI| for plain crossover (default 5)")
    parser.add_argument("--no-divergence", action="store_true")
    parser.add_argument("--no-london",     action="store_true")
    parser.add_argument("--no-ny",         action="store_true")
    args = parser.parse_args()

    root  = Path(args.data_dir)
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
    end   = datetime.strptime(args.end,   "%Y-%m-%d").replace(tzinfo=UTC)

    params = dict(
        sl_atr_mult=args.sl_mult,
        tp_atr_mult=args.tp_mult,
        ob_level=args.ob_level,
        tsi_threshold=args.threshold,
        use_divergence=not args.no_divergence,
        london=not args.no_london,
        ny=not args.no_ny,
    )

    print(f"\nTSIMomentum Backtest — {_SYMBOL} — {args.start} → {args.end}")
    print(f"SL={args.sl_mult}×ATR  TP={args.tp_mult}×ATR  "
          f"OB/OS±{args.ob_level}  threshold={args.threshold}")
    print(f"Divergence={'ON' if not args.no_divergence else 'OFF'}  "
          f"London={'ON' if not args.no_london else 'OFF'}  "
          f"NY={'ON' if not args.no_ny else 'OFF'}")

    results: dict[str, dict] = {}

    for tf in ("1h", "15m"):
        bars = load_bars(root, _SYMBOL, tf, start, end)
        if not bars:
            print(f"\n  [{tf}] No data. Run:")
            interval = "1h" if tf == "1h" else "15min"
            print(f"    .venv/bin/python scripts/ingest_twelvedata.py "
                  f"--symbol {_SYMBOL} --interval {interval} "
                  f"--start {args.start} --end {args.end} "
                  f"--output-dir {args.data_dir}")
            continue
        print(f"\n[{tf}] {len(bars)} bars loaded  "
              f"[{bars[0].ts.date()} → {bars[-1].ts.date()}]")
        trades = _simulate(bars, params)
        results[tf] = _report(tf, trades)

    # Comparison summary
    if len(results) == 2:
        print(f"\n{'='*56}")
        print("  COMPARISON  1H vs 15M")
        print(f"{'='*56}")
        for tf, m in results.items():
            print(f"  [{tf}]  trades={int(m['n']):3d}  "
                  f"win={m['win_rate']:.1%}  "
                  f"pnl={m['total_pips']:+.0f}pip  "
                  f"dd={m['max_dd_pips']:.0f}pip")


if __name__ == "__main__":
    main()
