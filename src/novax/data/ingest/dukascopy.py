"""Dukascopy historical tick data downloader and parser.

Binary .bi5 format (20 bytes per tick, big-endian, LZMA-compressed):
  uint32  milliseconds from hour start
  uint32  ask price in points (divide by 100_000 to get price)
  uint32  bid price in points (divide by 100_000 to get price)
  float32 ask volume
  float32 bid volume

URL pattern:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH:02d}/{DAY:02d}/{HOUR:02d}_ticks.bi5
  Month is 0-indexed: January=00, December=11.
"""

from __future__ import annotations

import lzma
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

__all__ = ["RawTick", "parse_bi5", "download_hour", "fetch_day_ticks"]

_TICK_STRUCT = struct.Struct(">IIIff")  # 20 bytes, big-endian
_POINT_DIVISOR = 100_000
_BASE_URL = "https://datafeed.dukascopy.com/datafeed"


@dataclass(frozen=True, slots=True)
class RawTick:
    """Single tick from Dukascopy: timestamp, ask, bid, and volumes."""

    ts: datetime  # UTC, millisecond precision
    ask: float
    bid: float
    ask_vol: float
    bid_vol: float

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0


def parse_bi5(data: bytes, hour_ts: datetime) -> list[RawTick]:
    """Decompress LZMA-compressed .bi5 data and parse all ticks.

    Args:
        data: Raw LZMA-compressed bytes from Dukascopy. Empty bytes → [].
        hour_ts: UTC datetime representing the start of the hour (minute/second/us=0).

    Raises:
        lzma.LZMAError: If decompression fails (corrupt or truncated data).
        ValueError: If decompressed size is not a multiple of 20 bytes.
    """
    if not data:
        return []
    raw = lzma.decompress(data)
    if len(raw) % _TICK_STRUCT.size != 0:
        raise ValueError(
            f"Decompressed .bi5 data is {len(raw)} bytes, "
            f"not a multiple of {_TICK_STRUCT.size}; file may be truncated."
        )
    n = len(raw) // _TICK_STRUCT.size
    ticks: list[RawTick] = []
    for i in range(n):
        ms_offset, ask_pts, bid_pts, ask_vol, bid_vol = _TICK_STRUCT.unpack_from(
            raw, i * _TICK_STRUCT.size
        )
        ticks.append(
            RawTick(
                ts=hour_ts + timedelta(milliseconds=int(ms_offset)),
                ask=ask_pts / _POINT_DIVISOR,
                bid=bid_pts / _POINT_DIVISOR,
                ask_vol=float(ask_vol),
                bid_vol=float(bid_vol),
            )
        )
    return ticks


def download_hour(symbol: str, hour_ts: datetime, *, timeout: int = 30) -> bytes | None:
    """Download the .bi5 file for a given symbol and UTC hour.

    Returns raw (compressed) bytes, or None if the hour has no data (HTTP 404).
    All other HTTP errors are re-raised unchanged.
    """
    month0 = hour_ts.month - 1  # Dukascopy uses 0-indexed months
    url = (
        f"{_BASE_URL}/{symbol.upper()}/"
        f"{hour_ts.year}/{month0:02d}/{hour_ts.day:02d}/{hour_ts.hour:02d}_ticks.bi5"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def fetch_day_ticks(symbol: str, date: datetime, *, timeout: int = 30) -> list[RawTick]:
    """Fetch all ticks for a single UTC day by downloading 24 hourly .bi5 files.

    Args:
        symbol: Instrument symbol, e.g. "EURUSD".
        date: UTC date; time components are replaced internally (hour=0..23).
        timeout: Per-request timeout in seconds.

    Returns:
        All ticks for the day sorted by timestamp. Hours with no data (404) are skipped.

    Raises:
        ValueError: If date is not tz-aware.
    """
    if date.tzinfo is None:
        raise ValueError("date must be tz-aware UTC")
    ticks: list[RawTick] = []
    for hour in range(24):
        hour_ts = date.replace(hour=hour, minute=0, second=0, microsecond=0, tzinfo=UTC)
        data = download_hour(symbol, hour_ts, timeout=timeout)
        if data is not None:
            ticks.extend(parse_bi5(data, hour_ts))
    return ticks
