"""Performance reporter for paper trading journals.

Computes the same metrics as novax.metrics.compute_basic_metrics but operates
on CompletedTrade records from the trade journal rather than BacktestResult.
Does NOT import from the backtest engine — the live package is self-contained.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime

from .trade_journal import CompletedTrade

__all__ = ["PerformanceReport", "compute_performance"]


@dataclass(frozen=True)
class PerformanceReport:
    symbol: str
    timeframe: str
    trade_count: int
    win_count: int
    win_rate: float          # [0, 1]; nan when trade_count == 0
    total_pnl: float
    avg_pnl: float           # nan when trade_count == 0
    profit_factor: float     # sum_wins / abs(sum_losses); inf when no losses; nan when no trades
    max_drawdown_abs: float  # max peak-to-trough on cumulative per-trade equity
    sharpe_ratio: float      # mean(pnl) / sample_std(pnl); nan when fewer than 2 trades
    exit_counts: dict[str, int]
    first_trade_ts: datetime | None
    last_trade_ts: datetime | None


def compute_performance(
    trades: list[CompletedTrade],
    *,
    symbol: str,
    timeframe: str,
) -> PerformanceReport:
    """Compute performance metrics from a list of completed trades."""
    nan = float("nan")

    exit_counts: dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_kind] = exit_counts.get(t.exit_kind, 0) + 1

    n = len(trades)
    if n == 0:
        return PerformanceReport(
            symbol=symbol,
            timeframe=timeframe,
            trade_count=0,
            win_count=0,
            win_rate=nan,
            total_pnl=0.0,
            avg_pnl=nan,
            profit_factor=nan,
            max_drawdown_abs=0.0,
            sharpe_ratio=nan,
            exit_counts=exit_counts,
            first_trade_ts=None,
            last_trade_ts=None,
        )

    pnls = [t.pnl for t in trades]
    win_count = sum(1 for p in pnls if p > 0)
    win_rate = win_count / n
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / n

    sum_wins = sum(p for p in pnls if p > 0)
    sum_losses = sum(p for p in pnls if p < 0)  # negative or 0
    if sum_losses == 0:
        profit_factor = math.inf if sum_wins > 0 else nan
    else:
        profit_factor = sum_wins / abs(sum_losses)

    # Max peak-to-trough drawdown on the per-trade cumulative equity curve.
    max_drawdown_abs = 0.0
    peak = 0.0
    cumulative = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_drawdown_abs:
            max_drawdown_abs = dd

    if n < 2:
        sharpe_ratio = nan
    else:
        std = statistics.stdev(pnls)
        sharpe_ratio = statistics.mean(pnls) / std if std != 0.0 else nan

    return PerformanceReport(
        symbol=symbol,
        timeframe=timeframe,
        trade_count=n,
        win_count=win_count,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl=avg_pnl,
        profit_factor=profit_factor,
        max_drawdown_abs=max_drawdown_abs,
        sharpe_ratio=sharpe_ratio,
        exit_counts=exit_counts,
        first_trade_ts=trades[0].entry_ts,
        last_trade_ts=trades[-1].exit_ts,
    )
