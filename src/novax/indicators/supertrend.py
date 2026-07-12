"""Supertrend indicator using Wilder's RMA for ATR (matches TradingView)."""

from __future__ import annotations

from dataclasses import dataclass

from .ema import RMAIndicator

__all__ = ["SupertrendIndicator", "SupertrendResult"]


@dataclass(frozen=True)
class SupertrendResult:
    """Supertrend output for one bar."""

    value: float
    """Price level of the active band (lower band when bullish, upper when bearish)."""
    direction: int
    """+1 = bullish (price is above the support band), -1 = bearish (price below resistance)."""


class SupertrendIndicator:
    """Supertrend — volatility-adaptive trend filter.

    ATR is computed with Wilder's RMA (alpha = 1/period), not standard EMA
    (alpha = 2/(period+1)). The two alphas diverge enough to cause 5-15 bar
    signal differences vs TradingView's built-in Supertrend.

    Band carry-forward (simplified):
      - Bullish: lower band only ratchets up (never drops while price stays above it).
      - Bearish: upper band only ratchets down (never rises while price stays below it).

    Direction convention: +1 = bullish (green), -1 = bearish (red).
    """

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        if period < 1:
            raise ValueError(f"SupertrendIndicator: period must be >= 1, got {period}")
        if multiplier <= 0:
            raise ValueError(f"SupertrendIndicator: multiplier must be > 0, got {multiplier}")
        self.period = period
        self.multiplier = multiplier
        self._rma = RMAIndicator(period)
        self._prev_close: float | None = None
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        self._direction: int = 1
        self._result: SupertrendResult | None = None

    @property
    def value(self) -> SupertrendResult | None:
        """Latest result, or None during ATR warm-up."""
        return self._result

    def update(self, high: float, low: float, close: float) -> SupertrendResult | None:
        """Feed one bar. Returns SupertrendResult or None if ATR still warming up."""
        tr = (
            high - low
            if self._prev_close is None
            else max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        )
        self._prev_close = close

        atr = self._rma.update(tr)
        if atr is None:
            return None

        hl2 = (high + low) / 2.0
        raw_upper = hl2 + self.multiplier * atr
        raw_lower = hl2 - self.multiplier * atr

        if self._prev_upper is None:
            self._prev_upper = raw_upper
            self._prev_lower = raw_lower
            self._direction = 1
            self._result = SupertrendResult(value=raw_lower, direction=1)
            return self._result

        # Ratchet bands so they don't whipsaw
        # _prev_lower/_prev_upper are always set together with _prev_upper (checked above).
        prev_lower: float = self._prev_lower  # type: ignore[assignment]
        prev_upper: float = self._prev_upper
        lower: float = max(raw_lower, prev_lower)
        upper: float = min(raw_upper, prev_upper)

        # Direction flip: compare current close to current (carry-forwarded) bands
        if self._direction == -1 and close > upper:
            self._direction = 1
        elif self._direction == 1 and close < lower:
            self._direction = -1

        self._prev_upper = upper
        self._prev_lower = lower

        band = lower if self._direction == 1 else upper
        self._result = SupertrendResult(value=band, direction=self._direction)
        return self._result
