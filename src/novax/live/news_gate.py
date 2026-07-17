"""Economic calendar news gate — suppress signals around high-impact events.

How it works
------------
1. Fetch upcoming high-impact economic events from TwelveData's
   /economic_calendar endpoint (REST, not WebSocket).
2. Cache the result for a configurable duration (default 4 hours).
3. Before sending any Telegram alert, call `is_blocked(now)`.
   If True, the alert is suppressed and logged.

What counts as "high impact" (FX focus)
----------------------------------------
- Non-Farm Payrolls (NFP)       — first Friday 12:30 UTC
- Federal Reserve (FOMC)        — 8× per year, 18:00–20:00 UTC
- Consumer Price Index (CPI)    — monthly
- GDP releases                  — quarterly
- ISM Manufacturing / Services  — monthly
- Central bank rate decisions   — RBA, BoE, ECB, BoJ, Fed, BoC, SNB, RBNZ

Suppression window
------------------
Signals within [event_time - 30 min, event_time + 15 min] are blocked.
Gold (XAU/USD) is especially sensitive to USD events; the window is wider
than for pure FX pairs (±30/+30 vs ±15/+15 for others).

TwelveData /economic_calendar response (one item)
--------------------------------------------------
{
  "id":       "...",
  "date":     "2026-07-05 12:30:00",
  "country":  "United States",
  "event":    "Non-Farm Employment Change",
  "type":     "Economic",
  "actual":   "151K",
  "estimate": "165K",
  "previous": "139K",
  "impact":   "High",
  "currency": "USD"
}

Usage
-----
    gate = NewsGate(api_key=os.environ["TWELVEDATA_API_KEY"])

    if gate.is_blocked(datetime.now(tz=UTC)):
        log.info("Signal suppressed — high-impact news window")
        return

    _send_telegram(...)
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

__all__ = ["NewsGate", "EconomicEvent"]

log = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/economic_calendar"

# Suppression window around a high-impact event
_BLOCK_BEFORE = timedelta(minutes=30)
_BLOCK_AFTER = timedelta(minutes=15)

# Cache lifetime — fetch calendar at most once per window
_CACHE_TTL = timedelta(hours=4)

# Only USD and XAU events affect FX/Gold — expand as needed
_RELEVANT_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "XAU"}


class EconomicEvent:
    """A single high-impact economic event parsed from TwelveData."""

    __slots__ = ("event_time", "name", "country", "impact", "currency")

    def __init__(
        self,
        event_time: datetime,
        name: str,
        country: str,
        impact: str,
        currency: str,
    ) -> None:
        self.event_time = event_time
        self.name = name
        self.country = country
        self.impact = impact
        self.currency = currency

    def __repr__(self) -> str:
        return (
            f"EconomicEvent({self.event_time.strftime('%Y-%m-%d %H:%M UTC')} "
            f"{self.currency} {self.name!r} [{self.impact}])"
        )


class NewsGate:
    """Thread-safe economic calendar gate.

    Call is_blocked(now) before sending any trading signal. Returns True if
    a high-impact event falls within the suppression window around now.
    """

    def __init__(
        self,
        api_key: str,
        *,
        block_before: timedelta = _BLOCK_BEFORE,
        block_after: timedelta = _BLOCK_AFTER,
        cache_ttl: timedelta = _CACHE_TTL,
        relevant_currencies: set[str] = _RELEVANT_CURRENCIES,
        timeout: int = 10,
    ) -> None:
        self._api_key = api_key
        self._block_before = block_before
        self._block_after = block_after
        self._cache_ttl = cache_ttl
        self._relevant_currencies = relevant_currencies
        self._timeout = timeout

        self._lock = threading.Lock()
        self._events: list[EconomicEvent] = []
        self._last_fetch: datetime | None = None

    def is_blocked(self, now: datetime) -> bool:
        """Return True if now falls within a high-impact event window."""
        events = self._get_events(now)
        utc_now = now.astimezone(UTC)

        for ev in events:
            window_start = ev.event_time - self._block_before
            window_end = ev.event_time + self._block_after
            if window_start <= utc_now <= window_end:
                log.info(
                    "Signal blocked by news gate: %s %s at %s UTC (window %s – %s)",
                    ev.currency,
                    ev.name,
                    ev.event_time.strftime("%H:%M"),
                    window_start.strftime("%H:%M"),
                    window_end.strftime("%H:%M"),
                )
                return True
        return False

    def next_blocked_event(self, now: datetime) -> EconomicEvent | None:
        """Return the next upcoming high-impact event, or None if clear."""
        utc_now = now.astimezone(UTC)
        upcoming = [e for e in self._get_events(now) if e.event_time > utc_now]
        return min(upcoming, key=lambda e: e.event_time, default=None)

    def _get_events(self, now: datetime) -> list[EconomicEvent]:
        with self._lock:
            if self._cache_valid(now):
                return self._events
            try:
                self._events = self._fetch(now)
                self._last_fetch = now.astimezone(UTC)
                log.info("Economic calendar refreshed — %d high-impact events", len(self._events))
            except Exception as exc:
                # On failure, return stale cache rather than crashing the daemon
                log.warning("Economic calendar fetch failed: %s — using stale cache", exc)
            return self._events

    def _cache_valid(self, now: datetime) -> bool:
        if self._last_fetch is None:
            return False
        age = now.astimezone(UTC) - self._last_fetch
        return age < self._cache_ttl

    def _fetch(self, now: datetime) -> list[EconomicEvent]:
        utc_now = now.astimezone(UTC)
        start = utc_now - timedelta(hours=1)  # catch events that started recently
        end = utc_now + timedelta(hours=24)  # look 24 h ahead

        params = urllib.parse.urlencode(
            {
                "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
                "importance": "high",
                "apikey": self._api_key,
            }
        )
        req = urllib.request.Request(
            f"{_BASE_URL}?{params}",
            headers={"User-Agent": "novax-research/1.0"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
            payload: dict[str, object] = json.loads(resp.read())

        raw_events = payload.get("result", {})
        if isinstance(raw_events, dict):
            raw_events = raw_events.get("rows", [])
        if not isinstance(raw_events, list):
            return []

        events: list[EconomicEvent] = []
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            impact = str(item.get("impact", "")).capitalize()
            currency = str(item.get("currency", "")).upper()

            if impact != "High":
                continue
            if currency not in self._relevant_currencies:
                continue

            raw_dt = item.get("date", "")
            if not raw_dt:
                continue
            try:
                event_time = datetime.strptime(str(raw_dt), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue

            events.append(
                EconomicEvent(
                    event_time=event_time,
                    name=str(item.get("event", "Unknown")),
                    country=str(item.get("country", "")),
                    impact=impact,
                    currency=currency,
                )
            )

        return sorted(events, key=lambda e: e.event_time)
