"""Average True Range (ATR) indicator using Wilder's RMA."""

from __future__ import annotations

from .ema import RMAIndicator

__all__ = ["ATRIndicator"]


class ATRIndicator:
    """ATR with Wilder's smoothing (RMA), matching TradingView's ta.atr()."""

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"ATRIndicator: period must be >= 1, got {period}")
        self.period = period
        self._rma = RMAIndicator(period)
        self._prev_close: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        """Feed one bar. Returns ATR or None during warm-up."""
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        return self._rma.update(tr)
