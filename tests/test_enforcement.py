"""Adversarial enforcement tests (Phase 0.7).

Each test attempts a bypass that worked (or was possible) before, and asserts it
now fails closed.
"""
import inspect
from datetime import UTC, datetime

import pytest

from novax.artifacts import ArtifactRegistry, ArtifactType
from novax.costs import DEFAULT_COST_MODEL
from novax.gate import evaluate_gate
from novax.harness import BaselineRandomStrategy, emit_required_artifacts
from novax.instruments import get_instrument
from novax.market_calendar import is_fx_market_open
from novax.runner import ExperimentRunner, audit_artifacts_match_trials
from novax.trial_registry import Trial, TrialRegistry
from novax.units import Pips, PriceUnits, to_pips


def _runner(campaign="C1"):
    reg, arts = TrialRegistry(), ArtifactRegistry()
    return reg, arts, ExperimentRunner(
        reg, arts, campaign_id=campaign, data_version="d1",
        feature_version="f1", cost_model_version="cm1")


# --- 1. cannot return a result if trial logging fails ----------------------
class _FailingRegistry(TrialRegistry):
    def log(self, trial):  # type: ignore[override]
        raise RuntimeError("disk full")


def test_no_result_if_trial_logging_fails():
    arts = ArtifactRegistry()
    runner = ExperimentRunner(_FailingRegistry(), arts, campaign_id="C")
    body_ran = False
    with pytest.raises(RuntimeError), runner.evaluate(
            strategy="s", instrument="EUR/USD", timeframe="5m",
            session="LONDON", params={}, random_seed=1):
        body_ran = True
    assert body_ran is False          # body never executed
    assert arts.all() == []           # no artifacts emitted


# --- 2. cannot produce an artifact without a logged trial ------------------
def test_no_artifact_without_trial_id():
    arts = ArtifactRegistry()
    with pytest.raises(ValueError):
        arts.register(run_id="r", trial_id="ghost", campaign_id="C",
                      artifact_type=ArtifactType.RESULT, provenance={}, payload={})


# --- 3/8. under-logging cannot help: runner forces every trial; best-of-200 rejected
def test_best_of_200_random_rejected_end_to_end():
    reg, arts, runner = _runner("camp")
    n_obs = 300
    best_run, best_sr = None, -9.0
    for i in range(200):
        strat = BaselineRandomStrategy(seed=i)
        pnls = strat.generate(n_obs)
        inst = "EUR/USD" if i % 2 == 0 else "GBP/USD"  # instrument selection too
        with runner.evaluate(strategy="asian", instrument=inst, timeframe="5m",
                             session="LONDON", params={"k": i}, random_seed=i) as ev:
            from novax.validation import sharpe
            sr = sharpe(pnls)
            emit_required_artifacts(ev, pnls)
            if sr > best_sr:
                best_sr, best_run = sr, ev.run_id
    # campaign logged all 200 -> DSR over 200 trials rejects the luckiest
    dec = evaluate_gate(campaign_id="camp", strategy="asian", run_id=best_run,
                        artifacts=arts, registry=reg)
    assert dec.passed is False
    assert any("deflated_sharpe" in f for f in dec.failed_criteria)
    # artifact/trial bookkeeping is healthy
    assert audit_artifacts_match_trials(reg, arts) == []


# --- 4. gate exposes no caller-supplied boolean overrides ------------------
def test_gate_has_no_boolean_override_params():
    sig = inspect.signature(evaluate_gate)
    for p in sig.parameters.values():
        assert p.annotation is not bool, f"gate accepts a bool override: {p.name}"
    # and no params named like overrides
    assert not any(k in sig.parameters for k in
                   ("survives_cost_stress", "beats_randomized_entry", "drawdown_pct"))


