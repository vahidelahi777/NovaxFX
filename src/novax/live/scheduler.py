"""Bar-close schedulers using epoch-modular arithmetic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

__all__ = ["BarScheduler", "H4BarScheduler"]

_H4_SECONDS = 4 * 3600  # 14 400
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class H4BarScheduler:
    """Computes when the next H4 bar closes relative to UTC midnight epoch."""

    @staticmethod
    def next_bar_close(now: datetime) -> datetime:
        """Return the UTC datetime of the next H4 bar close strictly after *now*.

        Raises ValueError for naive datetimes.
        """
        if now.tzinfo is None:
            raise ValueError("now must be tz-aware (got naive datetime)")
        now_utc = now.astimezone(UTC)
        elapsed = (now_utc - _EPOCH).total_seconds()
        remainder = elapsed % _H4_SECONDS
        seconds_to_next = _H4_SECONDS - remainder
        return now_utc + timedelta(seconds=seconds_to_next)

    @staticmethod
    def seconds_until_next(now: datetime) -> float:
        """Return seconds until the next H4 bar close (always > 0)."""
        return (H4BarScheduler.next_bar_close(now) - now.astimezone(UTC)).total_seconds()


class BarScheduler:
    """Generic epoch-aligned bar-close scheduler for any fixed interval.

    Args:
        interval_seconds: Bar width in seconds. Must be a positive multiple of 60.
                          Common values: 900 (15m), 3600 (1h), 14400 (4h).
    """

    def __init__(self, interval_seconds: int) -> None:
        if interval_seconds < 60 or interval_seconds % 60 != 0:
            raise ValueError(
                f"interval_seconds must be a positive multiple of 60, got {interval_seconds}"
            )
        self._interval = interval_seconds

    def next_bar_close(self, now: datetime) -> datetime:
        """Return the UTC datetime of the next bar close strictly after *now*.

        Raises ValueError for naive datetime.
        """
        if now.tzinfo is None:
            raise ValueError("now must be tz-aware (got naive datetime)")
        now_utc = now.astimezone(UTC)
        elapsed = (now_utc - _EPOCH).total_seconds()
        remainder = elapsed % self._interval
        seconds_to_next = self._interval - remainder
        return now_utc + timedelta(seconds=seconds_to_next)

    def seconds_until_next(self, now: datetime) -> float:
        """Return seconds until the next bar close (always > 0)."""
        return (self.next_bar_close(now) - now.astimezone(UTC)).total_seconds()
