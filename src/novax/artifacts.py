"""Artifact registry — every research output is provenance-stamped and traceable.

Enforcement rules:
  * An artifact CANNOT be registered without a `trial_id` that exists in the trial
    registry (no orphan results).
  * Each artifact carries full provenance (commit, data/config hashes, versions,
    seed) and a content hash; mismatches are detectable by the gate.
  * Registration is append-only; duplicate (run_id, artifact_type) is rejected.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .provenance import sha256_obj

UTC = UTC

__all__ = ["ArtifactType", "Artifact", "ArtifactRegistry"]


def _to_int(v: object) -> int:
    return int(v) if isinstance(v, (int, float, str)) else 0


class ArtifactType(StrEnum):
    EQUITY_CURVE = "equity_curve"
    TRADE_LEDGER = "trade_ledger"
    DATA_QUALITY = "data_quality"
    NO_LOOKAHEAD = "no_lookahead"
    WALK_FORWARD = "walk_forward"
    RANDOMIZED_ENTRY = "randomized_entry"
    ONE_BAR_DELAY = "one_bar_delay"
    COST_STRESS = "cost_stress"
    MONTE_CARLO_DD = "monte_carlo_dd"
    LOCKBOX = "lockbox"
    FAILURE = "failure"
    RESULT = "result"


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    run_id: str
    trial_id: str
    campaign_id: str
    artifact_type: ArtifactType
    created_at: datetime
    git_commit: str
    config_hash: str
    data_hash: str
    feature_version: str
    cost_model_version: str
    validation_protocol_version: str
    random_seed: int
    code_version: str
    environment_hash: str
    dependency_lock_hash: str
    content_hash: str
    payload: dict[str, object] = field(default_factory=dict)
    parent_ids: tuple[str, ...] = field(default_factory=tuple)
    file_path: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("Artifact.created_at must be tz-aware UTC")


@dataclass(slots=True)
class ArtifactRegistry:
    _by_id: dict[str, Artifact] = field(default_factory=dict)
    _known_trial_ids: set[str] = field(default_factory=set)
    _seen: set[tuple[str, str]] = field(default_factory=set)  # (run_id, artifact_type)

    def register_trial_id(self, trial_id: str) -> None:
        """Bless a trial_id so its artifacts may be registered."""
        self._known_trial_ids.add(trial_id)

    def register(
        self,
        *,
        run_id: str,
        trial_id: str,
        campaign_id: str,
        artifact_type: ArtifactType,
        provenance: dict[str, object],
        payload: dict[str, object],
        parent_ids: tuple[str, ...] = (),
        file_path: str | None = None,
    ) -> Artifact:
        if trial_id not in self._known_trial_ids:
            raise ValueError(
                f"refusing to register artifact for unknown trial_id={trial_id!r}: "
                "no artifact without a logged trial."
            )
        key = (run_id, str(artifact_type))
        if key in self._seen:
            raise ValueError(f"duplicate artifact for run_id={run_id} type={artifact_type}")
        self._seen.add(key)
        art = Artifact(
            artifact_id=uuid.uuid4().hex,
            run_id=run_id,
            trial_id=trial_id,
            campaign_id=campaign_id,
            artifact_type=artifact_type,
            created_at=datetime.now(UTC),
            git_commit=str(provenance.get("git_commit", "unknown")),
            config_hash=str(provenance.get("config_hash", "")),
            data_hash=str(provenance.get("data_hash", "")),
            feature_version=str(provenance.get("feature_version", "")),
            cost_model_version=str(provenance.get("cost_model_version", "")),
            validation_protocol_version=str(provenance.get("validation_protocol_version", "")),
            random_seed=_to_int(provenance.get("random_seed", 0)),
            code_version=str(provenance.get("code_version", "")),
            environment_hash=str(provenance.get("environment_hash", "")),
            dependency_lock_hash=str(provenance.get("dependency_lock_hash", "")),
            content_hash=sha256_obj(payload),
            payload=dict(payload),
            parent_ids=tuple(parent_ids),
            file_path=file_path,
        )
        self._by_id[art.artifact_id] = art
        return art

    def all(self) -> list[Artifact]:
        return list(self._by_id.values())

    def for_run(self, run_id: str) -> list[Artifact]:
        return [a for a in self._by_id.values() if a.run_id == run_id]

    def by_type(self, run_id: str, artifact_type: ArtifactType) -> Artifact | None:
        for a in self._by_id.values():
            if a.run_id == run_id and a.artifact_type is artifact_type:
                return a
        return None

    def for_campaign(self, campaign_id: str) -> list[Artifact]:
        return [a for a in self._by_id.values() if a.campaign_id == campaign_id]

    def orphans(self, known_trial_ids: Iterable[str]) -> list[Artifact]:
        known = set(known_trial_ids)
        return [a for a in self._by_id.values() if a.trial_id not in known]