# --- 5. gate rejects missing artifacts -------------------------------------
def test_gate_rejects_missing_artifacts():
    reg, arts, runner = _runner("c")
    with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                         session="LONDON", params={}, random_seed=1) as ev:
        ev.emit(ArtifactType.EQUITY_CURVE, {"equity": [1, 2, 3]})  # only one artifact
        run_id = ev.run_id
    dec = evaluate_gate(campaign_id="c", strategy="s", run_id=run_id,
                        artifacts=arts, registry=reg)
    assert dec.passed is False
    assert any("missing artifact" in f for f in dec.failed_criteria)


# --- 6. gate rejects provenance mismatch across artifacts ------------------
def test_gate_rejects_provenance_mismatch():
    reg, arts = TrialRegistry(), ArtifactRegistry()
    # log a trial and bless its id, then register two artifacts with different data_hash
    t = reg.log(Trial("s", "EUR/USD", "5m", "LONDON", {}, "f", "d", "cm", "research",
                      datetime.now(UTC), "c", 1, 0.1, campaign_id="c"))
    arts.register_trial_id(t.result_id)
    base = dict(data_hash="d1", feature_version="f1", cost_model_version="cm1")
    arts.register(run_id="R", trial_id=t.result_id, campaign_id="c",
                  artifact_type=ArtifactType.EQUITY_CURVE,
                  provenance={**base}, payload={"equity": [1, 2]})
    arts.register(run_id="R", trial_id=t.result_id, campaign_id="c",
                  artifact_type=ArtifactType.TRADE_LEDGER,
                  provenance={**base, "data_hash": "DIFFERENT"}, payload={"pnls": [1, -1]})
    # remaining required artifacts share yet another provenance, but mismatch already present
    for at in (ArtifactType.DATA_QUALITY, ArtifactType.NO_LOOKAHEAD, ArtifactType.WALK_FORWARD,
               ArtifactType.RANDOMIZED_ENTRY, ArtifactType.ONE_BAR_DELAY, ArtifactType.COST_STRESS,
               ArtifactType.MONTE_CARLO_DD, ArtifactType.LOCKBOX):
        arts.register(run_id="R", trial_id=t.result_id, campaign_id="c", artifact_type=at,
                      provenance={**base}, payload={})
    dec = evaluate_gate(campaign_id="c", strategy="s", run_id="R", artifacts=arts, registry=reg)
    assert dec.passed is False
    assert any("provenance mismatch" in f for f in dec.failed_criteria)


# --- 7. artifact count == trial count (orphan detection) -------------------
def test_orphan_artifact_detected():
    reg, arts = TrialRegistry(), ArtifactRegistry()
    arts.register_trial_id("ghost")  # blessed but never logged as a Trial
    arts.register(run_id="r", trial_id="ghost", campaign_id="c",
                  artifact_type=ArtifactType.RESULT, provenance={}, payload={})
    violations = audit_artifacts_match_trials(reg, arts)
    assert any("orphan" in v for v in violations)


# --- 9. instrument-selection trials are counted in the campaign ------------
def test_instrument_selection_counts_as_multiple_testing():
    reg = TrialRegistry()
    for inst in ("EUR/USD", "GBP/USD", "USD/JPY"):
        reg.log(Trial("asian", inst, "5m", "LONDON", {}, "f", "d", "cm", "r",
                      datetime.now(UTC), "c", 1, 0.1, campaign_id="camp"))
    assert reg.campaign_n_trials("camp", "asian") == 3   # spans instruments
    assert reg.n_trials("asian", "EUR/USD", "5m") == 1   # narrow family is per-instrument


# --- 10. drawdown computed from the equity curve --------------------------
def test_drawdown_computed_from_equity_curve():
    reg, arts, runner = _runner("c")
    # equity: rise to 100 then fall to 70 -> 30% drawdown
    pnls = [100.0] + [-30.0]  # cum: 100, 70
    with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                         session="LONDON", params={}, random_seed=1) as ev:
        emit_required_artifacts(ev, pnls)
        run_id = ev.run_id
    dec = evaluate_gate(campaign_id="c", strategy="s", run_id=run_id,
                        artifacts=arts, registry=reg)
    assert dec.computed["drawdown_pct"] == pytest.approx(0.30, abs=1e-9)


