"""Weekly high/low tracker — causal, O(1) per bar."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..data_sources import Bar

__all__ = ["WeeklyLevelTracker", "WeeklyLevels"]


@dataclass(frozen=True)
class WeeklyLevels:
    """Snapshot of weekly price levels at a given bar."""

    prev_high: float
    """Highest high of the completed previous week. Frozen for the entire current week."""
    prev_low: float
    """Lowest low of the completed previous week. Frozen for the entire current week."""
    curr_high: float
    """Running highest high of the current (live) week so far."""
    curr_low: float
    """Running lowest low of the current (live) week so far."""
    week: int
    """ISO week number of the current week."""
    year: int
    """ISO year of the current week (required at year boundaries: W52/W53 → W1)."""


class WeeklyLevelTracker:
    """Tracks previous and current week high/low from a stream of H4 bars.

    Returns None until the first complete ISO week has been observed — at least
    two distinct ISO year+week values must appear before prev_high/prev_low
    are meaningful.

    Week boundary is detected by ISO (year, week) change between consecutive
    bars, which handles year boundaries (W52/W53 → W1) correctly.

    Bars must be fed in strictly ascending timestamp order. Out-of-order
    bars are not detected and will silently corrupt state.
    """

    def __init__(self) -> None:
        self._curr_high: float = -math.inf
        self._curr_low: float = math.inf
        self._curr_year: int | None = None
        self._curr_week: int | None = None
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._result: WeeklyLevels | None = None

    @property
    def value(self) -> WeeklyLevels | None:
        """Current levels, or None if fewer than two ISO weeks have been seen."""
        return self._result

    def update(self, bar: Bar) -> WeeklyLevels | None:
        """Feed one bar. Returns current WeeklyLevels or None during first week."""
        iso = bar.ts.isocalendar()
        new_year, new_week = iso.year, iso.week
        is_new_week = (new_year, new_week) != (self._curr_year, self._curr_week)

        if is_new_week:
            if self._curr_year is not None:
                # Finalise the week that just ended before resetting.
                self._prev_high = self._curr_high
                self._prev_low = self._curr_low
            # Start fresh accumulators for the new week, seeded with this bar.
            self._curr_high = bar.high
            self._curr_low = bar.low
            self._curr_year = new_year
            self._curr_week = new_week
        else:
            self._curr_high = max(self._curr_high, bar.high)
            self._curr_low = min(self._curr_low, bar.low)

        if self._prev_high is None or self._prev_low is None:
            self._result = None
        else:
            self._result = WeeklyLevels(
                prev_high=self._prev_high,
                prev_low=self._prev_low,
                curr_high=self._curr_high,
                curr_low=self._curr_low,
                week=self._curr_week,  # type: ignore[arg-type]
                year=self._curr_year,  # type: ignore[arg-type]
            )
        return self._result
