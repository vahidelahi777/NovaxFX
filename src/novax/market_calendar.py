"""Market calendar — computed holidays + half-days, fail-closed.

Replaces the Phase 0.6 hardcoded 7-date stub. Holidays are COMPUTED from rules
(Good Friday via Easter, Thanksgiving = 4th Thu Nov, observed fixed dates, etc.)
so any year is covered, and the previously-missed mid-week holidays (Thanksgiving,
Good Friday, July 4) are caught. A `CalendarProvider` abstraction allows
instrument-specific calendars (e.g. XAU); missing calendar data fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

UTC = UTC

__all__ = [
    "CalendarProvider",
    "ComputedHolidayProvider",
    "MarketCalendar",
    "DEFAULT_FX_CALENDAR",
    "is_fx_market_open",
    "easter",
    "good_friday",
]


def easter(year: int) -> date:
    """Anonymous Gregorian (Meeus/Jones/Butcher) Easter Sunday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def good_friday(year: int) -> date:
    return easter(year) - timedelta(days=2)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth (1-based) weekday (Mon=0) of a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Last `weekday` of a month."""
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """US observed rule: Sat -> Fri, Sun -> Mon."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@runtime_checkable
class CalendarProvider(Protocol):
    def full_closures(self, year: int) -> set[date]: ...
    def half_days(self, year: int) -> set[date]: ...


@dataclass(frozen=True, slots=True)
class ComputedHolidayProvider:
    """Computes FX-relevant US/UK closures + half-days for any year."""

    name: str = "fx_us_uk"

    def full_closures(self, year: int) -> set[date]:
        return {
            date(year, 1, 1),  # New Year's Day
            good_friday(year),  # Good Friday
            date(year, 12, 25),  # Christmas
            date(year, 12, 26),  # Boxing Day (UK)
            _observed(date(year, 7, 4)),  # US Independence Day (observed)
            _nth_weekday(year, 11, 3, 4),  # US Thanksgiving (4th Thu Nov)
            _nth_weekday(year, 1, 0, 3),  # US MLK Day (3rd Mon Jan)
            _nth_weekday(year, 2, 0, 3),  # US Presidents' Day
            _last_weekday(year, 5, 0),  # US Memorial Day (last Mon May)
            _nth_weekday(year, 9, 0, 1),  # US Labor Day (1st Mon Sep)
        }

    def half_days(self, year: int) -> set[date]:
        return {
            _nth_weekday(year, 11, 3, 4) + timedelta(days=1),  # Black Friday
            date(year, 12, 24),  # Christmas Eve
        }


@dataclass(frozen=True, slots=True)
class MarketCalendar:
    name: str = "fx"
    provider: CalendarProvider = field(default_factory=ComputedHolidayProvider)
    week_close_local: time = time(17, 0)  # Friday NY close
    week_open_local: time = time(17, 0)  # Sunday NY open
    half_day_close_local: time = time(12, 0)
    tz: str = "America/New_York"

    def is_holiday(self, d: date) -> bool:
        return d in self.provider.full_closures(d.year)

    def is_half_day(self, d: date) -> bool:
        return d in self.provider.half_days(d.year)

    def is_open(self, dt_utc: datetime) -> bool:
        if dt_utc.tzinfo is None:
            raise ValueError("naive datetime rejected: must be tz-aware UTC")
        local = dt_utc.astimezone(ZoneInfo(self.tz))
        wd, t, d = local.weekday(), local.time(), local.date()
        if self.is_holiday(d):
            return False
        if wd == 5:
            return False
        if wd == 4 and t >= self.week_close_local:
            return False
        if self.is_half_day(d) and t >= self.half_day_close_local:
            return False
        return not (wd == 6 and t < self.week_open_local)


DEFAULT_FX_CALENDAR = MarketCalendar()


def is_fx_market_open(dt_utc: datetime, calendar: MarketCalendar = DEFAULT_FX_CALENDAR) -> bool:
    return calendar.is_open(dt_utc)
