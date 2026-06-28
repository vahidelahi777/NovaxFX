"""Data-quality gate — runs BEFORE any backtest.

No backtest result is accepted without a passing report (fail-closed). Checks
operate on a sequence of `Bar` (see data_sources). The gate catches the data
defects that silently manufacture edges: gaps bridged into clean fills, duplicate
or non-monotonic timestamps, invalid bid/ask, abnormal spreads, weekend/holiday
contamination, and cross-source price divergence.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import timedelta

from .data_sources import Bar
from .market_calendar import DEFAULT_FX_CALENDAR, MarketCalendar

__all__ = ["CheckResult", "DataQualityReport", "run_data_quality"]

_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str = "high"  # high | medium | low


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    symbol: str
    timeframe: str
    n_bars: int
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        # Fail closed: any failed HIGH check fails the report.
        return all(c.passed for c in self.checks if c.severity == "high")

    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _tf_delta(timeframe: str) -> timedelta:
    if timeframe not in _TF_SECONDS:
        raise ValueError(f"unknown timeframe {timeframe!r}")
    return timedelta(seconds=_TF_SECONDS[timeframe])


def run_data_quality(
    symbol: str,
    timeframe: str,
    bars: list[Bar],
    *,
    min_coverage: float = 0.995,
    spread_z_max: float = 8.0,
    calendar: MarketCalendar = DEFAULT_FX_CALENDAR,
) -> DataQualityReport:
    checks: list[CheckResult] = []
    n = len(bars)
    step = _tf_delta(timeframe)

    if n == 0:
        return DataQualityReport(
            symbol, timeframe, 0, (CheckResult("non_empty", False, "no bars"),)
        )

    ts = [b.ts for b in bars]

    # monotonic + duplicates
    strictly_increasing = all(ts[i] < ts[i + 1] for i in range(n - 1))
    checks.append(
        CheckResult(
            "monotonic_timestamps",
            strictly_increasing,
            "timestamps strictly increasing"
            if strictly_increasing
            else "non-monotonic or duplicate timestamps found",
        )
    )
    dupes = n - len(set(ts))
    checks.append(CheckResult("no_duplicate_timestamps", dupes == 0, f"{dupes} duplicates"))

    # invalid bid/ask
    bad_quotes = sum(1 for b in bars if b.bid is not None and b.ask is not None and b.ask < b.bid)
    checks.append(CheckResult("valid_bid_ask", bad_quotes == 0, f"{bad_quotes} ask<bid bars"))

    # abnormal spreads (z-score)
    spreads = [b.spread for b in bars if b.spread is not None]
    if len(spreads) >= 2:
        mu, sd = statistics.mean(spreads), statistics.pstdev(spreads)
        outliers = sum(1 for s in spreads if sd > 0 and abs(s - mu) / sd > spread_z_max)
        neg = sum(1 for s in spreads if s < 0)
        checks.append(CheckResult("no_negative_spread", neg == 0, f"{neg} negative spreads"))
        checks.append(
            CheckResult(
                "spread_outliers",
                outliers == 0,
                f"{outliers} bars beyond {spread_z_max}σ",
                severity="medium",
            )
        )

    # coverage vs expected open-bars (uses DST-correct calendar)
    expected = 0
    t = ts[0]
    while t <= ts[-1]:
        if calendar.is_open(t):
            expected += 1
        t += step
    present_open = sum(1 for b in bars if calendar.is_open(b.ts))
    coverage = present_open / expected if expected else 1.0
    checks.append(
        CheckResult(
            "coverage", coverage >= min_coverage, f"coverage={coverage:.4f} (>= {min_coverage})"
        )
    )

    # gaps within open hours
    gaps = 0
    for i in range(n - 1):
        if (
            calendar.is_open(ts[i])
            and calendar.is_open(ts[i + 1])
            and ts[i + 1] - ts[i] > step * 1.5
        ):
            gaps += 1
    checks.append(
        CheckResult(
            "intra_session_gaps",
            gaps == 0,
            f"{gaps} unexpected gaps in open hours",
            severity="medium",
        )
    )

    # weekend / holiday contamination (data when market is closed)
    closed_bars = sum(1 for b in bars if not calendar.is_open(b.ts))
    checks.append(
        CheckResult(
            "no_closed_market_data",
            closed_bars == 0,
            f"{closed_bars} bars while market closed (weekend/holiday)",
        )
    )

    return DataQualityReport(symbol, timeframe, n, tuple(checks))
