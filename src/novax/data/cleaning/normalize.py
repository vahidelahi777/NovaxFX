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

_MINUTES_PER_DAY = 1440

__all__ = ["ticks_to_1m_bars", "resample_bars"]


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


def resample_bars(bars: Sequence[Bar], interval_minutes: int) -> list[Bar]:
    """Aggregate bars to a coarser timeframe.

    Groups input bars into buckets of ``interval_minutes`` width and builds one
    OHLCV bar per bucket (open = first, high = max, low = min, close = last,
    volume = sum). ``interval_minutes`` must evenly divide 1440 (minutes per day).

    Raises:
        ValueError: If ``interval_minutes`` does not divide 1440 exactly.
    """
    if _MINUTES_PER_DAY % interval_minutes != 0:
        raise ValueError(
            f"interval_minutes={interval_minutes} does not evenly divide {_MINUTES_PER_DAY}"
        )
    if not bars:
        return []

    def _floor(ts: datetime) -> datetime:
        total_min = ts.hour * 60 + ts.minute
        floored = (total_min // interval_minutes) * interval_minutes
        return ts.replace(
            hour=floored // 60,
            minute=floored % 60,
            second=0,
            microsecond=0,
        )

    groups: dict[datetime, list[Bar]] = {}
    for bar in bars:
        key = _floor(bar.ts)
        groups.setdefault(key, []).append(bar)

    result: list[Bar] = []
    for key in sorted(groups):
        g = groups[key]
        first, last = g[0], g[-1]
        bid = last.bid if last.bid is not None else None
        ask = last.ask if last.ask is not None else None
        spread = (ask - bid) if (ask is not None and bid is not None) else last.spread
        result.append(
            Bar(
                ts=key,
                open=first.open,
                high=max(b.high for b in g),
                low=min(b.low for b in g),
                close=last.close,
                volume=sum(b.volume for b in g),
                bid=bid,
                ask=ask,
                spread=spread,
                source="resampled",
            )
        )
    return result
