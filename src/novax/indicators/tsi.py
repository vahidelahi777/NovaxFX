"""True Strength Index — double-smoothed momentum oscillator."""

from __future__ import annotations

from dataclasses import dataclass

from .ema import EMAIndicator

__all__ = ["TSIIndicator", "TSIResult"]


@dataclass(frozen=True)
class TSIResult:
    """TSI output for one bar."""

    tsi: float
    """True Strength Index value. Range is bounded to [-100, 100] by construction."""
    signal: float
    """Signal line: EMA(TSI, signal_period)."""


class TSIIndicator:
    """True Strength Index (Elder, 1993) — double-smoothed price momentum.

    Formula:
        momentum = close - prev_close
        double_smoothed     = EMA(EMA(momentum,   long), short)
        double_smoothed_abs = EMA(EMA(|momentum|, long), short)
        TSI    = 100 * double_smoothed / double_smoothed_abs
        signal = EMA(TSI, signal_period)

    Composed from 5 EMAIndicator instances — all O(1) per bar.

    Warm-up: returns None for the first 1 + long_period + short_period + signal_period - 2 bars.
    """

    def __init__(
        self,
        long_period: int = 25,
        short_period: int = 13,
        signal_period: int = 13,
    ) -> None:
        if any(p < 1 for p in (long_period, short_period, signal_period)):
            raise ValueError("TSIIndicator: all periods must be >= 1")
        self.long_period = long_period
        self.short_period = short_period
        self.signal_period = signal_period
        self._ema_mom_long = EMAIndicator(long_period)
        self._ema_mom_short = EMAIndicator(short_period)
        self._ema_abs_long = EMAIndicator(long_period)
        self._ema_abs_short = EMAIndicator(short_period)
        self._ema_signal = EMAIndicator(signal_period)
        self._prev_close: float | None = None
        self._result: TSIResult | None = None

    @property
    def value(self) -> TSIResult | None:
        """Latest TSI result, or None during warm-up."""
        return self._result

    def update(self, close: float) -> TSIResult | None:
        """Feed one close price. Returns TSIResult or None if still warming up."""
        if self._prev_close is None:
            self._prev_close = close
            return None

        momentum = close - self._prev_close
        self._prev_close = close

        ds_mom = self._ema_mom_short.update(self._ema_mom_long.update(momentum))
        ds_abs = self._ema_abs_short.update(self._ema_abs_long.update(abs(momentum)))

        if ds_mom is None or ds_abs is None or ds_abs == 0.0:
            return None

        tsi = 100.0 * ds_mom / ds_abs
        signal = self._ema_signal.update(tsi)
        if signal is None:
            return None

        self._result = TSIResult(tsi=tsi, signal=signal)
        return self._result
