"""Gate must reject when asked about a run_id that owns no artifacts.

Artifacts are created under run_id A; evaluating the gate with run_id B must fail
closed (the foreign run's artifacts are read as "missing"), so a researcher cannot
point the gate at an unrelated run's evidence.
"""

from novax.artifacts import ArtifactRegistry, ArtifactType
from novax.gate import evaluate_gate
from novax.harness import BaselineRandomStrategy, emit_required_artifacts
from novax.runner import ExperimentRunner
from novax.trial_registry import TrialRegistry


def test_gate_rejects_foreign_run_id() -> None:
    reg, arts = TrialRegistry(), ArtifactRegistry()
    runner = ExperimentRunner(
        reg,
        arts,
        campaign_id="C",
        data_version="d1",
        feature_version="f1",
        cost_model_version="cm1",
    )
    pnls = BaselineRandomStrategy(seed=1).generate(300)

    # Full, gate-ready artifact set is emitted under run_id A.
    with runner.evaluate(
        strategy="s",
        instrument="EUR/USD",
        timeframe="5m",
        session="LONDON",
        params={"k": 1},
        random_seed=1,
    ) as ev:
        emit_required_artifacts(ev, pnls)
        run_id_a = ev.run_id

    # Sanity: run A itself has every required artifact present.
    assert arts.by_type(run_id_a, ArtifactType.EQUITY_CURVE) is not None

    # Evaluate the gate with a DIFFERENT (foreign) run_id -> everything reads missing.
    foreign = "b" * len(run_id_a)
    assert foreign != run_id_a
    dec = evaluate_gate(campaign_id="C", strategy="s", run_id=foreign, artifacts=arts, registry=reg)
    assert dec.passed is False
    assert any("missing artifact" in f for f in dec.failed_criteria)
    # And it did not silently borrow run A's artifacts.
    assert arts.by_type(foreign, ArtifactType.EQUITY_CURVE) is None
