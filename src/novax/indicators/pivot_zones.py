"""Causal pivot-based supply/demand zone detector."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

from ..data_sources import Bar

__all__ = ["PivotZoneDetector", "PivotZone"]


@dataclass
class PivotZone:
    """A price zone anchored to a confirmed swing high or low."""

    price: float
    kind: Literal["support", "resistance"]
    touches: int = 1
    broken: bool = False

    def is_fresh(self, max_touches: int) -> bool:
        """Zone is usable: not broken and not exhausted by repeated tests."""
        return not self.broken and self.touches <= max_touches


class PivotZoneDetector:
    """Detects swing-high / swing-low pivots and tracks the resulting S/D zones.

    Detection is fully causal: a pivot at bar i is confirmed only after right_bars
    more bars have been observed, introducing a right_bars-bar lag.

    Zone freshness:
      - A zone is broken when price closes through it.
      - A zone is exhausted when it has been tested more than max_touches times.
      - active_zones returns only fresh zones (not broken, not exhausted).

    Touch counting: a bar touches a resistance zone when bar.high reaches within
    zone_merge_pips of the zone price; a support zone when bar.low does the same.
    Zone state is updated before pivot detection each bar so newly created zones
    are not immediately double-counted.
    """

    def __init__(
        self,
        pip_size: float,
        left_bars: int = 5,
        right_bars: int = 5,
        zone_merge_pips: float = 10.0,
        max_touches: int = 3,
    ) -> None:
        if left_bars < 1 or right_bars < 1:
            raise ValueError("left_bars and right_bars must be >= 1")
        if pip_size <= 0:
            raise ValueError("pip_size must be > 0")
        self.pip_size = pip_size
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.zone_merge_pips = zone_merge_pips
        self.max_touches = max_touches
        self._window: deque[Bar] = deque(maxlen=left_bars + right_bars + 1)
        self._zones: list[PivotZone] = []

    @property
    def active_zones(self) -> list[PivotZone]:
        """Fresh zones: not broken, touches <= max_touches."""
        return [z for z in self._zones if z.is_fresh(self.max_touches)]

    def update(self, bar: Bar) -> list[PivotZone]:
        """Feed one bar. Returns current active zones after updating state."""
        merge_dist = self.zone_merge_pips * self.pip_size

        # Update existing zone states before detecting new pivots so newly
        # added zones are not counted again in the same call.
        for zone in self._zones:
            if zone.broken:
                continue
            if zone.kind == "resistance":
                if bar.close > zone.price:
                    zone.broken = True
                elif bar.high >= zone.price - merge_dist:
                    zone.touches += 1
            else:
                if bar.close < zone.price:
                    zone.broken = True
                elif bar.low <= zone.price + merge_dist:
                    zone.touches += 1

        self._window.append(bar)

        if len(self._window) == self.left_bars + self.right_bars + 1:
            candidate = self._window[self.left_bars]
            if all(candidate.high >= b.high for b in self._window):
                self._add_or_merge(candidate.high, "resistance")
            if all(candidate.low <= b.low for b in self._window):
                self._add_or_merge(candidate.low, "support")

        return self.active_zones

    def _add_or_merge(self, price: float, kind: Literal["support", "resistance"]) -> None:
        merge_dist = self.zone_merge_pips * self.pip_size
        for zone in self._zones:
            if zone.kind == kind and not zone.broken and abs(zone.price - price) <= merge_dist:
                zone.touches += 1
                return
        self._zones.append(PivotZone(price=price, kind=kind))
