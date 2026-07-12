"""Tests for TradeJournal, CompletedTrade, and compute_performance."""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from novax.engine import Signal
from novax.live import CompletedTrade, EventKind, PaperEvent, TradeJournal, compute_performance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY_TS = datetime(2024, 1, 8, 8, 0, tzinfo=UTC)
_EXIT_TS = datetime(2024, 1, 8, 16, 0, tzinfo=UTC)  # +8h = 2 H4 bars


def _make_exit_event(
    pnl: float,
    *,
    kind: EventKind = EventKind.EXIT_SIGNAL,
    price: float = 100.0,
    ts: datetime = _EXIT_TS,
) -> PaperEvent:
    return PaperEvent(
        kind=kind,
        ts=ts,
        symbol="XAUUSD",
        signal=Signal.FLAT,
        price=price,
        sl=None,
        tp=None,
        pnl=pnl,
        cumulative_pnl=pnl,
    )


def _make_trade(
    pnl: float,
    *,
    symbol: str = "XAUUSD",
    direction: str = "LONG",
    exit_kind: str = "EXIT_SIGNAL",
    entry_ts: datetime = _ENTRY_TS,
    exit_ts: datetime = _EXIT_TS,
) -> CompletedTrade:
    return CompletedTrade(
        symbol=symbol,
        direction=direction,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=100.0,
        exit_price=100.0 + pnl if direction == "LONG" else 100.0 - pnl,
        sl_at_entry=None,
        tp_at_entry=None,
        exit_kind=exit_kind,
        pnl=pnl,
        n_bars_held=2,
    )


def _record(
    journal: TradeJournal,
    pnl: float,
    *,
    direction: str = "LONG",
    kind: EventKind = EventKind.EXIT_SIGNAL,
    entry_ts: str = _ENTRY_TS.isoformat(),
    exit_ts: datetime = _EXIT_TS,
) -> CompletedTrade:
    return journal.record_exit(
        symbol="XAUUSD",
        direction=direction,
        entry_price=100.0,
        entry_ts=entry_ts,
        sl_at_entry=None,
        tp_at_entry=None,
        exit_event=_make_exit_event(pnl, kind=kind, ts=exit_ts),
    )


# ---------------------------------------------------------------------------
# TradeJournal — record_exit and load
# ---------------------------------------------------------------------------


