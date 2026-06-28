"""Minimal walk-forward split — Phase 1 Batch 2.

One deterministic train/test split. No randomness, no rolling windows,
no cross-validation. Train is the first N bars; test is the remainder.

Temporal ordering: this module does NOT sort the input. Callers are
responsible for passing bars in strictly ascending timestamp order.
Passing unsorted bars will silently produce a split where train[-1].ts >
test[0].ts, which is a temporal leakage. Use
    assert bars == sorted(bars, key=lambda b: b.ts)
at the call site if the sort guarantee cannot be established statically.

Cold-start note: when the engine runs on test bars only (no train
pre-warming), indicators that require a warmup period (e.g. EMA with
period=P) will produce NaN for the first P-1 test bars. With period=5
and 12 test bars this wastes ~33 % of the test segment. Consider
passing a longer test window or pre-seeding indicators on the tail of
the train set if this matters for your experiment.
"""

from __future__ import annotations

from collections.abc import Sequence

from .data_sources import Bar

__all__ = ["SimpleWalkForward"]


class SimpleWalkForward:
    def __init__(self, train_ratio: float = 0.7) -> None:
        if not (0.0 < train_ratio < 1.0):
            raise ValueError(f"train_ratio must be in (0, 1), got {train_ratio}")
        self.train_ratio = train_ratio

    def split(self, bars: Sequence[Bar]) -> tuple[list[Bar], list[Bar]]:
        """Return (train_bars, test_bars). Both slices are contiguous and non-overlapping.

        Precondition: bars must be sorted in ascending timestamp order.
        This is not enforced at runtime — see module docstring for the rationale.
        """
        n = len(bars)
        idx = int(n * self.train_ratio)
        if idx < 1:
            raise ValueError(f"train_ratio {self.train_ratio} yields empty train set (n={n})")
        if idx >= n:
            raise ValueError(f"train_ratio {self.train_ratio} yields empty test set (n={n})")
        return list(bars[:idx]), list(bars[idx:])
