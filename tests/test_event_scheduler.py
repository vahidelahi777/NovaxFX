"""Tests for EventScheduler and calendar helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from novax.live.event_scheduler import (
    EventScheduler,
    EventType,
    _next_business_day_time,
    _next_single_weekday,
)


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class TestNextSingleWeekday:
    def test_sunday_market_open_from_saturday(self) -> None:
        # Saturday 10:00 → next Sunday 22:00
        now = _utc(2026, 7, 11, 10, 0)   # Saturday
        result = _next_single_weekday(now, 6, 22, 0)
        assert result == _utc(2026, 7, 12, 22, 0)

    def test_sunday_market_open_from_sunday_before_time(self) -> None:
        # Sunday 21:00 → same Sunday 22:00
        now = _utc(2026, 7, 12, 21, 0)
        result = _next_single_weekday(now, 6, 22, 0)
        assert result == _utc(2026, 7, 12, 22, 0)

    def test_sunday_market_open_from_sunday_at_exact_time(self) -> None:
        # Sunday 22:00:00 exactly → next Sunday 22:00
        now = _utc(2026, 7, 12, 22, 0, 0)
        result = _next_single_weekday(now, 6, 22, 0)
        assert result == _utc(2026, 7, 19, 22, 0)

    def test_friday_market_close_from_thursday(self) -> None:
        now = _utc(2026, 7, 9, 12, 0)   # Thursday
        result = _next_single_weekday(now, 4, 21, 0)
        assert result == _utc(2026, 7, 10, 21, 0)

    def test_result_strictly_after_now(self) -> None:
        # Exhaustive: for all weekdays and hours
        base = _utc(2026, 7, 6, 0, 0)
        for day_offset in range(7):
            for hour in range(24):
                now = base + timedelta(days=day_offset, hours=hour)
                for wd in range(7):
                    result = _next_single_weekday(now, wd, 12, 0)
                    assert result > now


class TestNextBusinessDayTime:
    def test_monday_08_from_monday_07(self) -> None:
        # Monday 07:00 → Monday 08:00
        now = _utc(2026, 7, 6, 7, 0)   # Monday
        result = _next_business_day_time(now, 8, 0)
        assert result == _utc(2026, 7, 6, 8, 0)

    def test_friday_after_time_skips_to_monday(self) -> None:
        # Friday 20:30 → Monday 08:00 (skips weekend)
        now = _utc(2026, 7, 10, 20, 30)   # Friday
        result = _next_business_day_time(now, 8, 0)
        assert result == _utc(2026, 7, 13, 8, 0)   # Monday

    def test_saturday_skips_to_monday(self) -> None:
        now = _utc(2026, 7, 11, 5, 0)   # Saturday
        result = _next_business_day_time(now, 8, 0)
        assert result == _utc(2026, 7, 13, 8, 0)   # Monday

    def test_sunday_skips_to_monday(self) -> None:
        now = _utc(2026, 7, 12, 10, 0)   # Sunday
        result = _next_business_day_time(now, 13, 0)
        assert result == _utc(2026, 7, 13, 13, 0)   # Monday

    def test_result_always_strictly_after_now(self) -> None:
        base = _utc(2026, 7, 6, 0, 0)
        for i in range(7 * 24):
            now = base + timedelta(hours=i)
            result = _next_business_day_time(now, 8, 0)
            assert result > now


class TestEventSchedulerReturnType:
    def _sched(self) -> EventScheduler:
        return EventScheduler()

    def test_returns_tuple_of_dt_and_list(self) -> None:
        now = _utc(2026, 7, 6, 9, 7)
        fire_at, events = self._sched().next_events(now)
        assert isinstance(fire_at, datetime)
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_fire_at_is_strictly_after_now(self) -> None:
        now = _utc(2026, 7, 6, 9, 7)
        fire_at, _ = self._sched().next_events(now)
        assert fire_at > now

    def test_fire_at_is_utc_aware(self) -> None:
        now = _utc(2026, 7, 6, 9, 7)
        fire_at, _ = self._sched().next_events(now)
        assert fire_at.tzinfo is not None

    def test_all_events_are_event_type(self) -> None:
        now = _utc(2026, 7, 6, 9, 7)
        _, events = self._sched().next_events(now)
        for e in events:
            assert isinstance(e, EventType)


class TestEventSchedulerCalendarFiring:
    def test_15m_fires_when_nearest(self) -> None:
        # Midweek, mid-hour — 15M bar close is always nearest
        now = _utc(2026, 7, 8, 9, 7)   # Wednesday 09:07 → next 15M at 09:15
        fire_at, events = EventScheduler().next_events(now)
        assert EventType.BAR_CLOSE_15M in events
        assert fire_at == _utc(2026, 7, 8, 9, 15)

    def test_market_open_fires_sunday_22(self) -> None:
        # Just before Sunday 22:00 → market open is nearest
        now = _utc(2026, 7, 12, 21, 59, 30)   # Sunday 21:59:30
        fire_at, events = EventScheduler().next_events(now)
        # 15M next close is 22:00 which ties with MARKET_OPEN
        assert EventType.MARKET_OPEN in events
        assert fire_at == _utc(2026, 7, 12, 22, 0)

    def test_market_close_and_weekly_report_fire_together(self) -> None:
        # Just before Friday 21:00
        now = _utc(2026, 7, 10, 20, 59, 30)   # Friday 20:59:30
        fire_at, events = EventScheduler().next_events(now)
        # Could be DAILY_REPORT at 20:00? No, 20:00 is in the past.
        # Actually at 20:59:30, next events:
        # 15M: 21:00 (coincides with MARKET_CLOSE and WEEKLY_REPORT)
        # So all three fire at 21:00
        assert fire_at == _utc(2026, 7, 10, 21, 0)
        assert EventType.MARKET_CLOSE in events
        assert EventType.WEEKLY_REPORT in events

    def test_london_open_fires_weekday_0800(self) -> None:
        # Just before Monday 08:00
        now = _utc(2026, 7, 6, 7, 59, 30)   # Monday 07:59:30
        fire_at, events = EventScheduler().next_events(now)
        assert fire_at == _utc(2026, 7, 6, 8, 0)
        assert EventType.LONDON_OPEN in events

    def test_ny_open_fires_weekday_1300(self) -> None:
        # Just before Monday 13:00
        now = _utc(2026, 7, 6, 12, 59, 30)
        fire_at, events = EventScheduler().next_events(now)
        assert fire_at == _utc(2026, 7, 6, 13, 0)
        assert EventType.NY_OPEN in events

    def test_daily_report_fires_weekday_2000(self) -> None:
        # Just before Monday 20:00
        now = _utc(2026, 7, 6, 19, 59, 30)
        fire_at, events = EventScheduler().next_events(now)
        assert fire_at == _utc(2026, 7, 6, 20, 0)
        assert EventType.DAILY_REPORT in events


class TestEventTypeEnum:
    def test_all_event_types_exist(self) -> None:
        expected = {
            "bar_close_15m",
            "market_open",
            "market_close",
            "london_open",
            "ny_open",
            "daily_report",
            "weekly_report",
        }
        actual = {e.value for e in EventType}
        assert actual == expected
