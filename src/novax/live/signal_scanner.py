"""Stateless signal scanner for WeeklyBOSRetest strategy.

Creates a fresh strategy instance on each call, replays all supplied bars,
and returns a structured snapshot of the signal and context at the last bar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..data_sources import Bar
from ..engine import BarView, Position, Signal
from ..strategies.weekly_bos_retest import WeeklyBOSRetest

__all__ = ["ScanResult", "SignalScanner"]


@dataclass(frozen=True)
class ScanResult:
    ts: datetime
    symbol: str
    timeframe: str
    signal: Signal
    bos_state: str
    has_ob: bool
    ob_high: float | None
    ob_low: float | None
    prev_week_high: float | None
    prev_week_low: float | None
    sl: float | None
    tp: float | None
    n_bars_used: int


def _nan_to_none(v: float) -> float | None:
    return None if math.isnan(v) else v


class SignalScanner:
    """Replay bars through a fresh WeeklyBOSRetest and capture the last signal.

    Args:
        symbol: Instrument identifier (e.g. "XAUUSD").
        timeframe: Bar timeframe label (e.g. "4h").
        strategy_params: Optional keyword overrides for WeeklyBOSRetest constructor.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str = "4h",
        strategy_params: dict[str, Any] | None = None,
    ) -> None:
        self._symbol = symbol
        self._timeframe = timeframe
        self._params: dict[str, Any] = strategy_params or {}

    def scan(self, bars: list[Bar]) -> ScanResult:
        """Replay *bars* and return a signal snapshot at the final bar.

        Returns a FLAT result immediately when fewer than 2 bars are supplied
        (the engine requires at least 2 bars to emit any fills, so a single-bar
        window cannot produce a meaningful signal).
        """
        last_ts = bars[-1].ts if bars else datetime.fromtimestamp(0, tz=UTC)

        if len(bars) < 2:
            return ScanResult(
                ts=last_ts,
                symbol=self._symbol,
                timeframe=self._timeframe,
                signal=Signal.FLAT,
                bos_state="idle",
                has_ob=False,
                ob_high=None,
                ob_low=None,
                prev_week_high=None,
                prev_week_low=None,
                sl=None,
                tp=None,
                n_bars_used=len(bars),
            )

        strat = WeeklyBOSRetest(**self._params)
        flat = Position(direction="FLAT")

        last_signal = Signal.FLAT
        for i, _bar in enumerate(bars):
            view = BarView(bars=tuple(bars[: i + 1]))
            last_signal = strat.on_bar(view, flat)

        bos_result = strat._bos.value  # noqa: SLF001
        weekly_levels = strat._weekly.value  # noqa: SLF001

        bos_state = bos_result.state.value if bos_result is not None else "idle"
        has_ob = bos_result.has_ob if bos_result is not None else False
        ob_high = _nan_to_none(bos_result.ob_high) if bos_result is not None else None
        ob_low = _nan_to_none(bos_result.ob_low) if bos_result is not None else None
        prev_week_high = weekly_levels.prev_high if weekly_levels is not None else None
        prev_week_low = weekly_levels.prev_low if weekly_levels is not None else None

        return ScanResult(
            ts=last_ts,
            symbol=self._symbol,
            timeframe=self._timeframe,
            signal=last_signal,
            bos_state=bos_state,
            has_ob=has_ob,
            ob_high=ob_high,
            ob_low=ob_low,
            prev_week_high=prev_week_high,
            prev_week_low=prev_week_low,
            sl=strat._sl,  # noqa: SLF001
            tp=strat._tp,  # noqa: SLF001
            n_bars_used=len(bars),
        )
