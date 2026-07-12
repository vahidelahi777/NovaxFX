"""Multi-event calendar scheduler.

Merges epoch-aligned 15M bar-close events with fixed weekly calendar
events (market open/close, London/NY session opens, daily/weekly reports).

All calendar times are UTC:
  Sunday    22:00  — MARKET_OPEN   (Forex week open)
  Mon-Fri   08:00  — LONDON_OPEN   (11:30 IRST)
  Mon-Fri   13:00  — NY_OPEN       (16:30 IRST)
  Mon-Fri   20:00  — DAILY_REPORT  (23:30 IRST)
  Friday    21:00  — MARKET_CLOSE + WEEKLY_REPORT
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from .scheduler import BarScheduler

__all__ = ["EventScheduler", "EventType", "ScheduledEvent"]


class EventType(Enum):
    BAR_CLOSE_15M = "bar_close_15m"
    MARKET_OPEN = "market_open"  # Sunday 22:00 UTC
    MARKET_CLOSE = "market_close"  # Friday 21:00 UTC
    LONDON_OPEN = "london_open"  # Mon-Fri 08:00 UTC
    NY_OPEN = "ny_open"  # Mon-Fri 13:00 UTC
    DAILY_REPORT = "daily_report"  # Mon-Fri 20:00 UTC
    WEEKLY_REPORT = "weekly_report"  # Friday 21:00 UTC (same fire time as MARKET_CLOSE)


@dataclass(frozen=True)
class ScheduledEvent:
    fire_at: datetime  # always UTC-aware
    event_type: EventType


class EventScheduler:
    """Return the next event(s) across all event types.

    When multiple events share the same fire time (e.g. MARKET_CLOSE
    and WEEKLY_REPORT both fire Friday 21:00 UTC) they are returned
    together in a single ``next_events()`` call so the daemon can
    handle both without re-sleeping.
    """

    def __init__(self) -> None:
        self._bar = BarScheduler(900)

    def next_events(self, now: datetime) -> tuple[datetime, list[EventType]]:
        """Return *(fire_at, [EventType, ...])* for the soonest event(s).

        ``fire_at`` is always strictly after *now* and timezone-aware (UTC).
        """
        candidates: list[tuple[datetime, EventType]] = [
            (self._bar.next_bar_close(now), EventType.BAR_CLOSE_15M),
            (_next_single_weekday(now, 6, 22, 0), EventType.MARKET_OPEN),
            (_next_single_weekday(now, 4, 21, 0), EventType.MARKET_CLOSE),
            (_next_single_weekday(now, 4, 21, 0), EventType.WEEKLY_REPORT),
            (_next_business_day_time(now, 8, 0), EventType.LONDON_OPEN),
            (_next_business_day_time(now, 13, 0), EventType.NY_OPEN),
            (_next_business_day_time(now, 20, 0), EventType.DAILY_REPORT),
        ]

        earliest = min(t for t, _ in candidates)
        events = [et for t, et in candidates if t == earliest]
        return earliest, events


# ------------------------------------------------------------------
# Calendar helpers
# ------------------------------------------------------------------


def _next_single_weekday(now: datetime, weekday: int, hour: int, minute: int = 0) -> datetime:
    """Next occurrence of *weekday* (0=Mon … 6=Sun) at the given UTC time.

    Always strictly after *now*.
    """
    now_utc = now.astimezone(UTC)
    candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - now_utc.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now_utc:
        candidate += timedelta(weeks=1)
    return candidate


def _next_business_day_time(now: datetime, hour: int, minute: int = 0) -> datetime:
    """Next Mon-Fri occurrence of the given UTC time, strictly after *now*."""
    now_utc = now.astimezone(UTC)
    candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_utc:
        candidate += timedelta(days=1)
    while candidate.weekday() > 4:  # 5=Sat, 6=Sun
        candidate += timedelta(days=1)
    return candidate
