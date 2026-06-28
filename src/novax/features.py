"""Causal technical indicators — Phase 1 Batch 1.

All functions satisfy assert_no_lookahead: for any i,
    fn(bars[:i+1])[-1] == fn(bars)[i]

NaN is returned for indices where insufficient history exists, so early bars
never inject a synthetic zero that could inflate an apparent edge. Callers
must handle NaN explicitly (e.g. skip bars until history is warm).

Functions operate on Sequence[Bar] and return list[float] of the same length,
making them compatible with novax.lookahead.find_lookahead_indices.
"""
from __future__ import annotations

from collections.abc import Sequence

from .data_sources import Bar

__all__ = ["ema", "atr"]

_NAN = float("nan")


def ema(bars: Sequence[Bar], period: int) -> list[float]:
    """Causal EMA of close prices (standard exponential smoothing).

    Seeded with the simple mean of the first `period` closes. Returns NaN for
    indices 0 .. period-2 (insufficient history).
    """
    if period < 1:
        raise ValueError(f"ema period must be >= 1, got {period}")
    n = len(bars)
    if n == 0:
        return []

    result: list[float] = [_NAN] * n
    if n < period:
        return result

    k = 2.0 / (period + 1)
    seed_idx = period - 1
    # Seed: SMA of the first `period` closes — all in the prefix at index seed_idx.
    current = sum(b.close for b in bars[:period]) / period
    result[seed_idx] = current

    for i in range(period, n):
        current = bars[i].close * k + current * (1.0 - k)
        result[i] = current

    return result


def atr(bars: Sequence[Bar], period: int) -> list[float]:
    """Causal ATR using Wilder's smoothing (equivalent to EMA with alpha=1/period).

    True Range at index 0 uses only the bar's own high-low range (no previous
    close). Returns NaN for indices 0 .. period-2.
    """
    if period < 1:
        raise ValueError(f"atr period must be >= 1, got {period}")
    n = len(bars)
    if n == 0:
        return []

    # Compute True Range causally: TR[i] uses only bars[i] and bars[i-1].
    tr: list[float] = []
    for i in range(n):
        hi, lo = bars[i].high, bars[i].low
        if i == 0:
            tr.append(hi - lo)
        else:
            prev_close = bars[i - 1].close
            tr.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))

    result: list[float] = [_NAN] * n
    if n < period:
        return result

    seed_idx = period - 1
    current = sum(tr[:period]) / period
    result[seed_idx] = current

    for i in range(period, n):
        current = (current * (period - 1) + tr[i]) / period
        result[i] = current

    return result
