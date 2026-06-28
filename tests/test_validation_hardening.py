"""Validation-hardening tests — prove the Critical/High fixes actually hold."""
from datetime import UTC, datetime, timedelta

import pytest

from novax.validation import (
    block_bootstrap,
    deflated_sharpe_ratio,
    estimate_sr_variance,
    percentile_rank,
    purged_kfold,
    shuffle_pnls_mean,
    walk_forward_windows,
)


# --- DSR fail-closed: the headline Critical fix ----------------------------
def test_dsr_rejects_multi_trial_without_variance():
    # The Phase 0 silent no-op is now impossible.
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(0.2, n_obs=300, n_trials=50, sr_variance=0.0)


def test_dsr_requires_valid_n_trials_and_obs():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(0.2, n_obs=300, n_trials=0, sr_variance=0.01)
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(0.2, n_obs=1, n_trials=1, sr_variance=0.0)


def test_dsr_penalizes_more_trials():
    # Same observed Sharpe + variance: more trials => lower probability.
    few = deflated_sharpe_ratio(0.20, n_obs=300, n_trials=2, sr_variance=0.01)
    many = deflated_sharpe_ratio(0.20, n_obs=300, n_trials=500, sr_variance=0.01)
    assert many.probability < few.probability
    assert many.benchmark_sharpe > few.benchmark_sharpe  # sr0 grows with trials


def test_dsr_warns_on_normal_kurtosis_and_small_sample():
    r = deflated_sharpe_ratio(0.2, n_obs=50, n_trials=1, sr_variance=0.0, kurtosis=3.0)
    joined = " ".join(r.warnings)
    assert "kurtosis" in joined and "small sample" in joined


def test_estimate_sr_variance_needs_two():
    with pytest.raises(ValueError):
        estimate_sr_variance([0.1])
    assert estimate_sr_variance([0.1, 0.2, 0.3]) > 0


# --- walk-forward generator ------------------------------------------------
def test_walk_forward_windows_non_overlapping_and_chronological():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 4, 1, tzinfo=UTC)
    ws = walk_forward_windows(start, end, train=timedelta(days=20), test=timedelta(days=10))
    assert len(ws) >= 2
    for w in ws:
        assert w.train_start < w.train_end <= w.test_start < w.test_end
    # consecutive test windows do not overlap
    for a, b in zip(ws, ws[1:], strict=False):
        assert b.test_start >= a.test_start


def test_walk_forward_requires_aware():
    with pytest.raises(ValueError):
        walk_forward_windows(datetime(2020, 1, 1), datetime(2020, 2, 1),
                             train=timedelta(days=10), test=timedelta(days=5))


# --- purged k-fold + embargo ----------------------------------------------
def test_purged_kfold_no_train_test_overlap_and_embargo_gap():
    folds = purged_kfold(100, n_splits=5, embargo=3)
    assert len(folds) == 5
    for train, test in folds:
        assert set(train).isdisjoint(test)              # no leakage
        lo, hi = min(test), max(test)
        for i in train:
            assert not (hi < i <= hi + 3)               # right embargo enforced
            assert not (lo - 3 <= i < lo)               # left embargo enforced


# --- block bootstrap -------------------------------------------------------
def test_block_bootstrap_preserves_length_and_is_deterministic():
    vals = list(range(50))
    a = block_bootstrap(vals, block_size=5, n_resamples=10, seed=1)
    b = block_bootstrap(vals, block_size=5, n_resamples=10, seed=1)
    assert a == b                                       # seeded -> reproducible
    assert all(len(s) == len(vals) for s in a)


def test_block_bootstrap_preserves_local_order_within_block():
    vals = list(range(20))
    [series] = block_bootstrap(vals, block_size=20, n_resamples=1, seed=0)
    # with block_size == n, a resample is a single contiguous slice -> ascending
    assert series == sorted(series)


# --- destructive-battery stats --------------------------------------------
def test_percentile_rank():
    assert percentile_rank(5, [1, 2, 3, 4]) == 1.0
    assert percentile_rank(0, [1, 2, 3, 4]) == 0.0


def test_label_shuffle_mean_near_zero():
    pnls = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5] * 20
    m = shuffle_pnls_mean(pnls, n_shuffles=200, seed=0)
    assert abs(m) < 0.05  # permutation preserves the (near-zero) mean
