"""Central configuration and Phase 0 thresholds.

Single source of truth for the go/no-go numbers so docs, code, and tests cannot
drift apart. Frozen dataclass — settings are constants, not runtime-mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

UTC = UTC


@dataclass(frozen=True, slots=True)
class Settings:
    # --- storage layout (local only in Phase 0) ---
    data_root: str = "data"
    raw_subdir: str = "raw"
    curated_subdir: str = "curated"

    # --- defaults ---
    default_timeframe: str = "5m"

    # --- data-quality gate ---
    min_coverage_pct: float = 99.5

    # --- go/no-go thresholds (mirror docs/phase-0/validation-protocol.md) ---
    min_history_years: int = 5
    min_instruments_passing: int = 3  # of 4
    min_oos_trades: int = 200
    min_walk_forward_window_pass_rate: float = 0.60
    max_drawdown_pct: float = 0.20
    max_mc_p95_drawdown_pct: float = 0.30
    min_profit_factor: float = 1.25
    max_pnl_share_per_slice: float = 0.50  # no session/regime > 50% of PnL
    cost_stress_factors: tuple[float, ...] = (1.0, 1.25, 1.5)

    # --- Phase 0.6 hardening thresholds ---
    min_deflated_sharpe_probability: float = 0.95  # DSR is a probability; doc ">0" was wrong
    randomized_entry_percentile: float = 0.95  # must beat 95th pct of random entries
    default_embargo_fraction: float = 0.01  # embargo as fraction of sample
    fx_kurtosis_estimate: float = 6.0  # FX is fat-tailed; never assume 3 (normal)

    # --- provenance / versioning ---
    feature_version: str = "0.0.0"
    code_version: str = "0.0.1"

    def coverage_fraction(self) -> float:
        """Coverage threshold as a 0..1 fraction."""
        return self.min_coverage_pct / 100.0


SETTINGS = Settings()