# --- 11. Thanksgiving 2025 handled ----------------------------------------
def test_thanksgiving_2025_handled():
    # 2025-11-27 is the 4th Thursday of November -> computed closure.
    assert is_fx_market_open(datetime(2025, 11, 27, 15, 0, tzinfo=UTC)) is False


# --- 12. ATR in price units cannot be passed as pips ----------------------
def test_atr_price_units_rejected():
    cm = DEFAULT_COST_MODEL
    with pytest.raises(TypeError):
        cm.round_trip_cost_pips("EUR/USD", atr=PriceUnits(0.0010))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        cm.round_trip_cost_pips("EUR/USD", atr=0.0010)  # type: ignore[arg-type]
    # the correct path: convert first
    pips = to_pips(get_instrument("EUR/USD"), PriceUnits(0.0010))
    assert cm.round_trip_cost_pips("EUR/USD", atr=pips) > 0


# --- 13. fixed commission is not stress-multiplied ------------------------
def test_commission_not_stress_multiplied():
    cm = DEFAULT_COST_MODEL
    commission = 3.5 * 2  # per-side * 2, lots=1
    c1 = cm.round_trip_cost_currency("EUR/USD", lots=1.0, atr=Pips(10))
    c15 = cm.with_stress(1.5).round_trip_cost_currency("EUR/USD", lots=1.0, atr=Pips(10))
    # spread+slippage portion scales 1.5x; commission stays fixed
    assert (c15 - commission) == pytest.approx(1.5 * (c1 - commission))


# --- 13. legacy caller-boolean gate is removed (cannot be invoked) ----------
def test_legacy_caller_boolean_gate_is_removed():
    from novax.validation import evaluate_go_no_go
    with pytest.raises(RuntimeError, match="removed in Phase 0.7"):
        evaluate_go_no_go(
            object(), instruments_passing=4, walk_forward_window_pass_rate=1.0,
            lockbox_expectancy_after_costs=1.0, survives_cost_stress=True,
            max_pnl_share_per_slice=0.1, deflated_sharpe=object(),
            mc_p95_drawdown_pct=0.1, drawdown_pct=0.1,
            beats_randomized_entry=True, survives_one_bar_delay=True,
        )


# --- 14. strict campaign integrity: completed trial with no artifact fails --
def test_campaign_integrity_flags_silent_discard():
    from novax.runner import audit_campaign_integrity
    reg, arts, runner = _runner("CINT")
    # one honest trial: logged AND emits an artifact
    with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                         session="LONDON", params={"k": 1}, random_seed=1) as ev:
        ev.set_sharpe(0.1)
        ev.emit(ArtifactType.EQUITY_CURVE, {"equity": [0.0, 1.0]})
    assert audit_campaign_integrity(reg, arts, "CINT", "s") == []   # healthy

    # now inject a COMPLETE trial directly into the registry with NO artifact
    reg.log(Trial("s", "EUR/USD", "5m", "LONDON", {"k": 2}, "f1", "d1", "cm1",
                  "research", datetime(2025, 1, 1, tzinfo=UTC), "c", 2,
                  observed_sharpe=0.9, campaign_id="CINT"))
    violations = audit_campaign_integrity(reg, arts, "CINT", "s")
    assert any("emitted no artifact" in v for v in violations)


# --- 15. under-logging attack: runner forces full campaign count -----------
def test_under_logging_attack_fails_via_runner():
    reg, arts, runner = _runner("BIG")
    for i in range(200):
        with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                             session="LONDON", params={"k": i}, random_seed=i) as ev:
            ev.set_sharpe(0.05)
            ev.emit(ArtifactType.EQUITY_CURVE, {"equity": [0.0, 0.01]})
    # the registry now SEES all 200 trials -> campaign DSR uses n=200, not n=1
    assert reg.campaign_n_trials("BIG", "s") == 200
    from novax.runner import audit_campaign_integrity
    assert audit_campaign_integrity(reg, arts, "BIG", "s") == []
