"""Tests for Tehran timezone display utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from novax.live.tz_utils import TEHRAN, fmt_both, fmt_tehran, fmt_utc


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class TestFmtUtc:
    def test_basic_format(self) -> None:
        dt = _utc(2026, 7, 14, 0, 15)
        assert fmt_utc(dt) == "2026-07-14 00:15 UTC"

    def test_midnight(self) -> None:
        dt = _utc(2026, 1, 1, 0, 0)
        assert fmt_utc(dt) == "2026-01-01 00:00 UTC"

    def test_converts_non_utc_input(self) -> None:
        # UTC+3:30 input → displayed as UTC
        irst = timezone(timedelta(hours=3, minutes=30))
        dt = datetime(2026, 7, 14, 3, 45, tzinfo=irst)
        assert fmt_utc(dt) == "2026-07-14 00:15 UTC"


class TestFmtTehran:
    def test_offset_3h30m(self) -> None:
        # 00:15 UTC → 03:45 IRST
        dt = _utc(2026, 7, 14, 0, 15)
        result = fmt_tehran(dt)
        assert result == "2026-07-14 03:45 IRST"

    def test_always_irst_label(self) -> None:
        # Iran does not observe DST — always IRST regardless of date
        for month in [1, 4, 7, 10]:
            dt = _utc(2026, month, 15, 12, 0)
            assert fmt_tehran(dt).endswith("IRST"), f"month={month} should be IRST"

    def test_midnight_utc_is_0330_tehran(self) -> None:
        dt = _utc(2026, 3, 10, 0, 0)
        result = fmt_tehran(dt)
        assert "03:30 IRST" in result

    def test_date_rollover(self) -> None:
        # 22:00 UTC → 01:30 IRST next day
        dt = _utc(2026, 7, 13, 22, 0)
        result = fmt_tehran(dt)
        assert "2026-07-14" in result
        assert "01:30 IRST" in result


class TestFmtBoth:
    def test_format_structure(self) -> None:
        dt = _utc(2026, 7, 14, 0, 15)
        result = fmt_both(dt)
        assert result == "2026-07-14 00:15 UTC / 03:45 IRST"

    def test_contains_utc_and_irst(self) -> None:
        dt = _utc(2026, 1, 5, 8, 0)
        result = fmt_both(dt)
        assert "UTC" in result
        assert "IRST" in result

    def test_separator_slash(self) -> None:
        dt = _utc(2026, 7, 14, 13, 0)
        result = fmt_both(dt)
        assert " / " in result

    def test_sunday_market_open(self) -> None:
        # Sunday 22:00 UTC → Monday 01:30 IRST
        dt = _utc(2026, 7, 12, 22, 0)
        result = fmt_both(dt)
        assert "22:00 UTC" in result
        assert "01:30 IRST" in result


class TestTehranZoneObject:
    def test_tehran_is_zoneinfo(self) -> None:
        from zoneinfo import ZoneInfo
        assert isinstance(TEHRAN, ZoneInfo)

    def test_offset_is_3h30(self) -> None:
        dt = _utc(2026, 7, 14, 0, 0)
        teh = dt.astimezone(TEHRAN)
        offset = teh.utcoffset()
        assert offset == timedelta(hours=3, minutes=30)
