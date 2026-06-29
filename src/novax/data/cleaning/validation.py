"""Ingestion quality report and validation for a single day of bar data."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ...data_sources import Bar

__all__ = ["IngestionReport", "validate_day"]

_MIN_BARS_DEFAULT = 100
_MAX_SPREAD_PIPS_DEFAULT = 50.0


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """Data quality summary for one instrument-day of ingestion."""

    symbol: str
    date: datetime  # UTC midnight of the day
    ticks_fetched: int
    bars_generated: int
    hours_with_data: int
    passed: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def validate_day(
    symbol: str,
    date: datetime,
    ticks_fetched: int,
    bars: Sequence[Bar],
    *,
    hours_with_data: int = 0,
    min_bars: int = _MIN_BARS_DEFAULT,
    max_spread_pips: float = _MAX_SPREAD_PIPS_DEFAULT,
) -> IngestionReport:
    """Validate a single day of bar data and return an IngestionReport.

    Hard checks (cause passed=False):
      1. Bar count must meet min_bars.
      2. No non-positive prices (open/high/low/close > 0).

    Soft checks (add a warning but do not fail):
      3. Spread per bar must be below max_spread_pips.

    Args:
        symbol: Instrument symbol, e.g. "EURUSD".
        date: UTC midnight of the day being validated (must be tz-aware).
        ticks_fetched: Total tick count for the day (for reporting only).
        bars: 1-minute bars generated from the ticks.
        hours_with_data: How many of the 24 hourly files were non-empty (404-skipped).
        min_bars: Minimum acceptable bar count; below this the day fails.
        max_spread_pips: Spread threshold (in pips) above which a warning is emitted.

    Raises:
        ValueError: If date is not tz-aware.
    """
    if date.tzinfo is None:
        raise ValueError("date must be tz-aware UTC")

    n = len(bars)
    warnings: list[str] = []
    passed = True

    # Hard check 1: minimum bar count.
    if n < min_bars:
        passed = False
        warnings.append(
            f"only {n} bars generated (min_bars={min_bars}); "
            "day may be a weekend, holiday, or have a data gap"
        )

    # Hard check 2: no non-positive prices.
    for bar in bars:
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            passed = False
            warnings.append(f"non-positive price at {bar.ts.isoformat()}")
            break

    # Soft check 3: spread reasonableness (warns only).
    pip_size = _pip_size_heuristic(symbol)
    if pip_size > 0:
        for bar in bars:
            if bar.spread is not None and bar.spread / pip_size > max_spread_pips:
                warnings.append(
                    f"spread {bar.spread / pip_size:.1f} pips at {bar.ts.isoformat()} "
                    f"exceeds max_spread_pips={max_spread_pips}"
                )
                break

    return IngestionReport(
        symbol=symbol,
        date=date,
        ticks_fetched=ticks_fetched,
        bars_generated=n,
        hours_with_data=hours_with_data,
        passed=passed,
        warnings=tuple(warnings),
    )


def _pip_size_heuristic(symbol: str) -> float:
    """Rough pip-size estimate from symbol name for spread sanity checks only."""
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    if "XAU" in s or "GOLD" in s:
        return 0.1
    if "XAG" in s or "SILVER" in s:
        return 0.01
    return 0.00001  # standard 5-digit FX (EURUSD, GBPUSD, etc.)
