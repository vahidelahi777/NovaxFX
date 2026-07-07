"""EMA-crossover strategy — simplest non-trivial trend-following signal.

Signal logic:
  LONG  when fast EMA > slow EMA
  SHORT when fast EMA < slow EMA
  FLAT  during warmup (fewer than slow bars seen)

EMAs are updated incrementally (O(1) per bar) using Wilder-style seeding:
the first slow bars seed the slow EMA as a simple mean; the first fast bars
seed the fast EMA the same way. Both start from the same bar-1 close stream,
so the slow seed incorporates all bars seen before the fast EMA goes live.

Causality guarantee: only view.last.close (the current bar) is read each call.
No future bar is ever accessed. This is structural, not tested per se — the
engine enforces it by passing view.bars[:i+1] at step i.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine import BarView, Position, Signal

__all__ = ["EMACross"]


@dataclass
class EMACross:
    """EMA crossover strategy. Parameters are fixed at construction.

    Args:
        fast: Period of the fast EMA (shorter, more reactive).
        slow: Period of the slow EMA (longer, smoother). Must be > fast.
    """

    fast: int
    slow: int

    # Internal state — reset by creating a new instance.
    _n: int = field(default=0, init=False, repr=False)
    _fast_sum: float = field(default=0.0, init=False, repr=False)
    _slow_sum: float = field(default=0.0, init=False, repr=False)
    _fast_ema: float = field(default=0.0, init=False, repr=False)
    _slow_ema: float = field(default=0.0, init=False, repr=False)
    _fast_warm: bool = field(default=False, init=False, repr=False)
    _slow_warm: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.fast < 1:
            raise ValueError(f"fast must be >= 1, got {self.fast}")
        if self.slow <= self.fast:
            raise ValueError(f"slow ({self.slow}) must be > fast ({self.fast})")

    def on_bar(self, view: BarView, position: Position) -> Signal:
        close = view.last.close
        self._n += 1

        # Fast EMA: seed with SMA of first `fast` bars, then use EMA formula.
        if not self._fast_warm:
            self._fast_sum += close
            if self._n >= self.fast:
                self._fast_ema = self._fast_sum / self.fast
                self._fast_warm = True
        else:
            k = 2.0 / (self.fast + 1)
            self._fast_ema += k * (close - self._fast_ema)

        # Slow EMA: continues accumulating through the fast warmup period.
        if not self._slow_warm:
            self._slow_sum += close
            if self._n >= self.slow:
                self._slow_ema = self._slow_sum / self.slow
                self._slow_warm = True
        else:
            k = 2.0 / (self.slow + 1)
            self._slow_ema += k * (close - self._slow_ema)

        if not (self._fast_warm and self._slow_warm):
            return Signal.FLAT

        return Signal.LONG if self._fast_ema > self._slow_ema else Signal.SHORT
