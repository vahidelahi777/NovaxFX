"""Integration tests for the validation battery, the data-quality artifact, and
the CI integrity invariant.
"""
from datetime import UTC, datetime, timedelta

from novax.artifacts import ArtifactRegistry, ArtifactType
from novax.battery import BatteryInputs, DataQualityGateRunner, ValidationBatteryRunner
from novax.data_sources import Bar
from novax.harness import BaselineRandomStrategy, equity_from_pnls
from novax.runner import ExperimentRunner, audit_campaign_integrity
from novax.trial_registry import TrialRegistry, TrialStatus
from novax.validation import expectancy, sharpe


def _runner(campaign: str = "C") -> tuple[TrialRegistry, ArtifactRegistry, ExperimentRunner]:
    reg, arts = TrialRegistry(), ArtifactRegistry()
    return reg, arts, ExperimentRunner(
        reg, arts, campaign_id=campaign, data_version="d1",
        feature_version="f1", cost_model_version="cm1")


def _london_bars(n: int) -> list[Bar]:
    # Sequential hourly bars during London session (UTC), valid OHLC.
    start = datetime(2025, 6, 2, 8, 0, tzinfo=UTC)  # Monday 08:00 UTC
    bars: list[Bar] = []
    for i in range(n):
        ts = start + timedelta(hours=i)
        bars.append(Bar(ts=ts, open=1.10, high=1.11, low=1.09, close=1.10,
                        bid=1.0999, ask=1.1001, spread=0.0002, source="test"))
    return bars


def test_battery_emits_all_validation_artifacts() -> None:
    reg, arts, runner = _runner()
    battery = ValidationBatteryRunner(seed=0, n_bootstrap=128)
    pnls = BaselineRandomStrategy(seed=2).generate(200)
    with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                         session="LONDON", params={"k": 1}, random_seed=1) as ev:
        battery.run(ev, BatteryInputs(pnls=pnls))
        run_id = ev.run_id
    types = {a.artifact_type for a in arts.for_run(run_id)}
    for t in (ArtifactType.RANDOMIZED_ENTRY, ArtifactType.ONE_BAR_DELAY,
              ArtifactType.COST_STRESS, ArtifactType.WALK_FORWARD,
              ArtifactType.MONTE_CARLO_DD, ArtifactType.NO_LOOKAHEAD):
        assert t in types, f"battery did not emit {t}"


def test_data_quality_runner_emits_artifact_and_gate_requires_it() -> None:
    from novax.gate import evaluate_gate
    reg, arts, runner = _runner()
    pnls = BaselineRandomStrategy(seed=3).generate(200)
    dq = DataQualityGateRunner()
    with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="1h",
                         session="LONDON", params={"k": 1}, random_seed=1) as ev:
        # emit everything EXCEPT data quality first
        ev.emit(ArtifactType.EQUITY_CURVE, {"equity": equity_from_pnls(pnls)})
        ev.emit(ArtifactType.TRADE_LEDGER, {"pnls": pnls})
        ev.emit(ArtifactType.LOCKBOX, {"expectancy": expectancy(pnls)})
        ValidationBatteryRunner(seed=0, n_bootstrap=64).run(ev, BatteryInputs(pnls=pnls))
        run_id = ev.run_id
        # gate BEFORE data-quality exists -> NO_GO on missing DATA_QUALITY
        mid = evaluate_gate(campaign_id="C", strategy="s", run_id=run_id,
                            artifacts=arts, registry=reg)
        assert any("missing artifact: data_quality" in f for f in mid.failed_criteria)
        # now run the data-quality gate runner -> artifact appears
        report = dq.run(ev, symbol="EUR/USD", timeframe="1h", bars=_london_bars(40))
    assert arts.by_type(run_id, ArtifactType.DATA_QUALITY) is not None
    # after emission, the missing-DATA_QUALITY failure is gone
    after = evaluate_gate(campaign_id="C", strategy="s", run_id=run_id,
                          artifacts=arts, registry=reg)
    assert not any("missing artifact: data_quality" in f for f in after.failed_criteria)
    assert isinstance(report.passed, bool)


def test_ci_integrity_artifact_count_equals_trial_count() -> None:
    """CI invariant: distinct trial_ids referenced by artifacts == COMPLETE trials,
    and audit_campaign_integrity reports no violations."""
    reg, arts, runner = _runner("CI")
    battery = ValidationBatteryRunner(seed=0, n_bootstrap=64)
    n = 25
    for i in range(n):
        pnls = BaselineRandomStrategy(seed=i).generate(120)
        with runner.evaluate(strategy="s", instrument="EUR/USD", timeframe="5m",
                             session="LONDON", params={"k": i}, random_seed=i) as ev:
            ev.set_sharpe(sharpe(pnls))
            ev.emit(ArtifactType.EQUITY_CURVE, {"equity": equity_from_pnls(pnls)})
            battery.run(ev, BatteryInputs(pnls=pnls))

    complete = [t for t in reg.campaign("CI", "s") if t.status == TrialStatus.COMPLETE]
    distinct_artifact_trials = {a.trial_id for a in arts.all()}
    assert len(complete) == n
    assert len(distinct_artifact_trials) == n            # one trial-id set per trial
    assert distinct_artifact_trials == {t.result_id for t in complete}
    assert audit_campaign_integrity(reg, arts, "CI", "s") == []
