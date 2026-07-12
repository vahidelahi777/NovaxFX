"""Tests for PaperTrader state machine and persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novax.data_sources import Bar
from novax.engine import Signal
from novax.live import EventKind, PaperTrader
from novax.live.signal_scanner import ScanResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 1, 8, 8, 0, tzinfo=UTC)


def _make_bar(
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
) -> Bar:
    h = high if high is not None else close + 1.0
    lo = low if low is not None else close - 1.0
    return Bar(ts=_BASE, open=close, high=h, low=lo, close=close, source="test")


def _make_scan_result(
    signal: Signal,
    *,
    sl: float | None = None,
    tp: float | None = None,
    symbol: str = "XAUUSD",
) -> ScanResult:
    return ScanResult(
        ts=_BASE,
        symbol=symbol,
        timeframe="4h",
        signal=signal,
        bos_state="idle",
        has_ob=sl is not None,
        ob_high=None,
        ob_low=None,
        prev_week_high=None,
        prev_week_low=None,
        sl=sl,
        tp=tp,
        n_bars_used=10,
    )


def _trader(tmp_path: pytest.TempPathFactory, name: str = "state.json") -> PaperTrader:
    return PaperTrader(tmp_path / name)


# ---------------------------------------------------------------------------
# FLAT cases
# ---------------------------------------------------------------------------


class TestFlatCases:
    def test_flat_to_flat_no_change(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        event = trader.update(_make_scan_result(Signal.FLAT), _make_bar(2600.0))
        assert event.kind == EventKind.NO_CHANGE
        assert trader.position.direction == "FLAT"
        assert event.pnl is None
        assert event.sl is None
        assert event.tp is None

    def test_flat_to_long_entry(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        event = trader.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        assert event.kind == EventKind.ENTRY_LONG
        assert event.signal == Signal.LONG
        assert event.price == pytest.approx(2661.5)
        assert event.sl == pytest.approx(2657.5)
        assert event.tp == pytest.approx(2669.5)
        assert event.pnl is None
        assert trader.position.direction == "LONG"
        assert trader.position.entry_price == pytest.approx(2661.5)
        assert trader.position.sl == pytest.approx(2657.5)

    def test_flat_to_short_entry(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        event = trader.update(
            _make_scan_result(Signal.SHORT, sl=2665.0, tp=2654.0),
            _make_bar(2661.5),
        )
        assert event.kind == EventKind.ENTRY_SHORT
        assert event.signal == Signal.SHORT
        assert trader.position.direction == "SHORT"
        assert trader.position.sl == pytest.approx(2665.0)
        assert trader.position.tp == pytest.approx(2654.0)

    def test_entry_saves_state_to_disk(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "state.json"
        trader = PaperTrader(path)
        trader.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        assert path.exists()


# ---------------------------------------------------------------------------
# HOLD cases
# ---------------------------------------------------------------------------


class TestHoldCases:
    def test_long_hold(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5), _make_bar(2661.5))
        prev_pnl = trader.position.cumulative_pnl
        event = trader.update(_make_scan_result(Signal.LONG), _make_bar(2662.0))
        assert event.kind == EventKind.HOLD
        assert event.signal == Signal.LONG
        assert event.pnl is None
        assert trader.position.cumulative_pnl == pytest.approx(prev_pnl)
        assert trader.position.direction == "LONG"

    def test_short_hold(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.SHORT, sl=2665.0, tp=2654.0), _make_bar(2661.5))
        event = trader.update(_make_scan_result(Signal.SHORT), _make_bar(2660.0))
        assert event.kind == EventKind.HOLD
        assert event.signal == Signal.SHORT
        assert trader.position.direction == "SHORT"

    def test_hold_preserves_stored_sl_tp(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5), _make_bar(2661.5))
        event = trader.update(_make_scan_result(Signal.LONG), _make_bar(2663.0))
        assert event.sl == pytest.approx(2657.5)
        assert event.tp == pytest.approx(2669.5)


# ---------------------------------------------------------------------------
# LONG exits
# ---------------------------------------------------------------------------


class TestLongExits:
    def _enter_long(self, trader: PaperTrader) -> None:
        trader.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )

    def test_long_exit_tp(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_long(trader)
        # bar.high=2671 >= tp=2669.5 → EXIT_TP
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2670.0, high=2671.0, low=2668.0),
        )
        assert event.kind == EventKind.EXIT_TP
        assert event.signal == Signal.FLAT
        assert event.pnl == pytest.approx(2670.0 - 2661.5)
        assert event.cumulative_pnl == pytest.approx(2670.0 - 2661.5)
        assert trader.position.direction == "FLAT"
        assert trader.position.trade_count == 1

    def test_long_exit_sl(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_long(trader)
        # bar.low=2655 <= sl=2657.5 → EXIT_SL (checked before TP)
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2656.0, high=2658.0, low=2655.0),
        )
        assert event.kind == EventKind.EXIT_SL
        assert event.pnl == pytest.approx(2656.0 - 2661.5)
        assert event.pnl < 0

    def test_long_exit_signal(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_long(trader)
        # bar doesn't breach SL (2260 > 2257.5) or TP (2263 < 2269.5) → EXIT_SIGNAL
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2662.0, high=2663.0, low=2660.0),
        )
        assert event.kind == EventKind.EXIT_SIGNAL

    def test_long_sl_takes_priority_over_tp(self, tmp_path: pytest.TempPathFactory) -> None:
        """Gap bar that breaches both SL and TP → SL wins (checked first)."""
        trader = _trader(tmp_path)
        self._enter_long(trader)
        # low=2650 <= sl=2657.5 AND high=2680 >= tp=2669.5
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2660.0, high=2680.0, low=2650.0),
        )
        assert event.kind == EventKind.EXIT_SL


# ---------------------------------------------------------------------------
# SHORT exits
# ---------------------------------------------------------------------------


class TestShortExits:
    def _enter_short(self, trader: PaperTrader) -> None:
        trader.update(
            _make_scan_result(Signal.SHORT, sl=2665.0, tp=2654.0),
            _make_bar(2661.5),
        )

    def test_short_exit_tp(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_short(trader)
        # bar.low=2651 <= tp=2654 → EXIT_TP
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2652.0, high=2655.0, low=2651.0),
        )
        assert event.kind == EventKind.EXIT_TP
        assert event.pnl == pytest.approx(2661.5 - 2652.0)
        assert event.pnl > 0

    def test_short_exit_sl(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_short(trader)
        # bar.high=2667 >= sl=2665 → EXIT_SL
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2666.0, high=2667.0, low=2664.0),
        )
        assert event.kind == EventKind.EXIT_SL
        assert event.pnl == pytest.approx(2661.5 - 2666.0)
        assert event.pnl < 0

    def test_short_exit_signal(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        self._enter_short(trader)
        # bar doesn't breach SL (high=2664 < sl=2665) or TP (low=2656 > tp=2654) → EXIT_SIGNAL
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(2660.0, high=2664.0, low=2656.0),
        )
        assert event.kind == EventKind.EXIT_SIGNAL


# ---------------------------------------------------------------------------
# Direction flip
# ---------------------------------------------------------------------------


class TestDirectionFlip:
    def test_direction_flip_long_to_short(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        # Enter LONG
        trader.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        # Flip to SHORT: should exit LONG first as EXIT_SIGNAL
        event = trader.update(
            _make_scan_result(Signal.SHORT, sl=2666.0, tp=2654.0),
            _make_bar(2663.0, high=2664.0, low=2661.0),
        )
        assert event.kind == EventKind.EXIT_SIGNAL
        assert event.signal == Signal.FLAT
        assert event.pnl == pytest.approx(2663.0 - 2661.5)
        assert trader.position.direction == "FLAT"

    def test_direction_flip_next_call_enters_new_direction(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5), _make_bar(2661.5))
        # Flip (exits LONG, saves FLAT)
        trader.update(
            _make_scan_result(Signal.SHORT, sl=2666.0, tp=2654.0),
            _make_bar(2663.0, high=2664.0, low=2661.0),
        )
        # Next call with same SHORT signal → ENTRY_SHORT
        event = trader.update(
            _make_scan_result(Signal.SHORT, sl=2666.0, tp=2654.0),
            _make_bar(2663.0),
        )
        assert event.kind == EventKind.ENTRY_SHORT
        assert trader.position.direction == "SHORT"

    def test_direction_flip_short_to_long(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.SHORT, sl=2665.0, tp=2654.0), _make_bar(2661.5))
        event = trader.update(
            _make_scan_result(Signal.LONG, sl=2658.0, tp=2670.0),
            _make_bar(2660.0, high=2661.0, low=2659.0),
        )
        assert event.kind == EventKind.EXIT_SIGNAL
        assert event.pnl == pytest.approx(2661.5 - 2660.0)
        assert trader.position.direction == "FLAT"


# ---------------------------------------------------------------------------
# None SL/TP
# ---------------------------------------------------------------------------


class TestNoneSlTp:
    def test_none_sl_tp_entry(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=None, tp=None), _make_bar(2661.5))
        assert trader.position.sl is None
        assert trader.position.tp is None

    def test_none_sl_tp_exit_always_exit_signal(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=None, tp=None), _make_bar(100.0))
        # Even if bar looks like an SL breach, no stored SL → EXIT_SIGNAL
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(80.0, high=90.0, low=75.0),
        )
        assert event.kind == EventKind.EXIT_SIGNAL


# ---------------------------------------------------------------------------
# Cumulative PnL across multiple trades
# ---------------------------------------------------------------------------


class TestCumulativePnl:
    def test_cumulative_pnl_multi_trade(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)

        # Trade 1: LONG 100→105 via EXIT_SIGNAL (bar doesn't breach SL=95 or TP=110)
        trader.update(_make_scan_result(Signal.LONG, sl=95.0, tp=110.0), _make_bar(100.0))
        trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(105.0, high=106.0, low=104.0),
        )
        assert trader.position.cumulative_pnl == pytest.approx(5.0)
        assert trader.position.trade_count == 1

        # Trade 2: SHORT 110→103 via EXIT_SIGNAL (bar doesn't breach SL=115 or TP=100)
        trader.update(_make_scan_result(Signal.SHORT, sl=115.0, tp=100.0), _make_bar(110.0))
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(103.0, high=104.0, low=102.0),
        )
        assert event.pnl == pytest.approx(7.0)
        assert event.cumulative_pnl == pytest.approx(12.0)
        assert trader.position.trade_count == 2

    def test_losing_trades_reduce_cumulative(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = _trader(tmp_path)
        trader.update(_make_scan_result(Signal.LONG, sl=95.0, tp=110.0), _make_bar(100.0))
        # SL hit: bar.low=93 <= sl=95
        event = trader.update(
            _make_scan_result(Signal.FLAT),
            _make_bar(94.0, high=96.0, low=93.0),
        )
        assert event.kind == EventKind.EXIT_SL
        assert event.cumulative_pnl == pytest.approx(94.0 - 100.0)
        assert event.cumulative_pnl < 0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_persistence_survives_restart(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "state.json"
        # First process: enter LONG
        t1 = PaperTrader(path)
        t1.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        # Second process: load same file
        t2 = PaperTrader(path)
        assert t2.position.direction == "LONG"
        assert t2.position.entry_price == pytest.approx(2661.5)
        assert t2.position.sl == pytest.approx(2657.5)
        assert t2.position.tp == pytest.approx(2669.5)

    def test_fresh_start_when_no_file(self, tmp_path: pytest.TempPathFactory) -> None:
        trader = PaperTrader(tmp_path / "does_not_exist.json")
        assert trader.position.direction == "FLAT"
        assert trader.position.cumulative_pnl == pytest.approx(0.0)

    def test_fresh_start_on_corrupt_file(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "state.json"
        path.write_text("not valid json", encoding="utf-8")
        trader = PaperTrader(path)
        assert trader.position.direction == "FLAT"

    def test_atomic_save_no_tmp_file_left(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "state.json"
        trader = PaperTrader(path)
        trader.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_atomic_save_second_trader_sees_first_write(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        path = tmp_path / "state.json"
        t1 = PaperTrader(path)
        t1.update(
            _make_scan_result(Signal.LONG, sl=2657.5, tp=2669.5),
            _make_bar(2661.5),
        )
        t2 = PaperTrader(path)
        assert t2.position.direction == "LONG"
        assert t2.position.entry_price == pytest.approx(2661.5)

    def test_cumulative_pnl_persists_across_restart(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "state.json"
        # First session: complete a trade
        t1 = PaperTrader(path)
        t1.update(_make_scan_result(Signal.LONG, sl=95.0, tp=110.0), _make_bar(100.0))
        t1.update(_make_scan_result(Signal.FLAT), _make_bar(105.0, high=106.0, low=104.0))
        # Second session: cumulative PnL is preserved
        t2 = PaperTrader(path)
        assert t2.position.cumulative_pnl == pytest.approx(5.0)
        assert t2.position.trade_count == 1
