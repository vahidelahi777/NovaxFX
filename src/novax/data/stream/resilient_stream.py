"""Resilient WebSocket supervisor with reconnect, gap backfill, and watchdog.

Architecture
------------
- `ResilientStream.run()` is an asyncio coroutine that loops until cancelled.
- Each iteration starts a `TwelveDataStream` in a thread (the SDK blocks).
- A watchdog coroutine detects stalled feeds (no bar for 1.5× interval) and
  signals the supervisor to tear down and reconnect.
- Reconnect uses capped exponential backoff.
- After every reconnect the gap is backfilled via REST, and only bars newer
  than the last received bar are pushed to the queue.

Pure helpers (backoff_delay, gap_window, filter_new_bars) are extracted so
they can be unit-tested without the SDK or network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from ...data_sources import Bar
from ..ingest.twelvedata import fetch_bars
from .twelvedata_ws import TwelveDataStream

__all__ = [
    "ResilientStream",
    "backoff_delay",
    "filter_new_bars",
    "gap_window",
]

log = logging.getLogger(__name__)

# Reconnect back-off sequence (seconds). Last value is the cap.
_BACKOFF: tuple[int, ...] = (1, 2, 5, 15, 30, 60)

# Map interval_seconds → TwelveData interval string
_INTERVAL_STR: dict[int, str] = {
    60: "1min",
    300: "5min",
    900: "15min",
    3600: "1h",
    14400: "4h",
    86400: "1day",
}


def _interval_label(interval_seconds: int) -> str:
    return _INTERVAL_STR.get(interval_seconds, f"{interval_seconds // 60}min")


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — unit-testable)
# ---------------------------------------------------------------------------


def backoff_delay(attempt: int, sequence: tuple[int, ...] = _BACKOFF) -> int:
    """Return the reconnect delay (seconds) for the given attempt index (0-based)."""
    return sequence[min(attempt, len(sequence) - 1)]


def gap_window(
    last_bar_ts: datetime,
    interval_seconds: int,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return the (start, end) window for a REST backfill.

    start = last_bar_ts + interval (the next bar we need)
    end   = now
    """
    start = last_bar_ts + timedelta(seconds=interval_seconds)
    return start, now


def filter_new_bars(bars: list[Bar], after: datetime) -> list[Bar]:
    """Return bars strictly newer than *after*, sorted by timestamp ascending."""
    return sorted((b for b in bars if b.ts > after), key=lambda b: b.ts)


# ---------------------------------------------------------------------------
# ResilientStream
# ---------------------------------------------------------------------------


class ResilientStream:
    """Async supervisor for a TwelveData WebSocket stream.

    Args:
        api_key:          TwelveData API key.
        symbol:           Symbol to stream (e.g. "XAU/USD").
        interval_seconds: Bar size (e.g. 900 for 15 min).
        bar_queue:        asyncio.Queue into which completed Bar objects are put.
        lookback_days:    Days to request on REST backfill (default 2).
        watchdog_mult:    Stall threshold = interval × this multiplier (default 1.5).
        fetch_fn:         Injected REST fetcher for testing (default: fetch_bars).
        sleep_fn:         Injected sleep function for testing (default: asyncio.sleep).
    """

    def __init__(
        self,
        api_key: str,
        symbol: str,
        interval_seconds: int,
        bar_queue: asyncio.Queue[Bar],
        *,
        lookback_days: int = 2,
        watchdog_mult: float = 1.5,
        fetch_fn: Callable[..., list[Bar]] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._symbol = symbol
        self._interval = interval_seconds
        self._queue = bar_queue
        self._lookback_days = lookback_days
        self._watchdog_mult = watchdog_mult
        self._fetch_fn: Callable[..., list[Bar]] = fetch_fn or fetch_bars
        self._sleep_fn: Callable[[float], Any] = sleep_fn or asyncio.sleep
        self._last_bar_ts: datetime | None = None
        self._last_tick_wall: float = 0.0  # monotonic seconds

    async def run(self) -> None:
        """Supervisor loop — runs until the task is cancelled."""
        attempt = 0
        loop = asyncio.get_running_loop()

        while True:
            if attempt > 0:
                delay = backoff_delay(attempt - 1)
                log.info(
                    "ResilientStream reconnect attempt %d — waiting %ds",
                    attempt,
                    delay,
                )
                await self._sleep_fn(delay)

            stall_event = asyncio.Event()

            def _make_on_bar(
                ev: asyncio.Event,
            ) -> Callable[[str, Bar], None]:
                def _cb(sym: str, bar: Bar) -> None:  # noqa: ARG001
                    self._on_bar(bar, loop, ev)

                return _cb

            stream = TwelveDataStream(
                api_key=self._api_key,
                symbols=[self._symbol],
                interval_seconds=self._interval,
                on_bar=_make_on_bar(stall_event),
            )

            try:
                self._last_tick_wall = time.monotonic()
                await asyncio.to_thread(stream.start)
                log.info("ResilientStream: stream started for %s", self._symbol)

                # Backfill gap from the last known bar.
                if self._last_bar_ts is not None:
                    await self._backfill()

                # Watchdog: wait for stall or cancellation.
                await self._watchdog(stall_event)
                log.warning(
                    "ResilientStream: watchdog stall detected for %s — reconnecting",
                    self._symbol,
                )
                attempt += 1
            except asyncio.CancelledError:
                log.info("ResilientStream: cancelled — stopping stream")
                raise
            except Exception:
                log.exception("ResilientStream: unexpected error — reconnecting")
                attempt += 1
            finally:
                try:
                    async with asyncio.timeout(5):
                        await asyncio.to_thread(stream.stop)
                except TimeoutError:
                    log.warning("ResilientStream: stream.stop timed out")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_bar(
        self,
        bar: Bar,
        loop: asyncio.AbstractEventLoop,
        stall_event: asyncio.Event,  # noqa: ARG002
    ) -> None:
        """Called from the SDK thread.  Hands bar to the asyncio queue."""
        self._last_bar_ts = bar.ts
        self._last_tick_wall = time.monotonic()
        loop.call_soon_threadsafe(self._queue.put_nowait, bar)

    async def _watchdog(self, stall_event: asyncio.Event) -> None:
        threshold = self._interval * self._watchdog_mult
        while True:
            await self._sleep_fn(threshold / 4)
            if stall_event.is_set():
                return
            elapsed = time.monotonic() - self._last_tick_wall
            if elapsed >= threshold:
                return

    async def _backfill(self) -> None:
        last_ts = self._last_bar_ts
        if last_ts is None:
            return
        now = datetime.now(tz=UTC)
        start, end = gap_window(last_ts, self._interval, now)
        if start >= end:
            return
        log.info(
            "ResilientStream backfill %s: %s → %s",
            self._symbol,
            start.strftime("%Y-%m-%dT%H:%M"),
            end.strftime("%Y-%m-%dT%H:%M"),
        )
        try:
            raw_bars: list[Bar] = await asyncio.to_thread(
                self._fetch_fn,
                self._symbol,
                _interval_label(self._interval),
                start,
                end,
                self._api_key,
            )
            new_bars = filter_new_bars(raw_bars, last_ts)
            for bar in new_bars:
                self._last_bar_ts = bar.ts
                self._queue.put_nowait(bar)
            log.info(
                "ResilientStream backfill: pushed %d bar(s) for %s",
                len(new_bars),
                self._symbol,
            )
        except Exception:
            log.exception("ResilientStream backfill failed — continuing without gap fill")
