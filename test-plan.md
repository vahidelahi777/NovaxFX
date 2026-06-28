# Phase 0.7 Test Plan

**Status:** 76 tests passing · ruff clean · mypy --strict clean (18 source files) ·
`ci_guards` self-test + repo scan clean.

Tests are grouped below. For each: **purpose** and **what a failure means**. Names are
the actual functions in `tests/`.

## Unit tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_round_trip_cost_is_positive`, `test_xau_costs_more_than_eurusd_in_pips` | cost model basics & instrument conventions | cost arithmetic / pip conventions wrong |
| `test_spread_floor_enforced`, `test_stop_exit_adds_adverse_slippage` | conservative cost flooring & stop slippage | cost model under-charges |
| `test_pip_sizes_are_correct`, `test_pip_math_respects_conventions`, `test_pip_round_trip` | instrument pip math | pip conversions wrong (mis-sized risk/cost) |
| `test_*_session_is_more_expensive_*` | session cost multipliers | session cost model mis-applied |

## Property tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_block_bootstrap_preserves_length_and_is_deterministic` | resampling length + seed determinism | non-deterministic MC ⇒ irreproducible results |
| `test_block_bootstrap_preserves_local_order_within_block` | block structure preserved | autocorrelation destroyed ⇒ understated tail risk |
| `test_percentile_rank`, `test_label_shuffle_mean_near_zero` | rank + null-distribution sanity | randomized-entry comparison invalid |
| `test_overlap_*` (sessions) | session/overlap durations across DST | DST handling regressed |

## Integration tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_best_of_200_random_rejected_end_to_end` | full runner→battery→gate loop rejects luck | the platform would bless a luck-only edge |
| `test_battery_emits_all_validation_artifacts` | battery emits the 6 validation artifacts | gate would see missing inputs |
| `test_data_quality_runner_emits_artifact_and_gate_requires_it` | data-quality artifact wired; missing ⇒ NO_GO | a backtest could pass without a data-quality gate |
| `test_ci_integrity_artifact_count_equals_trial_count` | artifacts reconcile with completed trials | silent discard / orphan would go undetected |

## Artifact / provenance tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_no_artifact_without_trial_id` | registry refuses unblessed trial | evidence could be fabricated out of band |
| `test_orphan_artifact_detected` | orphan detection | artifacts without a trial slip through |
| `test_gate_rejects_provenance_mismatch` | mixed data/feature/cost versions ⇒ NO_GO | stale artifact could be smuggled in |
| `test_registry_persists_to_disk` | trial log durability | crash loses trial count ⇒ DSR under-penalized |

## Adversarial bypass tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_no_result_if_trial_logging_fails` | logging-fail ⇒ body never runs | results could exist without a logged trial |
| `test_under_logging_attack_fails_via_runner` | runner forces full campaign count | DSR defeated by omission |
| `test_campaign_integrity_flags_silent_discard` | completed trial w/o artifact flagged | hidden discards |
| `test_gate_has_no_boolean_override_params` | gate signature has no bool | trust-based override re-introduced |
| `test_legacy_caller_boolean_gate_is_removed` | old gate raises | caller-boolean path callable again |
| `test_gate_rejects_missing_artifacts` | missing artifact ⇒ NO_GO | gate grades on absent evidence |
| `test_gate_rejects_foreign_run_id` | foreign run's artifacts not borrowed | evidence from another run accepted |
| `test_atr_price_units_rejected` | wrong-unit ATR ⇒ TypeError | silent unit error in costs |

## Statistical sanity tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_dsr_rejects_multi_trial_without_variance` | DSR fail-closed (no silent no-op) | the original Phase 0.5 bug returns |
| `test_dsr_penalizes_more_trials` | more trials ⇒ lower probability | multiple-testing penalty inert |
| `test_dsr_requires_valid_n_trials_and_obs`, `test_estimate_sr_variance_needs_two` | input validation | DSR computed on degenerate inputs |
| `test_registry_counts_and_dsr_uses_them` | DSR uses registry trial count | count decoupled from reality |
| `test_no_lookahead_passes_clean_feature`, `test_no_lookahead_catches_leaky_feature` | lookahead detector both ways | leakage undetected |

## Calendar tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_thanksgiving_2025_handled` | mid-week US holiday closed | holiday-contaminated bars accepted |
| `test_holiday_closes_market` | Good Friday + Christmas closed | computed closures regressed |
| `test_friday_*`, `test_sunday_reopen_dst_correct`, `test_market_closed_saturday` | weekend boundary DST-correct | weekend contamination |
| `test_data_quality_flags_weekend_contamination` | DQ flags closed-market bars | bad data passes DQ |

## Cost-unit tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_commission_not_stress_multiplied` | fixed commission excluded from stress | stress test mis-modeled |
| `test_currency_cost_includes_commission` | commission included in currency cost | under-counted costs |
| `test_higher_atr_increases_slippage` | ATR drives slippage (typed `Pips`) | volatility cost ignored |

## Regression tests
| Test | Purpose | Failure means |
|---|---|---|
| `test_phase06_fixes.py::*` | locks the Phase 0.6 remediations (OVERLAP, weekend DST, registry, lookahead, DQ) | a previously-fixed defect returns |
| `test_ci_guards.py::test_repo_source_has_no_enforcement_violations` | source stays free of forbidden constructs | a bypass re-introduced in code |
| `test_ci_guards.py::test_ci_guards_self_test_passes` | the guards themselves still detect violations | the guard rotted (false sense of safety) |

## Commands
```bash
cd novax-scaffold
PYTHONPATH=src python -m pytest -q                # 76 tests
PYTHONPATH=src python -m pytest tests/test_enforcement.py tests/test_gate_rejects_foreign_run_id.py -q
ruff check src tests scripts
MYPYPATH=src mypy --strict src
python scripts/ci_guards.py --self-test
python scripts/ci_guards.py --root . --docs-dir ../docs
```

## Coverage of the patch-plan §6 mandatory list
under-logging ✓ · logging-fail-closed ✓ · artifact-without-trial ✓ · boolean-override
rejected ✓ · missing-artifact ✓ · mismatched/foreign run_id ✓ · best-of-200 ✓ ·
instrument-selection counted ✓ · Thanksgiving 2025 ✓ · ATR price-unit misuse ✓ ·
commission-not-stressed ✓ · artifact-count==trial-count ✓.
