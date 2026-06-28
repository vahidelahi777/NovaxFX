"""Tests for the remaining Phase 0.6 fixes."""

from datetime import UTC, datetime

import pytest

from novax.data_sources import Bar
from novax.dataquality import run_data_quality
from novax.lookahead import assert_no_lookahead, find_lookahead_indices
from novax.market_calendar import is_fx_market_open
from novax.sessions import active_sessions, primary_session
from novax.trial_registry import Trial, TrialRegistry


# --- HIGH #4: OVERLAP is now emitted ---------------------------------------
def test_overlap_label_emitted():
    dt = datetime(2025, 1, 15, 14, 0, tzinfo=UTC)  # inside London-NY overlap
    act = active_sessions(dt)
    assert "OVERLAP" in act
    assert primary_session(dt) == "OVERLAP"


def test_primary_session_outside_overlap():
    dt = datetime(2025, 1, 15, 9, 0, tzinfo=UTC)  # London only (winter)
    assert primary_session(dt) == "LONDON"


# --- HIGH #5: weekend open/close is DST-correct ----------------------------
def test_friday_2130z_open_in_winter():
    # NY 16:30 EST -> still open. Phase 0 returned False here (bug).
    assert is_fx_market_open(datetime(2025, 1, 17, 21, 30, tzinfo=UTC)) is True


def test_friday_after_ny_close_winter_closed():
    # NY 17:30 EST -> closed.
    assert is_fx_market_open(datetime(2025, 1, 17, 22, 30, tzinfo=UTC)) is False


def test_sunday_reopen_dst_correct():
    # Summer: NY 17:00 EDT == 21:00 UTC. 20:00 UTC -> still closed, 22:00 UTC -> open.
    assert is_fx_market_open(datetime(2025, 7, 13, 20, 0, tzinfo=UTC)) is False
    assert is_fx_market_open(datetime(2025, 7, 13, 22, 0, tzinfo=UTC)) is True


def test_holiday_closes_market():
    # Computed closures: Christmas + Good Friday 2025 (2025-04-18).
    assert is_fx_market_open(datetime(2025, 12, 25, 14, 0, tzinfo=UTC)) is False
    assert is_fx_market_open(datetime(2025, 4, 18, 14, 0, tzinfo=UTC)) is False


# --- HIGH #8 support / Critical: trial registry feeds DSR ------------------
def _trial(sh: float, seed: int) -> Trial:
    return Trial(
        strategy="orb",
        instrument="EUR/USD",
        timeframe="5m",
        session="NEWYORK",
        params={"window": 30},
        feature_version="0.0.0",
        data_version="hashX",
        cost_model_version="0.0.1",
        validation_split="wf1",
        run_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        git_commit="abc",
        random_seed=seed,
        observed_sharpe=sh,
    )


def test_registry_counts_and_dsr_uses_them():
    reg = TrialRegistry()
    for i, sh in enumerate([0.05, 0.1, 0.15, 0.2, 0.25]):
        reg.log(_trial(sh, i))
    assert reg.n_trials("orb", "EUR/USD", "5m") == 5
    res = reg.deflated_sharpe_for(
        strategy="orb", instrument="EUR/USD", timeframe="5m", observed_sr=0.25, n_obs=300
    )
    assert res.n_trials == 5
    assert res.sr_variance > 0  # came from the registry, not a guess


def test_registry_persists_to_disk(tmp_path):
    path = tmp_path / "trials.jsonl"
    reg = TrialRegistry(path=path)
    reg.log(_trial(0.1, 0))
    reg2 = TrialRegistry(path=path)  # reload
    assert reg2.n_trials("orb", "EUR/USD", "5m") == 1


# --- Critical #3: no-lookahead helper catches leaks ------------------------
def _clean_feature(xs):
    # cumulative max up to and including t -> uses only past+present
    out, m = [], float("-inf")
    for x in xs:
        m = max(m, x)
        out.append(m)
    return out


def _leaky_feature(xs):
    # uses the GLOBAL max (future info) -> lookahead
    g = max(xs) if xs else 0.0
    return [g for _ in xs]


def test_no_lookahead_passes_clean_feature():
    assert_no_lookahead(_clean_feature, [3, 1, 4, 1, 5, 9, 2, 6])


def test_no_lookahead_catches_leaky_feature():
    bad = find_lookahead_indices(_leaky_feature, [3, 1, 4, 1, 5, 9, 2, 6])
    assert bad  # non-empty: leak detected
    with pytest.raises(AssertionError):
        assert_no_lookahead(_leaky_feature, [3, 1, 4, 1, 5, 9, 2, 6])


# --- HIGH #7 / data quality gate -------------------------------------------
def _bar(ts, spread=0.0001):
    return Bar(
        ts=ts,
        open=1.10,
        high=1.11,
        low=1.09,
        close=1.10,
        bid=1.0999,
        ask=1.0999 + spread,
        spread=spread,
        source="test",
    )


def test_data_quality_flags_weekend_contamination():
    # A Saturday bar must be flagged as closed-market data.
    bars = [
        _bar(datetime(2025, 1, 15, 14, 0, tzinfo=UTC)),
        _bar(datetime(2025, 1, 18, 14, 0, tzinfo=UTC)),
    ]  # Saturday
    rep = run_data_quality("EUR/USD", "1h", bars)
    names = {c.name: c.passed for c in rep.checks}
    assert names["no_closed_market_data"] is False
    assert rep.passed is False  # fail-closed on a high-severity check


def test_data_quality_flags_duplicate_and_bad_quote():
    ts = datetime(2025, 1, 15, 14, 0, tzinfo=UTC)
    dup = [_bar(ts), _bar(ts)]
    rep = run_data_quality("EUR/USD", "1h", dup)
    names = {c.name: c.passed for c in rep.checks}
    assert names["no_duplicate_timestamps"] is False
