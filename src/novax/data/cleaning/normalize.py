"""Tick → 1-minute OHLCV bar aggregation using mid-price.

Mid price = (ask + bid) / 2. This is the standard approach for FX instruments
that have no central exchange price.

Volume per bar = sum of (ask_vol + bid_vol) / 2 across all ticks in the minute,
approximating the average traded volume at each tick.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ...data_sources import Bar
from ..ingest.dukascopy import RawTick

__all__ = ["ticks_to_1m_bars"]


def ticks_to_1m_bars(ticks: Sequence[RawTick], *, symbol: str = "unknown") -> list[Bar]:
    """Aggregate ticks into 1-minute OHLCV bars.

    Ticks within the same UTC minute are aggregated to a single bar:
      open   = mid of the first tick in the minute
      high   = max mid across all ticks in the minute
      low    = min mid across all ticks in the minute
      close  = mid of the last tick in the minute
      volume = sum of (ask_vol + bid_vol) / 2 per tick
      bid/ask/spread = values from the last tick in the minute

    Returns bars sorted by timestamp (ascending). Empty input → empty list.
    """
    if not ticks:
        return []

    _open: dict[datetime, float] = {}
    _high: dict[datetime, float] = {}
    _low: dict[datetime, float] = {}
    _close: dict[datetime, float] = {}
    _volume: dict[datetime, float] = {}
    _bid: dict[datetime, float] = {}
    _ask: dict[datetime, float] = {}

    for tick in ticks:
        ts = tick.ts.replace(second=0, microsecond=0)  # truncate to minute boundary
        mid = tick.mid
        vol = (tick.ask_vol + tick.bid_vol) / 2.0

        if ts not in _open:
            _open[ts] = mid
            _high[ts] = mid
            _low[ts] = mid
        else:
            if mid > _high[ts]:
                _high[ts] = mid
            if mid < _low[ts]:
                _low[ts] = mid

        _close[ts] = mid
        _volume[ts] = _volume.get(ts, 0.0) + vol
        _bid[ts] = tick.bid
        _ask[ts] = tick.ask

    bars: list[Bar] = []
    for ts in sorted(_open):
        ask = _ask[ts]
        bid = _bid[ts]
        bars.append(
            Bar(
                ts=ts,
                open=_open[ts],
                high=_high[ts],
                low=_low[ts],
                close=_close[ts],
                volume=_volume[ts],
                bid=bid,
                ask=ask,
                spread=ask - bid,
                source="dukascopy",
            )
        )
    return bars
