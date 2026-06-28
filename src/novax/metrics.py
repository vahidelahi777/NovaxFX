"""Basic performance metrics — Phase 1 Batch 2.

Operates on BacktestResult. No external dependencies. All formulas are
explicit and auditable in a single reading.

Drawdown note: max_drawdown_abs is in the same currency units as the PnL
(e.g. USD). max_drawdown_pct is a dimensionless ratio in [0, 1] computed
peak-to-trough on the per-trade equity curve, mirroring the formula used
in gate.py. Always use max_drawdown_pct when comparing against a fractional
threshold (e.g. SETTINGS.max_drawdown_pct = 0.20).
"""

from __future__ import annotations

import math

from .engine import BacktestResult

__all__ = ["compute_basic_metrics"]

_REQUIRED_KEYS = frozenset(
    {
        "total_return",
        "max_drawdown_abs",
        "max_drawdown_pct",
        "sharpe_ratio",
        "trade_count",
        "win_rate",
        "avg_trade_pnl",
    }
)


def compute_basic_metrics(result: BacktestResult) -> dict[str, float]:
    """Compute seven scalar metrics from a BacktestResult.

    Returns a dict with keys:
      total_return      — sum of all trade PnLs, in currency units
      max_drawdown_abs  — max peak-to-trough drawdown, in currency units
      max_drawdown_pct  — max peak-to-trough drawdown as a fraction of the
                          preceding peak equity (dimensionless, in [0, 1]);
                          compare this against fractional gate thresholds
      sharpe_ratio      — per-trade Sharpe: mean(pnl) / std(pnl), sample std
                          (n-1 denominator); NOT annualised; 0.0 when n < 2 or std == 0
      trade_count       — number of closed trades (int)
      win_rate          — fraction of trades with pnl > 0 (in [0, 1])
      avg_trade_pnl     — mean trade PnL in currency units

    All values are 0.0 / 0 when there are no trades.
    """
    pnls = result.pnls  # list[float]
    equity = list(result.equity)  # list[float] — cumulative PnL per trade

    n = len(pnls)
    if n == 0:
        return {k: 0.0 for k in _REQUIRED_KEYS}

    total_return = sum(pnls)
    avg_trade_pnl = total_return / n
    win_rate = sum(1 for p in pnls if p > 0) / n

    # Max peak-to-trough drawdown on the per-trade equity curve.
    max_drawdown_abs = 0.0
    max_drawdown_pct = 0.0
    if equity:
        peak = equity[0]
        for v in equity:
            if v > peak:
                peak = v
            dd_abs = peak - v
            if dd_abs > max_drawdown_abs:
                max_drawdown_abs = dd_abs
                # Percentage relative to the preceding peak (mirrors gate.py formula).
                # Guard: if peak is zero, drawdown fraction is undefined → treat as 0.
                max_drawdown_pct = dd_abs / abs(peak) if peak != 0.0 else 0.0

    # Per-trade Sharpe: mean / sample-std. Returns 0 when std is zero or n < 2.
    sharpe_ratio = 0.0
    if n >= 2:
        mean = avg_trade_pnl
        variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        std = math.sqrt(variance)
        if std > 0:
            sharpe_ratio = mean / std

    return {
        "total_return": total_return,
        "max_drawdown_abs": max_drawdown_abs,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": n,
        "win_rate": win_rate,
        "avg_trade_pnl": avg_trade_pnl,
    }
