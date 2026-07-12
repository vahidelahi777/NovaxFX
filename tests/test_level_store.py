"""Tests for LevelStore (JSONL append-only store)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novax.live.level_store import LevelStore, SignalRecord, WeeklyLevel


@pytest.fixture()
def store(tmp_path: Path) -> LevelStore:
    return LevelStore(tmp_path / "test_levels.jsonl")


class TestWeeklyLevelAppendLoad:
    def test_append_and_load_one(self, store: LevelStore) -> None:
        rec = WeeklyLevel(
            week_start="2026-07-06",
            symbol="XAUUSD",
            prev_high=2750.0,
            prev_low=2680.0,
            week_high=None,
            week_low=None,
            recorded_at="2026-07-12T22:00:00+00:00",
        )
        store.append_level(rec)
        loaded = store.load_levels()
        assert len(loaded) == 1
        assert loaded[0].symbol == "XAUUSD"
        assert loaded[0].prev_high == pytest.approx(2750.0)

    def test_multiple_levels_preserved(self, store: LevelStore) -> None:
        for i in range(5):
            store.append_level(
                WeeklyLevel(
                    week_start=f"2026-0{i+1}-01",
                    symbol="XAUUSD",
                    prev_high=2700.0 + i,
                    prev_low=2600.0 + i,
                    week_high=None,
                    week_low=None,
                    recorded_at="2026-07-12T00:00:00+00:00",
                )
            )
        assert len(store.load_levels()) == 5

    def test_none_fields_survive_roundtrip(self, store: LevelStore) -> None:
        rec = WeeklyLevel(
            week_start="2026-07-06",
            symbol="XAUUSD",
            prev_high=None,
            prev_low=None,
            week_high=2760.0,
            week_low=2690.0,
            recorded_at="2026-07-11T21:00:00+00:00",
        )
        store.append_level(rec)
        loaded = store.load_levels()[0]
        assert loaded.prev_high is None
        assert loaded.week_high == pytest.approx(2760.0)


class TestSignalRecordAppendLoad:
    def test_append_and_load_signal(self, store: LevelStore) -> None:
        rec = SignalRecord(
            ts="2026-07-12T08:15:00+00:00",
            symbol="XAUUSD",
            h4_signal="LONG",
            h1_signal="LONG",
            m15_signal="FLAT",
            confluence=True,
            entry_price=2725.5,
            sl=2700.0,
            tp=2751.0,
            source="15m_scan",
        )
        store.append_signal(rec)
        loaded = store.load_signals()
        assert len(loaded) == 1
        assert loaded[0].confluence is True
        assert loaded[0].source == "15m_scan"
        assert loaded[0].entry_price == pytest.approx(2725.5)

    def test_level_and_signal_in_same_file(self, store: LevelStore) -> None:
        store.append_level(
            WeeklyLevel("2026-07-06", "XAUUSD", 2750.0, 2680.0, None, None, "ts")
        )
        store.append_signal(
            SignalRecord(
                "ts2", "XAUUSD", "SHORT", "FLAT", "SHORT", False, None, None, None, "daily"
            )
        )
        assert len(store.load_levels()) == 1
        assert len(store.load_signals()) == 1

    def test_load_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        s = LevelStore(tmp_path / "nonexistent.jsonl")
        assert s.load_levels() == []
        assert s.load_signals() == []


class TestFileFormat:
    def test_each_record_is_one_line(self, store: LevelStore, tmp_path: Path) -> None:
        store.append_level(
            WeeklyLevel("2026-07-06", "XAUUSD", 2750.0, 2680.0, None, None, "ts")
        )
        store.append_signal(
            SignalRecord(
                "ts", "XAUUSD", "LONG", "LONG", "LONG", True, 2725.0, 2700.0, 2775.0, "15m_scan"
            )
        )
        path = tmp_path / "test_levels.jsonl"
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "_type" in obj

    def test_corrupt_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.jsonl"
        path.write_text('{"_type": "level", "week_start": "2026-07-06", "symbol": "X", '
                        '"prev_high": 1.0, "prev_low": 0.5, "week_high": null, '
                        '"week_low": null, "recorded_at": "ts"}\n'
                        'NOT JSON\n')
        s = LevelStore(path)
        levels = s.load_levels()
        assert len(levels) == 1   # corrupt line silently skipped

    def test_parent_dir_created_if_missing(self, tmp_path: Path) -> None:
        s = LevelStore(tmp_path / "subdir" / "nested" / "store.jsonl")
        s.append_level(
            WeeklyLevel("2026-07-06", "XAUUSD", 2750.0, 2680.0, None, None, "ts")
        )
        assert (tmp_path / "subdir" / "nested" / "store.jsonl").exists()
