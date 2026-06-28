"""
Correctness tests for the session calendar — the cases that catch the classic
silent backtest bugs (DST, London/NY mismatch weeks, naive datetimes).

Run:  pytest -q libs/data/test_sessions.py
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from novax.sessions import (
    active_sessions,
    is_fx_market_open,
    is_in_overlap,
    is_in_session,
    overlap_bounds_utc,
    session_bounds_utc,
)

UTC = UTC


def _hours(td: timedelta) -> float:
    return td.total_seconds() / 3600.0


# --- Japan has no DST: ASIA is ALWAYS 00:00–09:00 UTC -----------------------
@pytest.mark.parametrize("d", [date(2025, 1, 15), date(2025, 7, 15)])
def test_asia_no_dst_constant_utc(d):
    start, end = session_bounds_utc("ASIA", d)
    assert (start.hour, start.minute) == (0, 0)
    assert (end.hour, end.minute) == (9, 0)


# --- London overlap shifts with DST but stays 3h when both sides agree ------
def test_overlap_winter_both_standard():
    # Jan: London GMT, NY EST -> overlap 13:00–16:00 UTC (3h)
    s, e = overlap_bounds_utc(date(2025, 1, 15))
    assert (s.hour, e.hour) == (13, 16)
    assert _hours(e - s) == 3.0


def test_overlap_summer_both_dst():
    # Jul: London BST, NY EDT -> overlap 12:00–15:00 UTC (3h), shifted -1h vs winter
    s, e = overlap_bounds_utc(date(2025, 7, 15))
    assert (s.hour, e.hour) == (12, 15)
    assert _hours(e - s) == 3.0


# --- THE KEY CASE: US already on EDT (since 2nd Sun Mar) but UK still on GMT
#     (until last Sun Mar). The overlap LENGTHENS to 4h. A hardcoded UTC window
#     would silently mislabel ~an hour of bars every spring/autumn. -----------
def test_overlap_dst_mismatch_week_is_four_hours():
    # 2025-03-12: US DST started 2025-03-09, UK DST starts 2025-03-30.
    s, e = overlap_bounds_utc(date(2025, 3, 12))
    assert (s.hour, e.hour) == (12, 16)
    assert _hours(e - s) == 4.0  # not 3h!


def test_autumn_mismatch_week_also_four_hours():
    # 2025-10-29: UK back to GMT (2025-10-26), US still EDT until 2025-11-02.
    s, e = overlap_bounds_utc(date(2025, 10, 29))
    assert _hours(e - s) == 4.0


# --- Membership + overlap consistency ---------------------------------------
def test_is_in_overlap_matches_bounds():
    d = date(2025, 1, 15)
    s, e = overlap_bounds_utc(d)
    assert is_in_overlap(s)
    assert is_in_overlap(s + timedelta(minutes=30))
    assert not is_in_overlap(e)  # end is exclusive
    assert not is_in_overlap(s - timedelta(minutes=1))


def test_active_sessions_during_overlap():
    # Inside the winter overlap, both LONDON and NEWYORK are active.
    dt = datetime(2025, 1, 15, 14, 0, tzinfo=UTC)
    act = active_sessions(dt)
    assert "LONDON" in act and "NEWYORK" in act


def test_asia_membership_boundary():
    assert is_in_session("ASIA", datetime(2025, 1, 15, 0, 0, tzinfo=UTC))  # inclusive start
    assert not is_in_session("ASIA", datetime(2025, 1, 15, 9, 0, tzinfo=UTC))  # exclusive end


# --- Safety: naive datetimes must be rejected -------------------------------
def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        is_in_session("LONDON", datetime(2025, 1, 15, 14, 0))  # no tzinfo


# --- Non-UTC aware input is normalized, not mishandled ----------------------
def test_non_utc_aware_input_is_normalized():
    from zoneinfo import ZoneInfo

    # 14:00 UTC expressed in NY time is still inside the winter overlap.
    dt_ny = datetime(2025, 1, 15, 9, 0, tzinfo=ZoneInfo("America/New_York"))  # =14:00 UTC
    assert is_in_overlap(dt_ny)


# --- FX weekend gating -------------------------------------------------------
def test_market_closed_saturday():
    assert not is_fx_market_open(datetime(2025, 1, 18, 12, 0, tzinfo=UTC))  # Sat


def test_market_open_midweek():
    assert is_fx_market_open(datetime(2025, 1, 15, 12, 0, tzinfo=UTC))  # Wed