class TestTradeJournalRecord:
    def test_record_exit_long_appends_jsonl(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "journal.jsonl")
        trade = _record(journal, pnl=8.5, direction="LONG")
        trades = journal.load()
        assert len(trades) == 1
        t = trades[0]
        assert t.symbol == "XAUUSD"
        assert t.direction == "LONG"
        assert t.pnl == pytest.approx(8.5)
        assert t.exit_kind == "EXIT_SIGNAL"
        assert t.entry_ts == _ENTRY_TS
        assert t.exit_ts == _EXIT_TS
        assert trade == t

    def test_record_exit_short(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "journal.jsonl")
        _record(journal, pnl=5.0, direction="SHORT")
        t = journal.load()[0]
        assert t.direction == "SHORT"
        assert t.pnl == pytest.approx(5.0)

    def test_multiple_trades_appended_in_order(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "journal.jsonl")
        pnls = [10.0, -5.0, 7.5]
        for p in pnls:
            _record(journal, pnl=p)
        trades = journal.load()
        assert len(trades) == 3
        for i, t in enumerate(trades):
            assert t.pnl == pytest.approx(pnls[i])

    def test_load_empty_when_no_file(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "does_not_exist.jsonl")
        assert journal.load() == []

    def test_load_skips_corrupt_lines(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "journal.jsonl"
        journal = TradeJournal(path)
        _record(journal, pnl=3.0)
        # inject a corrupt line between two valid records
        with path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
        _record(journal, pnl=7.0)
        trades = journal.load()
        assert len(trades) == 2
        assert trades[0].pnl == pytest.approx(3.0)
        assert trades[1].pnl == pytest.approx(7.0)

    def test_n_bars_held_computed(self, tmp_path: pytest.TempPathFactory) -> None:
        # entry 08:00, exit 16:00 → 8h = 2 × H4 bars
        journal = TradeJournal(tmp_path / "journal.jsonl")
        trade = _record(
            journal,
            pnl=5.0,
            entry_ts=_ENTRY_TS.isoformat(),
            exit_ts=_EXIT_TS,
        )
        assert trade.n_bars_held == 2

    def test_none_sl_tp_serialised_as_null(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "journal.jsonl")
        journal.record_exit(
            symbol="XAUUSD",
            direction="LONG",
            entry_price=100.0,
            entry_ts=_ENTRY_TS.isoformat(),
            sl_at_entry=None,
            tp_at_entry=None,
            exit_event=_make_exit_event(5.0),
        )
        t = journal.load()[0]
        assert t.sl_at_entry is None
        assert t.tp_at_entry is None

    def test_sl_tp_round_trip(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "journal.jsonl")
        journal.record_exit(
            symbol="XAUUSD",
            direction="LONG",
            entry_price=2661.5,
            entry_ts=_ENTRY_TS.isoformat(),
            sl_at_entry=2657.5,
            tp_at_entry=2669.5,
            exit_event=_make_exit_event(8.5, kind=EventKind.EXIT_TP),
        )
        t = journal.load()[0]
        assert t.sl_at_entry == pytest.approx(2657.5)
        assert t.tp_at_entry == pytest.approx(2669.5)
        assert t.exit_kind == "EXIT_TP"

    def test_file_created_in_nested_dir(self, tmp_path: pytest.TempPathFactory) -> None:
        journal = TradeJournal(tmp_path / "a" / "b" / "c" / "journal.jsonl")
        _record(journal, pnl=1.0)
        assert len(journal.load()) == 1

    def test_exit_ts_preserved_in_round_trip(self, tmp_path: pytest.TempPathFactory) -> None:
        custom_ts = datetime(2024, 3, 15, 20, 0, tzinfo=UTC)
        journal = TradeJournal(tmp_path / "journal.jsonl")
        _record(journal, pnl=2.0, exit_ts=custom_ts)
        assert journal.load()[0].exit_ts == custom_ts


# ---------------------------------------------------------------------------
# compute_performance
# ---------------------------------------------------------------------------


class TestComputePerformanceEmpty:
    def test_compute_performance_empty(self) -> None:
        report = compute_performance([], symbol="XAUUSD", timeframe="4h")
        assert report.trade_count == 0
        assert report.win_count == 0
        assert math.isnan(report.win_rate)
        assert math.isnan(report.avg_pnl)
        assert math.isnan(report.profit_factor)
        assert math.isnan(report.sharpe_ratio)
        assert report.total_pnl == pytest.approx(0.0)
        assert report.max_drawdown_abs == pytest.approx(0.0)
        assert report.first_trade_ts is None
        assert report.last_trade_ts is None


class TestComputePerformanceSingleTrade:
    def test_compute_performance_single_win(self) -> None:
        report = compute_performance([_make_trade(10.0)], symbol="XAUUSD", timeframe="4h")
        assert report.trade_count == 1
        assert report.win_count == 1
        assert report.win_rate == pytest.approx(1.0)
        assert report.total_pnl == pytest.approx(10.0)
        assert math.isinf(report.profit_factor) and report.profit_factor > 0
        assert math.isnan(report.sharpe_ratio)

    def test_compute_performance_single_loss(self) -> None:
        report = compute_performance([_make_trade(-8.0)], symbol="XAUUSD", timeframe="4h")
        assert report.trade_count == 1
        assert report.win_count == 0
        assert report.win_rate == pytest.approx(0.0)
        assert report.total_pnl == pytest.approx(-8.0)
        assert report.profit_factor == pytest.approx(0.0)
        assert math.isnan(report.sharpe_ratio)


class TestComputePerformanceMixed:
    def test_compute_performance_mixed(self) -> None:
        # 2 wins (+10, +5) and 1 loss (−8)
        trades = [_make_trade(10.0), _make_trade(5.0), _make_trade(-8.0)]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")

        assert report.trade_count == 3
        assert report.win_count == 2
        assert report.win_rate == pytest.approx(2 / 3)
        assert report.total_pnl == pytest.approx(7.0)
        assert report.avg_pnl == pytest.approx(7 / 3)
        assert report.profit_factor == pytest.approx(15 / 8)
        # cumulative: 10→15→7; peak=15, trough=7, dd=8
        assert report.max_drawdown_abs == pytest.approx(8.0)
        # Sharpe: mean / sample_std of [10, 5, -8]
        expected_sharpe = statistics.mean([10.0, 5.0, -8.0]) / statistics.stdev([10.0, 5.0, -8.0])
        assert report.sharpe_ratio == pytest.approx(expected_sharpe)

    def test_max_drawdown_abs(self) -> None:
        # Equity curve: +10, −15, +8, −5
        # cumulative: 10, −5, 3, −2
        # peak tracks: 10, 10, 10, 10
        # dd from peak: 0, 15, 7, 12 → max_dd = 15
        trades = [
            _make_trade(10.0),
            _make_trade(-15.0),
            _make_trade(8.0),
            _make_trade(-5.0),
        ]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")
        assert report.max_drawdown_abs == pytest.approx(15.0)

    def test_exit_counts(self) -> None:
        trades = [
            _make_trade(5.0, exit_kind="EXIT_TP"),
            _make_trade(3.0, exit_kind="EXIT_TP"),
            _make_trade(-4.0, exit_kind="EXIT_SL"),
        ]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")
        assert report.exit_counts == {"EXIT_TP": 2, "EXIT_SL": 1}

    def test_profit_factor_no_losses(self) -> None:
        trades = [_make_trade(5.0), _make_trade(3.0), _make_trade(8.0)]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")
        assert math.isinf(report.profit_factor) and report.profit_factor > 0

    def test_profit_factor_no_wins(self) -> None:
        trades = [_make_trade(-5.0), _make_trade(-3.0)]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")
        assert report.profit_factor == pytest.approx(0.0)

    def test_first_last_trade_ts(self) -> None:
        ts1 = datetime(2024, 1, 8, 8, 0, tzinfo=UTC)
        ts2 = datetime(2024, 2, 8, 8, 0, tzinfo=UTC)
        ts3 = datetime(2024, 3, 8, 8, 0, tzinfo=UTC)
        trades = [
            _make_trade(5.0, entry_ts=ts1, exit_ts=ts1 + timedelta(hours=8)),
            _make_trade(-2.0, entry_ts=ts2, exit_ts=ts2 + timedelta(hours=8)),
            _make_trade(7.0, entry_ts=ts3, exit_ts=ts3 + timedelta(hours=8)),
        ]
        report = compute_performance(trades, symbol="XAUUSD", timeframe="4h")
        assert report.first_trade_ts == ts1
        assert report.last_trade_ts == ts3 + timedelta(hours=8)

    def test_metadata_propagated(self) -> None:
        report = compute_performance(
            [_make_trade(1.0)], symbol="EURUSD", timeframe="1h"
        )
        assert report.symbol == "EURUSD"
        assert report.timeframe == "1h"
