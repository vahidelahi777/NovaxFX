"""Twelve Data historical bar downloader.

Fetches OHLC bars via the Twelve Data time_series endpoint.
FX and precious metals are supported; no bid/ask or volume is provided by
the API, so spread is synthesized from the instrument's pip_size.

Rate limits (Basic plan): 800 API credits/day, 8 requests/minute.
Each time_series call costs 1 credit and returns up to 5000 bars.
For 4h bars this covers ~3 years per request — no pagination needed
on the Basic plan for typical research windows.

Timestamp convention: Twelve Data returns FX timestamps in UTC.
The `timezone=UTC` parameter is sent on every request to make this explicit.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from ...data_sources import Bar
from ...instruments import get_instrument

__all__ = ["fetch_bars"]

_BASE_URL = "https://api.twelvedata.com/time_series"
_MAX_OUTPUTSIZE = 5000
_DT_INTRADAY = "%Y-%m-%d %H:%M:%S"
_DT_DAILY = "%Y-%m-%d"


def _parse_dt(raw: str) -> datetime:
    fmt = _DT_DAILY if len(raw) == 10 else _DT_INTRADAY
    return datetime.strptime(raw, fmt).replace(tzinfo=UTC)


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime(_DT_INTRADAY)


def _fetch_page(
    td_symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    api_key: str,
    timeout: int,
) -> list[dict[str, str]]:
    params = urllib.parse.urlencode(
        {
            "symbol": td_symbol,
            "interval": interval,
            "start_date": _fmt_dt(start),
            "end_date": _fmt_dt(end),
            "outputsize": _MAX_OUTPUTSIZE,
            "timezone": "UTC",
            "apikey": api_key,
        }
    )
    req = urllib.request.Request(
        f"{_BASE_URL}?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; novax-research/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload: dict[str, object] = json.loads(resp.read())

    if payload.get("status") == "error":
        raise RuntimeError(
            f"Twelve Data error for {td_symbol}: {payload.get('message', 'unknown')}"
        )
    values = payload.get("values", [])
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, dict)]


def fetch_bars(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    api_key: str,
    *,
    nominal_spread_pips: float = 2.0,
    request_delay: float = 8.0,
    timeout: int = 30,
) -> list[Bar]:
    """Download OHLC bars from Twelve Data for a symbol and date range.

    Args:
        symbol: Any form accepted by get_instrument: "EURUSD", "EUR/USD", "EUR_USD".
        interval: Twelve Data interval string: "1min", "5min", "1h", "4h", "1day".
        start: UTC start datetime (inclusive).
        end: UTC end datetime (inclusive).
        api_key: Twelve Data API key (never log or print this value).
        nominal_spread_pips: Pips used to synthesize bid/ask (default 2.0 = 1-pip half-spread).
        request_delay: Seconds between paginated requests to respect the 8 req/min limit.
        timeout: Per-request HTTP timeout in seconds.

    Returns:
        Bars sorted oldest-first. Returns [] when the API has no data for the range.

    Raises:
        ValueError: If start/end are not UTC-aware.
        RuntimeError: If the API returns an error status.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be tz-aware UTC datetimes")

    inst = get_instrument(symbol)
    spread = nominal_spread_pips * inst.pip_size
    td_symbol = inst.symbol  # canonical "EUR/USD" / "XAU/USD" as expected by TD

    raw: list[dict[str, str]] = []
    page_end = end

    while True:
        page = _fetch_page(td_symbol, interval, start, page_end, api_key, timeout)
        raw.extend(page)

        if len(page) < _MAX_OUTPUTSIZE:
            break  # received everything available in this range

        oldest_dt = _parse_dt(page[-1]["datetime"])
        if oldest_dt <= start:
            break  # reached (or passed) the requested start

        page_end = oldest_dt - timedelta(seconds=1)
        time.sleep(request_delay)

    if not raw:
        return []

    seen: set[datetime] = set()
    bars: list[Bar] = []
    for v in raw:
        ts = _parse_dt(v["datetime"])
        if ts < start or ts > end or ts in seen:
            continue
        seen.add(ts)
        open_ = float(v["open"])
        high_ = float(v["high"])
        low_ = float(v["low"])
        close = float(v["close"])
        # Twelve Data occasionally returns close/open outside [low, high] due to
        # rounding artefacts. Expand high/low to restore OHLC consistency.
        high_ = max(high_, open_, close)
        low_ = min(low_, open_, close)
        bars.append(
            Bar(
                ts=ts,
                open=open_,
                high=high_,
                low=low_,
                close=close,
                volume=0.0,
                bid=close - spread / 2,
                ask=close + spread / 2,
                spread=spread,
                source="twelvedata",
            )
        )

    return sorted(bars, key=lambda b: b.ts)
