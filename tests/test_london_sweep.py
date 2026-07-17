"""Tests for LondonOpenSweep strategy and LondonSweepScanner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.engine import BarView, Position, Signal
from novax.live.london_sweep_scanner import LondonSweepScanner
from novax.strategies.london_sweep import LondonOpenSweep

# Base Monday date — gives clean weekday context (not strictly required by strategy)
_BASE = datetime(2024, 1, 8, tzinfo=UTC)
_H1 = timedelta(hours=1)

_FLAT = Position(direction="FLAT")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def bar(ts: datetime, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(ts=ts, open=o, high=h, low=lo, close=c)


def asian_bar(hour: int, *, base: datetime = _BASE, price: float = 2600.0) -> Bar:
    """A calm Asian-session bar (inside range)."""
    ts = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    return bar(ts, price, price + 2, price - 2, price)


def london_bar(
    hour: int,
    *,
    base: datetime = _BASE,
    o: float | None = None,
    h: float = 2600.0,
    lo: float = 2600.0,
    c: float = 2600.0,
) -> Bar:
    ts = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    return bar(ts, o if o is not None else c, h, lo, c)


def _replay(strat: LondonOpenSweep, bars: list[Bar]) -> Signal:
    sig = Signal.FLAT
    for i, _b in enumerate(bars):
        view = BarView(bars=tuple(bars[: i + 1]))
        sig = strat.on_bar(view, _FLAT)
    return sig


def _build_asian_session(
    n: int = 6,
    *,
    base: datetime = _BASE,
    high: float = 2610.0,
    low: float = 2590.0,
) -> list[Bar]:
    """Return n Asian bars (hours 0..n-1) that establish high/low."""
    bars: list[Bar] = []
    for h in range(n):
        ts = base.replace(hour=h, minute=0, second=0, microsecond=0)
        if h == 0:
            bars.append(bar(ts, 2600, high, low, 2600))
        else:
            bars.append(bar(ts, 2600, 2605, 2595, 2600))
    return bars


# ---------------------------------------------------------------------------
# Asian session — warmup
# ---------------------------------------------------------------------------


def test_asian_bars_return_flat() -> None:
    strat = LondonOpenSweep()
    for h in range(7):  # 00–06 UTC
        ts = _BASE.replace(hour=h)
        b = bar(ts, 2600, 2610, 2590, 2600)
        view = BarView(bars=(b,))
        assert strat.on_bar(view, _FLAT) == Signal.FLAT


def test_warmup_guard_insufficient_asian_bars() -> None:
    """Fewer than 5 Asian bars → no signal even in London window."""
    strat = LondonOpenSweep()
    # Only 3 Asian bars
    asian = [asian_bar(h) for h in range(3)]
    # London bar that would normally trigger SHORT
    ldn = london_bar(8, h=2615.0, lo=2595.0, c=2598.0)  # wicked above & closed below
    sig = _replay(strat, asian + [ldn])
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# London window — SHORT (bearish sweep)
# ---------------------------------------------------------------------------


def test_short_signal_on_bearish_sweep() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    # London bar wicks above asian_high (2610) and closes below it
    ldn = london_bar(8, h=2618.0, lo=2605.0, c=2607.0)
    sig = _replay(strat, asian + [ldn])
    assert sig == Signal.SHORT


def test_short_sl_tp_set() -> None:
    strat = LondonOpenSweep(sl_atr_mult=1.0, rr=2.0, atr_period=5)
    asian = _build_asian_session(high=2610.0, low=2590.0)
    ldn = london_bar(8, h=2618.0, lo=2605.0, c=2607.0)
    _replay(strat, asian + [ldn])
    assert strat._sl is not None  # noqa: SLF001
    assert strat._tp is not None  # noqa: SLF001
    # SL must be above the sweep high
    assert strat._sl > 2618.0  # noqa: SLF001
    # TP must be below entry (SHORT)
    assert strat._tp < 2607.0  # noqa: SLF001


def test_no_short_when_bar_closes_above_asian_high() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    # Wicks above, closes above — NOT a sweep rejection
    ldn = london_bar(8, h=2618.0, lo=2605.0, c=2615.0)
    sig = _replay(strat, asian + [ldn])
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# London window — LONG (bullish sweep)
# ---------------------------------------------------------------------------


def test_long_signal_on_bullish_sweep() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    # London bar wicks below asian_low (2590) and closes above it
    ldn = london_bar(8, h=2595.0, lo=2582.0, c=2593.0)
    sig = _replay(strat, asian + [ldn])
    assert sig == Signal.LONG


def test_long_sl_tp_set() -> None:
    strat = LondonOpenSweep(sl_atr_mult=1.0, rr=2.0, atr_period=5)
    asian = _build_asian_session(high=2610.0, low=2590.0)
    ldn = london_bar(8, h=2595.0, lo=2582.0, c=2593.0)
    _replay(strat, asian + [ldn])
    assert strat._sl is not None  # noqa: SLF001
    assert strat._tp is not None  # noqa: SLF001
    # SL must be below the sweep low
    assert strat._sl < 2582.0  # noqa: SLF001
    # TP must be above entry (LONG)
    assert strat._tp > 2593.0  # noqa: SLF001


def test_no_long_when_bar_closes_below_asian_low() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    # Wicks below, closes below — NOT a bullish rejection
    ldn = london_bar(8, h=2595.0, lo=2582.0, c=2585.0)
    sig = _replay(strat, asian + [ldn])
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# One signal per day
# ---------------------------------------------------------------------------


def test_signal_fires_only_once_per_day() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    ldn1 = london_bar(8, h=2618.0, lo=2605.0, c=2607.0)  # triggers SHORT
    ldn2 = london_bar(9, h=2620.0, lo=2600.0, c=2602.0)  # same day, still SHORT
    sigs = []
    for i, _b in enumerate(asian + [ldn1, ldn2]):
        bars_so_far = (asian + [ldn1, ldn2])[: i + 1]
        view = BarView(bars=tuple(bars_so_far))
        sigs.append(strat.on_bar(view, _FLAT))
    # Both London bars should return SHORT (preserves direction)
    assert sigs[-2] == Signal.SHORT
    assert sigs[-1] == Signal.SHORT


def test_reset_on_new_day() -> None:
    strat = LondonOpenSweep()
    day1 = _BASE
    day2 = _BASE + timedelta(days=1)

    # Day 1: fire SHORT
    asian1 = _build_asian_session(base=day1, high=2610.0, low=2590.0)
    ldn1 = london_bar(8, base=day1, h=2618.0, lo=2605.0, c=2607.0)
    for i, _b in enumerate(asian1 + [ldn1]):
        view = BarView(bars=tuple((asian1 + [ldn1])[: i + 1]))
        strat.on_bar(view, _FLAT)

    assert strat._signal_fired is True  # noqa: SLF001

    # Day 2: Asian bars should reset state
    asian2_bar0 = bar(day2.replace(hour=0), 2600, 2608, 2592, 2600)
    view = BarView(bars=tuple(asian1 + [ldn1, asian2_bar0]))
    strat.on_bar(view, _FLAT)
    assert strat._signal_fired is False  # noqa: SLF001


# ---------------------------------------------------------------------------
# Past London close — FLAT
# ---------------------------------------------------------------------------


def test_flat_after_london_close_hour() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    after_close = london_bar(12, h=2618.0, lo=2582.0, c=2607.0)
    sig = _replay(strat, asian + [after_close])
    assert sig == Signal.FLAT


def test_flat_outside_london_window() -> None:
    strat = LondonOpenSweep()
    asian = _build_asian_session(high=2610.0, low=2590.0)
    # Hour 6 is Asian session → FLAT; hour 12+ is after close → FLAT
    non_london = london_bar(15, h=2618.0, lo=2582.0, c=2607.0)
    sig = _replay(strat, asian + [non_london])
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# Volatility filter
# ---------------------------------------------------------------------------


def test_vol_filter_suppresses_signal() -> None:
    """ATR spike suppresses a valid sweep signal."""
    strat = LondonOpenSweep(vol_mult=1.5, vol_window=5)

    # Build many calm Asian + London bars across multiple days to prime ATR history
    all_bars: list[Bar] = []
    for day in range(4):
        base = _BASE + timedelta(days=day)
        for h in range(7):
            ts = base.replace(hour=h)
            all_bars.append(bar(ts, 2600, 2605, 2595, 2600))
        for h in range(7, 12):
            ts = base.replace(hour=h)
            all_bars.append(bar(ts, 2600, 2605, 2595, 2600))

    # Day 5: wide Asian + extreme London bar (ATR spike)
    spike_base = _BASE + timedelta(days=4)
    for h in range(7):
        ts = spike_base.replace(hour=h)
        all_bars.append(bar(ts, 2600, 2610, 2590, 2600))
    # Extreme London bar — would be a sweep, but ATR is enormous
    ts_ldn = spike_base.replace(hour=8)
    all_bars.append(bar(ts_ldn, 2600, 2700, 2500, 2607))  # 200-pt range

    sig = _replay(strat, all_bars)
    # Vol filter should suppress the signal → FLAT
    assert sig == Signal.FLAT


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_sl_atr_mult() -> None:
    with pytest.raises(ValueError, match="sl_atr_mult"):
        LondonOpenSweep(sl_atr_mult=0)


def test_invalid_rr() -> None:
    with pytest.raises(ValueError, match="rr"):
        LondonOpenSweep(rr=0)


# ---------------------------------------------------------------------------
# LondonSweepScanner
# ---------------------------------------------------------------------------


def test_scanner_flat_on_insufficient_bars() -> None:
    scanner = LondonSweepScanner("XAUUSD")
    result = scanner.scan([])
    assert result.signal == Signal.FLAT
    assert not result.confluence

    result2 = scanner.scan([asian_bar(0)])
    assert result2.signal == Signal.FLAT


def test_scanner_returns_sweep_result() -> None:
    scanner = LondonSweepScanner("XAUUSD", strategy_params={"atr_period": 5})
    asian = _build_asian_session(high=2610.0, low=2590.0)
    ldn = london_bar(8, h=2618.0, lo=2605.0, c=2607.0)
    result = scanner.scan(asian + [ldn])

    assert result.signal == Signal.SHORT
    assert result.confluence is True
    assert result.direction == Signal.SHORT
    assert result.entry_price == pytest.approx(2607.0)
    assert result.asian_high == pytest.approx(2610.0)
    assert result.asian_low == pytest.approx(2590.0)
    assert result.sl is not None
    assert result.tp is not None


def test_scanner_flat_result_fields() -> None:
    scanner = LondonSweepScanner("XAUUSD")
    result = scanner.scan([])
    assert result.symbol == "XAUUSD"
    assert result.signal == Signal.FLAT
    assert result.confluence is False
    assert result.entry_price is None
    assert result.sl is None
    assert result.tp is None


def test_scanner_is_stateless_across_calls() -> None:
    """Each call creates a fresh strategy — prior state does not leak."""
    scanner = LondonSweepScanner("XAUUSD")
    asian = _build_asian_session(high=2610.0, low=2590.0)
    ldn = london_bar(8, h=2618.0, lo=2605.0, c=2607.0)

    r1 = scanner.scan(asian + [ldn])
    assert r1.signal == Signal.SHORT

    # Second call with only calm bars — should return FLAT
    calm_bars = _build_asian_session(high=2610.0, low=2590.0)
    r2 = scanner.scan(calm_bars)
    assert r2.signal == Signal.FLAT
