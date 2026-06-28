"""Trial registry — multiple-testing control with campaign-level accounting.

Every evaluated configuration is logged (the ExperimentRunner makes this
non-bypassable). The DSR reads its trial count and cross-trial Sharpe variance
from here. Phase 0.7 adds:
  * `campaign_id` + `status` (running/complete/failed) so aborted trials count.
  * CAMPAIGN-level accounting: selecting the best instrument/timeframe/session is
    itself multiple testing, so the campaign count spans those dimensions.
  * a low-variance-family warning (gaming the DSR by logging near-identical trials).

Append-only, JSONL-backed.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .validation import DeflatedSharpeResult, deflated_sharpe_ratio, estimate_sr_variance

__all__ = ["TrialStatus", "Trial", "TrialRegistry"]


class TrialStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Trial:
    strategy: str
    instrument: str
    timeframe: str
    session: str | None
    params: dict[str, float | int | str]
    feature_version: str
    data_version: str
    cost_model_version: str
    validation_split: str
    run_timestamp: datetime
    git_commit: str
    random_seed: int
    observed_sharpe: float
    campaign_id: str = "default"
    status: str = TrialStatus.COMPLETE
    result_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.run_timestamp.tzinfo is None:
            raise ValueError("Trial.run_timestamp must be tz-aware UTC")

    def family_key(self) -> tuple[str, str, str]:
        """Narrow family: (strategy, instrument, timeframe)."""
        return (self.strategy, self.instrument, self.timeframe)

    def campaign_key(self) -> tuple[str, str]:
        """Campaign family: (campaign_id, strategy) — spans instruments/timeframes/sessions."""
        return (self.campaign_id, self.strategy)


@dataclass(slots=True)
class TrialRegistry:
    path: Path | None = None
    _trials: list[Trial] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            d["run_timestamp"] = datetime.fromisoformat(d["run_timestamp"])
            self._trials.append(Trial(**d))

    def log(self, trial: Trial) -> Trial:
        self._trials.append(trial)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rec = asdict(trial)
            rec["run_timestamp"] = trial.run_timestamp.isoformat()
            with self.path.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return trial

    def all(self) -> list[Trial]:
        return list(self._trials)

    def latest(self) -> list[Trial]:
        """One record per trial (latest status wins). Counts use this so the
        two-phase RUNNING->COMPLETE logging does not double-count trials."""
        by_id: dict[str, Trial] = {}
        for t in self._trials:
            by_id[t.result_id] = t  # later record overwrites earlier
        return list(by_id.values())

    def trial_ids(self) -> set[str]:
        return {t.result_id for t in self._trials}

    # --- narrow family (strategy, instrument, timeframe) ---
    def family(self, strategy: str, instrument: str, timeframe: str) -> list[Trial]:
        key = (strategy, instrument, timeframe)
        return [t for t in self.latest() if t.family_key() == key]

    def n_trials(self, strategy: str, instrument: str, timeframe: str) -> int:
        return len(self.family(strategy, instrument, timeframe))

    def sharpes(self, strategy: str, instrument: str, timeframe: str) -> list[float]:
        return [t.observed_sharpe for t in self.family(strategy, instrument, timeframe)]

    def deflated_sharpe_for(
        self, *, strategy: str, instrument: str, timeframe: str,
        observed_sr: float, n_obs: int, skew: float = 0.0, kurtosis: float | None = None,
    ) -> DeflatedSharpeResult:
        """Narrow-family DSR (single instrument/timeframe). Prefer the campaign
        variant for go/no-go, which also counts instrument/timeframe selection."""
        sh = self.sharpes(strategy, instrument, timeframe)
        n_trials = len(sh)
        if n_trials < 1:
            raise ValueError("no trials logged for this family; log before computing DSR")
        kwargs: dict[str, float] = {} if kurtosis is None else {"kurtosis": kurtosis}
        if n_trials == 1:
            return deflated_sharpe_ratio(
                observed_sr, n_obs=n_obs, n_trials=1, sr_variance=0.0, skew=skew, **kwargs)
        return deflated_sharpe_ratio(
            observed_sr, n_obs=n_obs, n_trials=n_trials,
            sr_variance=estimate_sr_variance(sh), skew=skew, **kwargs)

    # --- campaign family (campaign_id, strategy) across instruments/timeframes/sessions ---
    def campaign(self, campaign_id: str, strategy: str) -> list[Trial]:
        key = (campaign_id, strategy)
        return [t for t in self.latest() if t.campaign_key() == key]

    def campaign_n_trials(self, campaign_id: str, strategy: str) -> int:
        return len(self.campaign(campaign_id, strategy))

    def campaign_sharpes(self, campaign_id: str, strategy: str) -> list[float]:
        return [t.observed_sharpe for t in self.campaign(campaign_id, strategy)]

    def deflated_sharpe_for_campaign(
        self, *, campaign_id: str, strategy: str, observed_sr: float, n_obs: int,
        skew: float = 0.0, kurtosis: float | None = None,
    ) -> DeflatedSharpeResult:
        """DSR penalized by the FULL campaign trial count (counts instrument/tf/session selection).

        This closes the Phase 0.6 undercount: picking the best instrument is multiple
        testing, and the campaign count includes every instrument/timeframe/session tried.
        """
        sh = self.campaign_sharpes(campaign_id, strategy)
        n_trials = len(sh)
        if n_trials < 1:
            raise ValueError("no trials logged for this campaign; log before computing DSR")
        kwargs: dict[str, float] = {} if kurtosis is None else {"kurtosis": kurtosis}
        if n_trials == 1:
            return deflated_sharpe_ratio(
                observed_sr, n_obs=n_obs, n_trials=1, sr_variance=0.0, skew=skew, **kwargs)
        result = deflated_sharpe_ratio(
            observed_sr, n_obs=n_obs, n_trials=n_trials,
            sr_variance=estimate_sr_variance(sh), skew=skew, **kwargs)
        # Low-variance gaming warning (near-identical trials shrink the penalty).
        if _suspiciously_low_variance(sh):
            result = _with_warning(result, "trial-family Sharpe variance suspiciously low "
                                           "(possible DSR gaming by near-identical trials)")
        return result


def _suspiciously_low_variance(sharpes: Sequence[float], *, rel: float = 0.01) -> bool:
    if len(sharpes) < 3:
        return False
    mean_abs = sum(abs(s) for s in sharpes) / len(sharpes)
    if mean_abs == 0:
        return False
    spread = max(sharpes) - min(sharpes)
    return spread < rel * mean_abs


def _with_warning(res: DeflatedSharpeResult, msg: str) -> DeflatedSharpeResult:
    from dataclasses import replace
    return replace(res, warnings=(*res.warnings, msg))
