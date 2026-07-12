"""EMA and RMA (Wilder's Smoothed MA) — O(1)-per-bar update indicators."""

from __future__ import annotations

__all__ = ["EMAIndicator", "RMAIndicator"]


class EMAIndicator:
    """Exponential Moving Average with alpha = 2/(period+1).

    Returns None during the first period-1 bars (warm-up). Accepts None inputs
    so it can be chained after another indicator that is still warming up.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"EMAIndicator: period must be >= 1, got {period}")
        self.period = period
        self._alpha: float = 2.0 / (period + 1)
        self._value: float | None = None
        self._count: int = 0

    @property
    def value(self) -> float | None:
        """Current EMA value, or None during warm-up."""
        return self._value if self._count >= self.period else None

    def update(self, price: float | None) -> float | None:
        """Feed one price. Returns current EMA or None if still warming up."""
        if price is None:
            return None
        self._count += 1
        if self._value is None:
            self._value = price
        else:
            self._value = self._alpha * price + (1.0 - self._alpha) * self._value
        return self.value


class RMAIndicator:
    """Wilder's Smoothed Moving Average with alpha = 1/period.

    Seeds the first period bars as a plain SMA, then switches to the recursive
    Wilder formula. This matches TradingView's ta.rma() behaviour exactly.
    Using this instead of EMA for ATR avoids 5-15 bar Supertrend divergence.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"RMAIndicator: period must be >= 1, got {period}")
        self.period = period
        self._alpha: float = 1.0 / period
        self._value: float | None = None
        self._warmup_sum: float = 0.0
        self._count: int = 0

    @property
    def value(self) -> float | None:
        """Current RMA value, or None during warm-up."""
        return self._value

    def update(self, price: float | None) -> float | None:
        """Feed one value. Returns current RMA or None if still warming up."""
        if price is None:
            return None
        self._count += 1
        if self._count < self.period:
            self._warmup_sum += price
        elif self._count == self.period:
            self._warmup_sum += price
            self._value = self._warmup_sum / self.period
        else:
            assert self._value is not None
            self._value = self._alpha * price + (1.0 - self._alpha) * self._value
        return self._value
