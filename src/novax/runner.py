"""Non-bypassable experiment runner — closes Critical 1 (under-logging).

The ONLY supported way to run an evaluation is through `ExperimentRunner.evaluate`,
a context manager that:
  1. registers an immutable trial (status=RUNNING) BEFORE the body runs;
  2. blesses that trial_id with the artifact registry so artifacts can attach;
  3. requires every artifact to be emitted via the yielded handle (which stamps
     trial_id/run_id/campaign + provenance) — no artifact without a trial;
  4. on success marks the trial COMPLETE with its observed Sharpe;
  5. on ANY exception marks the trial FAILED and re-raises — aborted trials still
     count toward the multiple-testing total;
  6. if trial logging itself fails, the body never runs and no result is returned.

`audit_artifacts_match_trials` is the CI invariant: no orphan artifacts, and every
completed trial produced at least one artifact.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .artifacts import Artifact, ArtifactRegistry, ArtifactType
from .provenance import git_commit, sha256_obj
from .trial_registry import Trial, TrialRegistry, TrialStatus

__all__ = [
    "Evaluation",
    "ExperimentRunner",
    "audit_artifacts_match_trials",
    "audit_campaign_integrity",
]


@dataclass(slots=True)
class Evaluation:
    """Handle yielded inside `evaluate`. The only way to emit artifacts."""

    run_id: str
    trial_id: str
    campaign_id: str
    _artifacts: ArtifactRegistry
    _provenance: dict[str, object]
    observed_sharpe: float = 0.0
    _emitted: int = 0

    def set_sharpe(self, value: float) -> None:
        self.observed_sharpe = value

    def emit(
        self,
        artifact_type: ArtifactType,
        payload: Mapping[str, object],
        *,
        parents: tuple[str, ...] = (),
    ) -> Artifact:
        art = self._artifacts.register(
            run_id=self.run_id,
            trial_id=self.trial_id,
            campaign_id=self.campaign_id,
            artifact_type=artifact_type,
            provenance=self._provenance,
            payload=dict(payload),
            parent_ids=parents,
        )
        self._emitted += 1
        return art

    @property
    def emitted_count(self) -> int:
        return self._emitted


@dataclass(slots=True)
class ExperimentRunner:
    registry: TrialRegistry
    artifacts: ArtifactRegistry
    campaign_id: str = "default"
    data_version: str = ""
    feature_version: str = ""
    cost_model_version: str = ""
    validation_protocol_version: str = ""
    code_version: str = ""
    _provenance_extra: Mapping[str, object] = field(default_factory=dict)

    @contextmanager
    def evaluate(
        self,
        *,
        strategy: str,
        instrument: str,
        timeframe: str,
        session: str | None,
        params: Mapping[str, float | int | str],
        random_seed: int,
        validation_split: str = "research",
    ) -> Iterator[Evaluation]:
        run_id = uuid.uuid4().hex
        commit = git_commit()
        provenance: dict[str, object] = {
            "git_commit": commit,
            "config_hash": sha256_obj(dict(params)),
            "data_hash": self.data_version,
            "feature_version": self.feature_version,
            "cost_model_version": self.cost_model_version,
            "validation_protocol_version": self.validation_protocol_version,
            "random_seed": random_seed,
            "code_version": self.code_version,
            "environment_hash": "",
            "dependency_lock_hash": "",
            **self._provenance_extra,
        }
        # 1) log the trial BEFORE the body. If this raises, the body never runs.
        trial = Trial(
            strategy=strategy,
            instrument=instrument,
            timeframe=timeframe,
            session=session,
            params=dict(params),
            feature_version=self.feature_version,
            data_version=self.data_version,
            cost_model_version=self.cost_model_version,
            validation_split=validation_split,
            run_timestamp=datetime.now(UTC),
            git_commit=commit,
            random_seed=random_seed,
            observed_sharpe=0.0,
            campaign_id=self.campaign_id,
            status=TrialStatus.RUNNING,
        )
        self.registry.log(trial)
        self.artifacts.register_trial_id(trial.result_id)

        ev = Evaluation(run_id, trial.result_id, self.campaign_id, self.artifacts, provenance)
        try:
            yield ev
        except Exception:
            # aborted trials still count toward multiple testing
            self.registry.log(_with_status(trial, TrialStatus.FAILED, ev.observed_sharpe))
            raise
        else:
            self.registry.log(_with_status(trial, TrialStatus.COMPLETE, ev.observed_sharpe))


def _with_status(trial: Trial, status: TrialStatus, sharpe: float) -> Trial:
    from dataclasses import replace

    return replace(
        trial,
        status=status,
        observed_sharpe=sharpe,
        run_timestamp=datetime.now(UTC),
        result_id=trial.result_id,
    )


def audit_artifacts_match_trials(
    registry: TrialRegistry,
    artifacts: ArtifactRegistry,
) -> list[str]:
    """CI invariant. Returns a list of violations (empty == healthy).

    * No orphan artifacts (every artifact.trial_id is a logged trial).
    * Every COMPLETE trial produced >= 1 artifact.
    """
    violations: list[str] = []
    known = registry.trial_ids()
    orphans = artifacts.orphans(known)
    if orphans:
        violations.append(f"{len(orphans)} orphan artifact(s) with no logged trial")
    arts_by_trial: dict[str, int] = {}
    for a in artifacts.all():
        arts_by_trial[a.trial_id] = arts_by_trial.get(a.trial_id, 0) + 1
    complete = {t.result_id for t in registry.all() if t.status == TrialStatus.COMPLETE}
    missing = [tid for tid in complete if arts_by_trial.get(tid, 0) == 0]
    if missing:
        violations.append(f"{len(missing)} completed trial(s) produced no artifact")
    return violations


def audit_campaign_integrity(
    registry: TrialRegistry,
    artifacts: ArtifactRegistry,
    campaign_id: str,
    strategy: str,
) -> list[str]:
    """Strict per-campaign invariant: the set of trial_ids referenced by artifacts
    must EQUAL the set of COMPLETE trials in the campaign — no more, no fewer.

    This is the mechanical answer to the under-logging attack: within a campaign run
    through ``ExperimentRunner``, every evaluation logs a trial and emits >=1 artifact,
    so the two sets coincide. A completed trial with no artifact (silent discard) or
    an artifact whose trial is absent (out-of-band emission) is a hard violation.

    Honest boundary: this cannot detect a trial that was NEVER logged because the
    runner was bypassed entirely. That residual is addressed by making the runner the
    sole sanctioned entry point plus code review — it is policy, not mechanism, and is
    documented as such.
    """
    violations: list[str] = []
    complete = {
        t.result_id
        for t in registry.campaign(campaign_id, strategy)
        if t.status == TrialStatus.COMPLETE
    }
    art_trials = {a.trial_id for a in artifacts.all() if a.trial_id in complete}
    completed_without_art = complete - art_trials
    if completed_without_art:
        violations.append(
            f"{len(completed_without_art)} completed campaign trial(s) emitted no artifact"
        )
    # artifacts whose trial_id is unknown to the registry entirely
    known = registry.trial_ids()
    unknown = {a.trial_id for a in artifacts.all()} - known
    if unknown:
        violations.append(f"{len(unknown)} artifact(s) reference unlogged trial_id(s)")
    return violations
