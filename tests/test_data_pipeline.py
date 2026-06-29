"""Unit tests for the Novax data pipeline.

All tests are network-free. Dukascopy downloads are avoided by constructing
synthetic .bi5 bytes directly (lzma.compress + struct.pack) and by patching
download_hour where needed.
"""

from __future__ import annotations

import lzma
import struct
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from novax.data.cleaning.normalize import ticks_to_1m_bars
from novax.data.cleaning.validation import IngestionReport, validate_day
from novax.data.ingest.dukascopy import (
    RawTick,
    fetch_day_ticks,
    parse_bi5,
)
from novax.data.loader.bar_loader import load_bars
from novax.data.storage.parquet_store import ParquetStore
from novax.data_sources import Bar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TICK_STRUCT = struct.Struct(">IIIff")
_UTC = UTC

_HOUR = datetime(2020, 3, 10, 9, tzinfo=_UTC)  # 2020-03-10 09:00 UTC


def _make_bi5(*ticks: tuple[int, int, int, float, float]) -> bytes:
    """Pack (ms_offset, ask_pts, bid_pts, ask_vol, bid_vol) tuples into LZMA .bi5."""
    raw = b"".join(_TICK_STRUCT.pack(*t) for t in ticks)
    return lzma.compress(raw)


def _make_bar(
    ts: datetime,
    price: float = 1.10000,
    *,
    spread_pips: float = 2.0,
) -> Bar:
    pip = 0.00001
    ask = price + spread_pips * pip / 2
    bid = price - spread_pips * pip / 2
    return Bar(
        ts=ts,
        open=price,
        high=price + 0.0001,
        low=price - 0.0001,
        close=price,
        volume=100.0,
        bid=bid,
        ask=ask,
        spread=ask - bid,
        source="dukascopy",
    )


# ---------------------------------------------------------------------------
# parse_bi5
# ---------------------------------------------------------------------------


