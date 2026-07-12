"""Break-of-Structure detector — causal, O(1) per bar."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from ..data_sources import Bar
from .weekly_levels import WeeklyLevels

__all__ = ["BOSDetector", "BOSResult", "BOSState"]


class BOSState(StrEnum):
    IDLE = "idle"
    BOS_UP = "bos_up"
    BOS_DOWN = "bos_down"


@dataclass(frozen=True)
class BOSResult:
    state: BOSState
    bos_level: float
    ob_high: float
    ob_low: float
    choch_bearish: bool
    choch_bullish: bool

    @property
    def has_ob(self) -> bool:
        return not math.isnan(self.ob_high)


def _find_ob(buffer: deque[Bar], direction: str) -> tuple[float, float]:
    for bar in reversed(buffer):
        if direction == "up" and bar.open > bar.close:
            return bar.high, bar.low
        if direction == "down" and bar.close > bar.open:
            return bar.high, bar.low
    return math.nan, math.nan


class BOSDetector:
    """Detects weekly BOS, identifies the Order Block, and tracks CHoCH.

    Feed bars in strictly ascending timestamp order via update().
    Returns None until WeeklyLevelTracker has enough history to supply levels.
    BOS triggers on close only (not wick). State resets each new ISO week.
    OB is the last opposing candle in the buffer before the BOS bar.
    """

    def __init__(self) -> None:
        self._buffer: deque[Bar] = deque(maxlen=20)
        self._state: BOSState = BOSState.IDLE
        self._bos_level: float = math.nan
        self._ob_high: float = math.nan
        self._ob_low: float = math.nan
        self._curr_week: tuple[int, int] | None = None
        self._prev_week_high: float | None = None
        self._prev_week_low: float | None = None
        self._two_weeks_ago_high: float | None = None
        self._two_weeks_ago_low: float | None = None
        self._result: BOSResult | None = None

    @property
    def value(self) -> BOSResult | None:
        return self._result

    def update(self, bar: Bar, levels: WeeklyLevels | None) -> BOSResult | None:
        if levels is None:
            self._buffer.append(bar)
            return None

        new_week_key = (levels.year, levels.week)

        if new_week_key != self._curr_week:
            if self._curr_week is not None:
                self._two_weeks_ago_high = self._prev_week_high
                self._two_weeks_ago_low = self._prev_week_low
            # Always capture the new prev_* so CHoCH has it on the NEXT transition.
            self._prev_week_high = levels.prev_high
            self._prev_week_low = levels.prev_low
            self._curr_week = new_week_key
            self._state = BOSState.IDLE
            self._bos_level = math.nan
            self._ob_high = math.nan
            self._ob_low = math.nan

        choch_bearish = False
        choch_bullish = False
        if self._two_weeks_ago_high is not None:
            choch_bearish = levels.prev_high < self._two_weeks_ago_high
        if self._two_weeks_ago_low is not None:
            choch_bullish = levels.prev_low > self._two_weeks_ago_low

        if self._state == BOSState.IDLE:
            if bar.close > levels.prev_high:
                self._state = BOSState.BOS_UP
                self._bos_level = levels.prev_high
                self._ob_high, self._ob_low = _find_ob(self._buffer, direction="up")
            elif bar.close < levels.prev_low:
                self._state = BOSState.BOS_DOWN
                self._bos_level = levels.prev_low
                self._ob_high, self._ob_low = _find_ob(self._buffer, direction="down")

        self._buffer.append(bar)

        self._result = BOSResult(
            state=self._state,
            bos_level=self._bos_level,
            ob_high=self._ob_high,
            ob_low=self._ob_low,
            choch_bearish=choch_bearish,
            choch_bullish=choch_bullish,
        )
        return self._result
