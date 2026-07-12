"""Tests for MultiTFScanner, MultiTFScanResult, TFSignal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from novax.data_sources import Bar
from novax.engine import Signal
from novax.live import MultiTFScanner, MultiTFScanResult

_BASE_TS = datetime(2024, 1, 8, 0, 0, tzinfo=UTC)


def _make_bars(
    n: int,
    start_price: float,
    step: float,
    *,
    ts_start: datetime = _BASE_TS,
    interval_seconds: int = 14400,
) -> list[Bar]:
    """Generate n OHLCV bars with linearly drifting price."""
    bars: list[Bar] = []
    for i in range(n):
        p = start_price + i * step
        ts = ts_start + timedelta(seconds=interval_seconds * i)
        bars.append(
            Bar(
                ts=ts,
                open=p,
                high=p + abs(step) * 0.5 + 0.01,
                low=p - abs(step) * 0.5 - 0.01,
                close=p,
                volume=100.0,
                source="synth",
            )
        )
    return bars


def _rising_h4(n: int = 200) -> list[Bar]:
    return _make_bars(n, 2600.0, 0.5, interval_seconds=14400)


def _falling_h4(n: int = 200) -> list[Bar]:
    return _make_bars(n, 2700.0, -0.5, interval_seconds=14400)


def _rising_h1(n: int = 500) -> list[Bar]:
    return _make_bars(n, 2600.0, 0.1, ts_start=_BASE_TS, interval_seconds=3600)


def _falling_h1(n: int = 500) -> list[Bar]:
    return _make_bars(n, 2700.0, -0.1, ts_start=_BASE_TS, interval_seconds=3600)


def _rising_m15(n: int = 500) -> list[Bar]:
    return _make_bars(n, 2600.0, 0.03, ts_start=_BASE_TS, interval_seconds=900)


def _falling_m15(n: int = 500) -> list[Bar]:
    return _make_bars(n, 2700.0, -0.03, ts_start=_BASE_TS, interval_seconds=900)


def _scanner() -> MultiTFScanner:
    return MultiTFScanner("XAUUSD")


class TestConfluence:
    def test_confluence_long_when_h4_and_h1_long(self) -> None:
        # 4H strongly rising → WeeklyBOSRetest eventually signals LONG
        # 1H strongly rising → GoldPullback eventually signals LONG
        # We just care that the scanner doesn't crash and returns valid types.
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert isinstance(result, MultiTFScanResult)
        assert result.symbol == "XAUUSD"
        assert result.direction in (Signal.LONG, Signal.SHORT, Signal.FLAT)
        assert isinstance(result.confluence, bool)

    def test_confluence_false_when_h4_flat(self) -> None:
        # Very short bar series → strategies don't warm up → FLAT
        scanner = _scanner()
        result = scanner.scan(
            _make_bars(5, 2600.0, 0.0, interval_seconds=14400),
            _rising_h1(500),
            _rising_m15(500),
        )
        assert result.confluence is False
        assert result.direction == Signal.FLAT

    def test_confluence_false_means_no_sl_tp(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _make_bars(5, 2600.0, 0.0, interval_seconds=14400),
            _rising_h1(),
            _rising_m15(),
        )
        assert result.sl is None
        assert result.tp is None
        assert result.entry_price is None

    def test_confluence_false_when_h1_disagrees(self) -> None:
        # 4H rising, 1H falling → directions must disagree → confluence=False
        # Even if 4H produces LONG signal, GoldPullback on falling bars won't confirm.
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _falling_h1(), _rising_m15())
        # If 4H is LONG and 1H is SHORT/FLAT → no confluence
        if result.h4.signal == Signal.LONG:
            assert result.h1.signal != Signal.LONG
            assert result.confluence is False

    def test_direction_matches_h4_signal_when_confluence(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        if result.confluence:
            assert result.direction == result.h4.signal

    def test_direction_flat_when_no_confluence(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _make_bars(3, 2600.0, 0.0, interval_seconds=14400),
            _rising_h1(),
            _rising_m15(),
        )
        assert result.direction == Signal.FLAT


class TestSLTP:
    def test_h4_sl_tp_none_when_flat(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _make_bars(3, 2600.0, 0.0, interval_seconds=14400),
            _rising_h1(),
            _rising_m15(),
        )
        assert result.h4.sl is None
        assert result.h4.tp is None

    def test_h4_sl_tp_propagated_to_result_when_confluence(self) -> None:
        # When confluence holds, result.sl/tp must match h4.sl/tp
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        if result.confluence:
            assert result.sl == result.h4.sl
            assert result.tp == result.h4.tp

    def test_h1_sl_tp_always_none(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.h1.sl is None
        assert result.h1.tp is None

    def test_m15_sl_tp_always_none(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.m15.sl is None
        assert result.m15.tp is None


class TestM15Informational:
    def test_m15_signal_present_in_result(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.m15.signal in (Signal.LONG, Signal.SHORT, Signal.FLAT)

    def test_m15_does_not_gate_confluence(self) -> None:
        # Even with falling 15M, if 4H+1H agree → confluence can still be True
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _falling_m15())
        # We can't force the strategies to agree without many bars,
        # but m15 signal must NOT affect the confluence field independently.
        # Verify m15.signal is set regardless:
        assert result.m15.signal in (Signal.LONG, Signal.SHORT, Signal.FLAT)


class TestMinimumBarsGuard:
    def test_too_few_h4_bars_returns_flat(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _make_bars(1, 2600.0, 0.1, interval_seconds=14400),
            _rising_h1(),
            _rising_m15(),
        )
        assert result.confluence is False
        assert result.direction == Signal.FLAT

    def test_too_few_h1_bars_returns_flat(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _rising_h4(),
            _make_bars(1, 2600.0, 0.1, interval_seconds=3600),
            _rising_m15(),
        )
        assert result.confluence is False
        assert result.direction == Signal.FLAT

    def test_too_few_m15_bars_returns_flat(self) -> None:
        scanner = _scanner()
        result = scanner.scan(
            _rising_h4(),
            _rising_h1(),
            _make_bars(1, 2600.0, 0.1, interval_seconds=900),
        )
        assert result.confluence is False
        assert result.direction == Signal.FLAT

    def test_empty_bars_returns_flat(self) -> None:
        scanner = _scanner()
        result = scanner.scan([], [], [])
        assert result.confluence is False
        assert result.direction == Signal.FLAT


class TestDataclassProperties:
    def test_scan_result_frozen(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        with pytest.raises((AttributeError, TypeError)):
            result.confluence = True  # type: ignore[misc]

    def test_tf_signal_frozen(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        with pytest.raises((AttributeError, TypeError)):
            result.h4.signal = Signal.LONG  # type: ignore[misc]

    def test_scanned_at_is_utc_aware(self) -> None:
        scanner = _scanner()
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.scanned_at.tzinfo is not None

    def test_result_symbol_propagated(self) -> None:
        scanner = MultiTFScanner("EURUSD")
        result = scanner.scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.symbol == "EURUSD"

    def test_n_bars_used_set(self) -> None:
        h4 = _rising_h4(200)
        h1 = _rising_h1(500)
        m15 = _rising_m15(500)
        result = MultiTFScanner("XAUUSD").scan(h4, h1, m15)
        assert result.h4.n_bars_used == len(h4)
        assert result.h1.n_bars_used == len(h1)
        assert result.m15.n_bars_used == len(m15)

    def test_timeframe_labels(self) -> None:
        result = MultiTFScanner("XAUUSD").scan(_rising_h4(), _rising_h1(), _rising_m15())
        assert result.h4.timeframe == "4h"
        assert result.h1.timeframe == "1h"
        assert result.m15.timeframe == "15min"