class TestParseBI5:
    def test_empty_bytes_returns_empty(self) -> None:
        assert parse_bi5(b"", _HOUR) == []

    def test_single_tick_parsed_correctly(self) -> None:
        # ask=1.10000, bid=1.09990, 1 second (1000 ms) into the hour
        data = _make_bi5((1_000, 110_000, 109_990, 1.5, 0.8))
        ticks = parse_bi5(data, _HOUR)
        assert len(ticks) == 1
        t = ticks[0]
        assert t.ts == datetime(2020, 3, 10, 9, 0, 1, tzinfo=_UTC)
        assert t.ask == pytest.approx(1.10000, rel=1e-5)
        assert t.bid == pytest.approx(1.09990, rel=1e-5)
        assert t.ask_vol == pytest.approx(1.5, rel=1e-4)
        assert t.bid_vol == pytest.approx(0.8, rel=1e-4)

    def test_mid_price_property(self) -> None:
        data = _make_bi5((0, 110_000, 109_990, 1.0, 1.0))
        t = parse_bi5(data, _HOUR)[0]
        assert t.mid == pytest.approx((1.10000 + 1.09990) / 2, rel=1e-5)

    def test_multiple_ticks_correct_count(self) -> None:
        data = _make_bi5(
            (0, 110_000, 109_990, 1.0, 1.0),
            (500, 110_001, 109_991, 2.0, 2.0),
            (1_000, 110_002, 109_992, 3.0, 3.0),
        )
        ticks = parse_bi5(data, _HOUR)
        assert len(ticks) == 3
        # Timestamps must be strictly increasing.
        for i in range(1, len(ticks)):
            assert ticks[i].ts > ticks[i - 1].ts

    def test_misaligned_data_raises(self) -> None:
        # Compress 25 bytes (not a multiple of 20).
        bad = lzma.compress(b"\x00" * 25)
        with pytest.raises(ValueError, match="not a multiple of"):
            parse_bi5(bad, _HOUR)

    def test_timestamp_offset_computed_from_hour(self) -> None:
        # 60_000 ms = 1 minute from hour start.
        data = _make_bi5((60_000, 110_000, 109_990, 1.0, 1.0))
        t = parse_bi5(data, _HOUR)[0]
        assert t.ts == datetime(2020, 3, 10, 9, 1, 0, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# fetch_day_ticks (patched — no network)
# ---------------------------------------------------------------------------


class TestFetchDayTicks:
    def test_naive_date_raises(self) -> None:
        naive = datetime(2020, 1, 1)
        with pytest.raises(ValueError, match="tz-aware"):
            fetch_day_ticks("EURUSD", naive)

    def test_returns_empty_when_all_hours_404(self) -> None:
        with patch("novax.data.ingest.dukascopy.download_hour", return_value=None):
            result = fetch_day_ticks("EURUSD", datetime(2020, 1, 1, tzinfo=_UTC))
        assert result == []

    def test_aggregates_ticks_from_multiple_hours(self) -> None:
        hour0_data = _make_bi5((0, 110_000, 109_990, 1.0, 1.0))
        hour1_data = _make_bi5((0, 110_010, 110_000, 1.0, 1.0))

        def fake_download(symbol: str, hour_ts: datetime, **kwargs: object) -> bytes | None:
            if hour_ts.hour == 0:
                return hour0_data
            if hour_ts.hour == 1:
                return hour1_data
            return None

        with patch("novax.data.ingest.dukascopy.download_hour", side_effect=fake_download):
            ticks = fetch_day_ticks("EURUSD", datetime(2020, 1, 2, tzinfo=_UTC))

        assert len(ticks) == 2
        assert ticks[0].ts.hour == 0
        assert ticks[1].ts.hour == 1


# ---------------------------------------------------------------------------
# ticks_to_1m_bars
# ---------------------------------------------------------------------------


class TestTicksTo1mBars:
    def test_empty_returns_empty(self) -> None:
        assert ticks_to_1m_bars([]) == []

    def test_single_tick_single_bar(self) -> None:
        ts = datetime(2020, 1, 1, 10, 5, 30, tzinfo=_UTC)
        tick = RawTick(ts=ts, ask=1.1001, bid=1.0999, ask_vol=1.0, bid_vol=1.0)
        bars = ticks_to_1m_bars([tick])
        assert len(bars) == 1
        b = bars[0]
        # Bar timestamp truncated to minute.
        assert b.ts == datetime(2020, 1, 1, 10, 5, tzinfo=_UTC)
        assert b.open == pytest.approx(tick.mid, rel=1e-6)
        assert b.high == pytest.approx(tick.mid, rel=1e-6)
        assert b.low == pytest.approx(tick.mid, rel=1e-6)
        assert b.close == pytest.approx(tick.mid, rel=1e-6)

    def test_multiple_ticks_same_minute_ohlcv(self) -> None:
        base = datetime(2020, 1, 1, 12, 0, tzinfo=_UTC)
        ticks = [
            RawTick(ts=base.replace(second=1), ask=1.1001, bid=1.0999, ask_vol=1.0, bid_vol=1.0),
            RawTick(ts=base.replace(second=20), ask=1.1010, bid=1.1008, ask_vol=2.0, bid_vol=2.0),
            RawTick(ts=base.replace(second=50), ask=1.0995, bid=1.0993, ask_vol=3.0, bid_vol=3.0),
        ]
        bars = ticks_to_1m_bars(ticks)
        assert len(bars) == 1
        b = bars[0]
        mid0 = (1.1001 + 1.0999) / 2
        mid1 = (1.1010 + 1.1008) / 2
        mid2 = (1.0995 + 1.0993) / 2
        assert b.open == pytest.approx(mid0, rel=1e-6)
        assert b.high == pytest.approx(max(mid0, mid1, mid2), rel=1e-6)
        assert b.low == pytest.approx(min(mid0, mid1, mid2), rel=1e-6)
        assert b.close == pytest.approx(mid2, rel=1e-6)
        # Volume = sum of (ask_vol + bid_vol) / 2 per tick.
        expected_vol = (1.0 + 1.0) / 2 + (2.0 + 2.0) / 2 + (3.0 + 3.0) / 2
        assert b.volume == pytest.approx(expected_vol, rel=1e-6)

    def test_ticks_in_different_minutes_produce_separate_bars(self) -> None:
        base = datetime(2020, 1, 1, 8, 0, tzinfo=_UTC)
        ticks = [
            RawTick(
                ts=base.replace(minute=0, second=5),
                ask=1.1001,
                bid=1.0999,
                ask_vol=1.0,
                bid_vol=1.0,
            ),
            RawTick(
                ts=base.replace(minute=1, second=5),
                ask=1.1005,
                bid=1.1003,
                ask_vol=1.0,
                bid_vol=1.0,
            ),
            RawTick(
                ts=base.replace(minute=2, second=5),
                ask=1.0998,
                bid=1.0996,
                ask_vol=1.0,
                bid_vol=1.0,
            ),
        ]
        bars = ticks_to_1m_bars(ticks)
        assert len(bars) == 3
        assert bars[0].ts.minute == 0
        assert bars[1].ts.minute == 1
        assert bars[2].ts.minute == 2

    def test_bars_sorted_ascending(self) -> None:
        base = datetime(2020, 6, 1, 10, 0, tzinfo=_UTC)
        # Deliberately unsorted input.
        ticks = [
            RawTick(ts=base.replace(minute=5), ask=1.10, bid=1.09, ask_vol=1.0, bid_vol=1.0),
            RawTick(ts=base.replace(minute=2), ask=1.11, bid=1.10, ask_vol=1.0, bid_vol=1.0),
            RawTick(ts=base.replace(minute=8), ask=1.12, bid=1.11, ask_vol=1.0, bid_vol=1.0),
        ]
        bars = ticks_to_1m_bars(ticks)
        assert bars[0].ts < bars[1].ts < bars[2].ts

    def test_source_tag_is_dukascopy(self) -> None:
        ts = datetime(2020, 1, 1, 9, 0, tzinfo=_UTC)
        tick = RawTick(ts=ts, ask=1.1001, bid=1.0999, ask_vol=1.0, bid_vol=1.0)
        bars = ticks_to_1m_bars([tick])
        assert bars[0].source == "dukascopy"


# ---------------------------------------------------------------------------
# validate_day
# ---------------------------------------------------------------------------


class TestValidateDay:
    _DATE = datetime(2020, 3, 10, tzinfo=_UTC)
    _SYMBOL = "EURUSD"

    def _make_bars(self, n: int, price: float = 1.10000) -> list[Bar]:
        base = datetime(2020, 3, 10, 6, 0, tzinfo=_UTC)
        from datetime import timedelta

        return [_make_bar(base + timedelta(minutes=i), price=price) for i in range(n)]

    def test_naive_date_raises(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            validate_day(self._SYMBOL, datetime(2020, 1, 1), 0, [])

    def test_passes_with_enough_bars(self) -> None:
        bars = self._make_bars(200)
        report = validate_day(self._SYMBOL, self._DATE, len(bars) * 10, bars)
        assert report.passed is True
        assert report.bars_generated == 200

    def test_fails_with_too_few_bars(self) -> None:
        bars = self._make_bars(5)
        report = validate_day(self._SYMBOL, self._DATE, 50, bars, min_bars=100)
        assert report.passed is False
        assert any("only 5 bars" in w for w in report.warnings)

    def test_fails_with_non_positive_price(self) -> None:
        bars = self._make_bars(200)
        # Inject a bar with zero open price.
        bad_bar = Bar(
            ts=bars[0].ts,
            open=0.0,
            high=0.0001,
            low=0.0,
            close=0.00005,
            volume=1.0,
            source="dukascopy",
        )
        report = validate_day(self._SYMBOL, self._DATE, 2000, [bad_bar] + list(bars))
        assert report.passed is False
        assert any("non-positive price" in w for w in report.warnings)

    def test_spread_warning_does_not_fail(self) -> None:
        bars = self._make_bars(200)
        # Inject a bar with a 100-pip spread (above default 50-pip threshold).
        big_spread = Bar(
            ts=bars[0].ts,
            open=1.10000,
            high=1.10010,
            low=1.09990,
            close=1.10000,
            volume=1.0,
            bid=1.09500,  # 50 pips from mid
            ask=1.10500,  # 50 pips from mid => spread = 100 pips
            spread=0.01000,  # 100 pips for 5-digit FX
            source="dukascopy",
        )
        mixed = [big_spread] + list(bars[1:])
        report = validate_day(self._SYMBOL, self._DATE, 2000, mixed)
        # Spread warning is soft — should still pass if bar count is OK.
        assert report.passed is True
        assert any("spread" in w for w in report.warnings)

    def test_report_fields(self) -> None:
        bars = self._make_bars(150)
        report: IngestionReport = validate_day(
            self._SYMBOL,
            self._DATE,
            ticks_fetched=5000,
            bars=bars,
            hours_with_data=18,
        )
        assert report.symbol == self._SYMBOL
        assert report.ticks_fetched == 5000
        assert report.bars_generated == 150
        assert report.hours_with_data == 18


# ---------------------------------------------------------------------------
# ParquetStore (roundtrip)
# ---------------------------------------------------------------------------


class TestParquetStore:
    _SYMBOL = "EURUSD"
    _TF = "1m"

    def _make_bars(self, year: int, month: int, n: int = 5) -> list[Bar]:
        from datetime import timedelta

        base = datetime(year, month, 1, 8, 0, tzinfo=_UTC)
        return [_make_bar(base + timedelta(minutes=i)) for i in range(n)]

    def test_roundtrip_single_month(self, tmp_path: Path) -> None:
        store = ParquetStore(tmp_path)
        bars = self._make_bars(2020, 1, n=10)
        store.write_bars(self._SYMBOL, self._TF, bars)
        loaded = store.read_bars(self._SYMBOL, self._TF, 2020, 1)
        assert len(loaded) == 10
        for orig, back in zip(bars, loaded, strict=True):
            assert back.ts == orig.ts
            assert back.open == pytest.approx(orig.open, rel=1e-7)
            assert back.high == pytest.approx(orig.high, rel=1e-7)
            assert back.low == pytest.approx(orig.low, rel=1e-7)
            assert back.close == pytest.approx(orig.close, rel=1e-7)
            assert back.volume == pytest.approx(orig.volume, rel=1e-6)
            assert back.source == orig.source

    def test_read_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        store = ParquetStore(tmp_path)
        assert store.read_bars(self._SYMBOL, self._TF, 2025, 6) == []

    def test_write_creates_separate_files_per_month(self, tmp_path: Path) -> None:
        store = ParquetStore(tmp_path)
        jan = self._make_bars(2020, 1, n=3)
        feb = self._make_bars(2020, 2, n=3)
        store.write_bars(self._SYMBOL, self._TF, jan + feb)
        assert store.bar_path(self._SYMBOL, self._TF, 2020, 1).exists()
        assert store.bar_path(self._SYMBOL, self._TF, 2020, 2).exists()
        assert len(store.read_bars(self._SYMBOL, self._TF, 2020, 1)) == 3
        assert len(store.read_bars(self._SYMBOL, self._TF, 2020, 2)) == 3

    def test_bars_preserved_sorted(self, tmp_path: Path) -> None:
        store = ParquetStore(tmp_path)
        bars = self._make_bars(2020, 5, n=20)
        store.write_bars(self._SYMBOL, self._TF, bars)
        loaded = store.read_bars(self._SYMBOL, self._TF, 2020, 5)
        for i in range(1, len(loaded)):
            assert loaded[i].ts > loaded[i - 1].ts

    def test_optional_fields_nullable(self, tmp_path: Path) -> None:
        store = ParquetStore(tmp_path)
        # Bar without bid/ask/spread.
        ts = datetime(2020, 6, 1, 10, 0, tzinfo=_UTC)
        bar_no_spread = Bar(
            ts=ts, open=1.1, high=1.101, low=1.099, close=1.1, volume=5.0, source="dukascopy"
        )
        store.write_bars(self._SYMBOL, self._TF, [bar_no_spread])
        loaded = store.read_bars(self._SYMBOL, self._TF, 2020, 6)
        assert len(loaded) == 1
        assert loaded[0].bid is None
        assert loaded[0].ask is None
        assert loaded[0].spread is None


# ---------------------------------------------------------------------------
# load_bars (DuckDB over Parquet)
# ---------------------------------------------------------------------------


class TestLoadBars:
    _SYMBOL = "EURUSD"
    _TF = "1m"

    def _seed_store(self, tmp_path: Path, n: int = 10) -> list[Bar]:
        from datetime import timedelta

        store = ParquetStore(tmp_path)
        base = datetime(2021, 6, 1, 8, 0, tzinfo=_UTC)
        bars = [_make_bar(base + timedelta(minutes=i)) for i in range(n)]
        store.write_bars(self._SYMBOL, self._TF, bars)
        return bars

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        result = load_bars(
            tmp_path,
            self._SYMBOL,
            self._TF,
            start=datetime(2021, 6, 1, tzinfo=_UTC),
            end=datetime(2021, 6, 30, tzinfo=_UTC),
        )
        assert result == []

    def test_naive_bounds_raise(self, tmp_path: Path) -> None:
        self._seed_store(tmp_path)
        with pytest.raises(ValueError, match="tz-aware"):
            load_bars(
                tmp_path,
                self._SYMBOL,
                self._TF,
                start=datetime(2021, 6, 1),
                end=datetime(2021, 6, 30, tzinfo=_UTC),
            )

    def test_loads_all_bars_in_range(self, tmp_path: Path) -> None:
        bars = self._seed_store(tmp_path, n=10)
        result = load_bars(
            tmp_path,
            self._SYMBOL,
            self._TF,
            start=bars[0].ts,
            end=bars[-1].ts,
        )
        assert len(result) == 10

    def test_date_range_filter(self, tmp_path: Path) -> None:
        bars = self._seed_store(tmp_path, n=10)
        # Request only the first 5 bars.
        result = load_bars(
            tmp_path,
            self._SYMBOL,
            self._TF,
            start=bars[0].ts,
            end=bars[4].ts,
        )
        assert len(result) == 5
        for r, orig in zip(result, bars[:5], strict=True):
            assert r.ts == orig.ts

    def test_returned_bars_are_utc_aware(self, tmp_path: Path) -> None:
        bars = self._seed_store(tmp_path, n=3)
        result = load_bars(
            tmp_path,
            self._SYMBOL,
            self._TF,
            start=bars[0].ts,
            end=bars[-1].ts,
        )
        for b in result:
            assert b.ts.tzinfo is not None

    def test_returned_bars_sorted_ascending(self, tmp_path: Path) -> None:
        bars = self._seed_store(tmp_path, n=8)
        result = load_bars(
            tmp_path,
            self._SYMBOL,
            self._TF,
            start=bars[0].ts,
            end=bars[-1].ts,
        )
        for i in range(1, len(result)):
            assert result[i].ts > result[i - 1].ts
