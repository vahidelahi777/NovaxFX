"""Unit tests for the Twelve Data ingestion adapter.

All tests are network-free — urllib.request.urlopen is patched throughout.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from novax.data.ingest.twelvedata import _parse_dt, fetch_bars

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = datetime(2024, 1, 5, 0, 0, tzinfo=UTC)
_END = datetime(2024, 1, 5, 23, 59, tzinfo=UTC)
_API_KEY = "test_key_not_real"
_INTERVAL = "4h"

_SAMPLE_VALUES = [
    {
        "datetime": "2024-01-05 16:00:00",
        "open": "1.09500",
        "high": "1.09600",
        "low": "1.09400",
        "close": "1.09550",
    },
    {
        "datetime": "2024-01-05 12:00:00",
        "open": "1.09400",
        "high": "1.09550",
        "low": "1.09350",
        "close": "1.09500",
    },
    {
        "datetime": "2024-01-05 08:00:00",
        "open": "1.09300",
        "high": "1.09450",
        "low": "1.09250",
        "close": "1.09400",
    },
]

_OK_RESPONSE = {
    "meta": {"symbol": "EUR/USD", "interval": "4h"},
    "values": _SAMPLE_VALUES,
    "status": "ok",
}
_EMPTY_RESPONSE = {"meta": {}, "values": [], "status": "ok"}
_ERROR_RESPONSE = {
    "status": "error",
    "message": "No data is available on the specified dates.",
    "code": 404,
}


def _mock_urlopen(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _patched(payload: dict) -> MagicMock:
    return patch(
        "novax.data.ingest.twelvedata.urllib.request.urlopen",
        return_value=_mock_urlopen(payload),
    )


# ---------------------------------------------------------------------------
# _parse_dt
# ---------------------------------------------------------------------------


class TestParseDt:
    def test_intraday_format(self) -> None:
        dt = _parse_dt("2024-01-05 16:00:00")
        assert dt == datetime(2024, 1, 5, 16, 0, 0, tzinfo=UTC)
        assert dt.tzinfo is UTC

    def test_daily_format(self) -> None:
        dt = _parse_dt("2024-01-05")
        assert dt == datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
        assert dt.tzinfo is UTC


# ---------------------------------------------------------------------------
# fetch_bars — happy path
# ---------------------------------------------------------------------------


class TestFetchBarsHappyPath:
    def test_returns_bars_sorted_oldest_first(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert len(bars) == 3
        assert bars[0].ts < bars[1].ts < bars[2].ts

    def test_source_field_is_twelvedata(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert all(b.source == "twelvedata" for b in bars)

    def test_ohlc_values_parsed_correctly(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        oldest = bars[0]
        assert oldest.open == pytest.approx(1.09300)
        assert oldest.high == pytest.approx(1.09450)
        assert oldest.low == pytest.approx(1.09250)
        assert oldest.close == pytest.approx(1.09400)

    def test_volume_is_zero(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert all(b.volume == 0.0 for b in bars)

    def test_bid_ask_synthesized_from_pip_size(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY, nominal_spread_pips=2.0)
        for b in bars:
            assert b.spread is not None
            assert b.bid is not None
            assert b.ask is not None
            # EUR/USD pip_size=0.0001, 2 pips spread
            assert b.spread == pytest.approx(2 * 0.0001)
            assert b.ask == pytest.approx(b.close + 0.0001)
            assert b.bid == pytest.approx(b.close - 0.0001)

    def test_ask_greater_than_bid(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        for b in bars:
            assert b.ask is not None and b.bid is not None
            assert b.ask > b.bid

    def test_timestamps_are_utc(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        for b in bars:
            assert b.ts.tzinfo is not None

    def test_empty_response_returns_empty_list(self) -> None:
        with _patched(_EMPTY_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert bars == []

    def test_accepts_compact_symbol(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert len(bars) == 3

    def test_accepts_canonical_symbol(self) -> None:
        with _patched(_OK_RESPONSE):
            bars = fetch_bars("EUR/USD", _INTERVAL, _START, _END, _API_KEY)
        assert len(bars) == 3

    def test_ohlc_clamped_when_close_exceeds_high(self) -> None:
        # Twelve Data rounding artefact: close > reported high (seen in live data 2025-01-14)
        values = [
            {
                "datetime": "2024-01-05 12:00:00",  # within _START/_END range
                "open": "1.02539",
                "high": "1.02961",
                "low": "1.02392",
                "close": "1.03000",  # close > high — would fail Bar validation without clamp
            }
        ]
        payload = {"values": values, "status": "ok"}
        with _patched(payload):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert len(bars) == 1
        b = bars[0]
        assert b.high >= b.close
        assert b.high >= b.open
        assert b.low <= b.close
        assert b.low <= b.open
        assert b.high == pytest.approx(1.03000)  # expanded to close

    def test_xauusd_spread_uses_metal_pip_size(self) -> None:
        xau_values = [
            {
                "datetime": "2024-01-05 12:00:00",
                "open": "2050.00",
                "high": "2055.00",
                "low": "2045.00",
                "close": "2052.00",
            }
        ]
        payload = {"values": xau_values, "status": "ok"}
        with _patched(payload):
            bars = fetch_bars("XAU/USD", _INTERVAL, _START, _END, _API_KEY, nominal_spread_pips=2.0)
        assert len(bars) == 1
        # XAU/USD pip_size = 0.1 → 2 pips spread = 0.2
        assert bars[0].spread == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# fetch_bars — error handling
# ---------------------------------------------------------------------------


class TestFetchBarsErrors:
    def test_api_error_response_raises_runtime_error(self) -> None:
        with _patched(_ERROR_RESPONSE), pytest.raises(RuntimeError, match="Twelve Data error"):
            fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)

    def test_naive_start_raises_value_error(self) -> None:
        naive = datetime(2024, 1, 5, 0, 0)
        with pytest.raises(ValueError, match="tz-aware"):
            fetch_bars("EURUSD", _INTERVAL, naive, _END, _API_KEY)

    def test_naive_end_raises_value_error(self) -> None:
        naive = datetime(2024, 1, 5, 23, 59)
        with pytest.raises(ValueError, match="tz-aware"):
            fetch_bars("EURUSD", _INTERVAL, _START, naive, _API_KEY)

    def test_unknown_symbol_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="unknown instrument"):
            fetch_bars("FAKEFX", _INTERVAL, _START, _END, _API_KEY)


# ---------------------------------------------------------------------------
# fetch_bars — out-of-range filtering and deduplication
# ---------------------------------------------------------------------------


class TestFetchBarsFiltering:
    def test_bars_outside_range_excluded(self) -> None:
        values = [
            # within range
            {
                "datetime": "2024-01-05 12:00:00",
                "open": "1.09400",
                "high": "1.09550",
                "low": "1.09350",
                "close": "1.09500",
            },
            # outside range (before start)
            {
                "datetime": "2024-01-04 20:00:00",
                "open": "1.09000",
                "high": "1.09100",
                "low": "1.08900",
                "close": "1.09050",
            },
        ]
        payload = {"values": values, "status": "ok"}
        narrow_start = datetime(2024, 1, 5, 0, 0, tzinfo=UTC)
        narrow_end = datetime(2024, 1, 5, 23, 59, tzinfo=UTC)
        with _patched(payload):
            bars = fetch_bars("EURUSD", _INTERVAL, narrow_start, narrow_end, _API_KEY)
        assert len(bars) == 1
        assert bars[0].ts == datetime(2024, 1, 5, 12, 0, tzinfo=UTC)

    def test_duplicate_timestamps_deduplicated(self) -> None:
        dupe_values = _SAMPLE_VALUES + [_SAMPLE_VALUES[0]]  # duplicate last
        payload = {"values": dupe_values, "status": "ok"}
        with _patched(payload):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)
        assert len(bars) == 3


# ---------------------------------------------------------------------------
# fetch_bars — pagination
# ---------------------------------------------------------------------------


class TestFetchBarsPagination:
    def test_stops_when_page_shorter_than_max(self) -> None:
        call_count = 0

        def fake_urlopen(req: object, timeout: int = 30) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return _mock_urlopen(_OK_RESPONSE)

        with (
            patch("novax.data.ingest.twelvedata.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("novax.data.ingest.twelvedata.time.sleep"),
        ):
            bars = fetch_bars("EURUSD", _INTERVAL, _START, _END, _API_KEY)

        assert call_count == 1  # 3 bars < 5000 → no second page
        assert len(bars) == 3

    def test_paginates_when_full_page_returned(self) -> None:
        from novax.data.ingest.twelvedata import _MAX_OUTPUTSIZE

        # First page: exactly MAX_OUTPUTSIZE bars (triggers pagination)
        page1_values = [
            {
                "datetime": f"2024-01-05 {h:02d}:00:00",
                "open": "1.09000",
                "high": "1.09100",
                "low": "1.08900",
                "close": "1.09050",
            }
            for h in range(min(_MAX_OUTPUTSIZE, 24))  # 24 bars for test
        ]
        # Pad to exactly MAX_OUTPUTSIZE
        while len(page1_values) < _MAX_OUTPUTSIZE:
            page1_values.append(page1_values[-1].copy())
        page1_values[-1]["datetime"] = "2024-01-03 00:00:00"  # oldest bar of page 1

        page2_values = [
            {
                "datetime": "2024-01-02 20:00:00",
                "open": "1.08900",
                "high": "1.09000",
                "low": "1.08800",
                "close": "1.08950",
            }
        ]

        responses = [
            {"values": page1_values, "status": "ok"},
            {"values": page2_values, "status": "ok"},
        ]
        call_count = 0

        def fake_urlopen(req: object, timeout: int = 30) -> MagicMock:
            nonlocal call_count
            result = _mock_urlopen(responses[min(call_count, len(responses) - 1)])
            call_count += 1
            return result

        wide_start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        wide_end = datetime(2024, 1, 5, 23, 59, tzinfo=UTC)

        with (
            patch("novax.data.ingest.twelvedata.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("novax.data.ingest.twelvedata.time.sleep"),
        ):
            bars = fetch_bars("EURUSD", _INTERVAL, wide_start, wide_end, _API_KEY)

        assert call_count == 2
        assert any(b.ts == datetime(2024, 1, 2, 20, 0, tzinfo=UTC) for b in bars)
