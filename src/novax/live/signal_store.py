"""DuckDB-backed signal store with full lifecycle tracking.

Architecture
============

Write path
----------
  scanner → score_signal() → SignalStore.insert()
               ↓
         DuckDB (in-process, single file)
               ↓
    Monthly Parquet archive (same layout as bar store)

Read path (analytical)
----------------------
  dashboard / confidence engine / ML features
      ↓
  SignalStore.win_rate()       — empirical win rate in score band + regime
  SignalStore.confidence()     — Wilson score interval (lower bound)
  SignalStore.recent()         — last N signals for dashboard feed
  SignalStore.score_breakdown() — per-component performance table

Signal lifecycle
----------------
  PENDING   signal emitted; entry not yet triggered (next bar not confirmed)
  CONFIRMED entry bar moved in direction (position assumed open)
  ACTIVE    tracking MAE/MFE across bars; neither SL nor TP hit yet
  WIN       TP touched — record pnl_pips > 0
  LOSS      SL touched — record pnl_pips < 0
  EXPIRED   max_hold_bars elapsed without SL or TP — record pnl_pips = 0

Confidence levels
-----------------
  ESTABLISHED    ≥ 50 closed signals in score band + regime
  DEVELOPING     20–49 closed signals
  INSUFFICIENT   < 20 closed signals — confidence defaults to 0.5 (neutral)

Score weights
-------------
  Phase 1 (now):   static weights [structure=30, momentum=30, session=20, cost=20]
  Phase 2 (100+):  logistic regression fit on closed signals — coefficients
                   normalised to sum 100 become the new weights
  Phase 3 (500+):  per-regime weights — trending vs ranging vs volatile each
                   get their own weight vector

Why DuckDB
----------
  Already a dependency.  Column-oriented → fast analytical GROUP BY / window
  functions.  In-process → no server to manage.  Reads Parquet natively →
  historical bars and archived signals queryable with the same SQL.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import sqrt
from pathlib import Path
from typing import Any

import duckdb

from .signal_score import SignalScore

__all__ = [
    "SignalStatus",
    "SignalWeights",
    "StoredSignal",
    "SignalStore",
    "STATIC_WEIGHTS",
]

log = logging.getLogger(__name__)

# ── Default static weights ───────────────────────────────────────────────────
# These are the starting point before ML optimisation has enough data.
# Each value is the maximum points the component can contribute.
_DEFAULT_W = {"structure": 30, "momentum": 30, "session": 20, "cost": 20}


@dataclass(frozen=True)
class SignalWeights:
    """Weight vector for the four score components.

    All weights must sum to 100.  Validated on construction.
    """

    structure: int = 30
    momentum: int = 30
    session: int = 20
    cost: int = 20

    def __post_init__(self) -> None:
        total = self.structure + self.momentum + self.session + self.cost
        if total != 100:
            raise ValueError(f"SignalWeights must sum to 100, got {total}")

    def to_json(self) -> str:
        return json.dumps(
            {
                "structure": self.structure,
                "momentum": self.momentum,
                "session": self.session,
                "cost": self.cost,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> SignalWeights:
        d = json.loads(raw)
        return cls(**d)


STATIC_WEIGHTS = SignalWeights(structure=30, momentum=30, session=20, cost=20)


class SignalStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    WIN = "win"
    LOSS = "loss"
    EXPIRED = "expired"

    @property
    def is_closed(self) -> bool:
        return self in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.EXPIRED}


@dataclass
class StoredSignal:
    """Full representation of one signal in the DuckDB store."""

    # Identity
    id: str
    ts: datetime  # emission UTC
    symbol: str
    source: str  # "15m_scan" | "daily" | "weekly" | ...
    direction: str | None  # "LONG" | "SHORT" | None

    # Multi-TF state
    h4_signal: str
    h1_signal: str
    m15_signal: str
    confluence: bool

    # Entry levels
    entry_price: float | None
    sl: float | None
    tp: float | None
    rr: float | None  # tp_pips / sl_pips
    sl_pips: float | None

    # Score
    score: SignalScore
    score_weights: SignalWeights

    # Confidence
    confidence_pct: float  # Wilson lower bound [0.0, 1.0]
    confidence_n: int  # sample size used
    confidence_label: str  # ESTABLISHED | DEVELOPING | INSUFFICIENT

    # Market context
    regime: str  # trending | ranging | volatile | unknown

    # Lifecycle
    status: SignalStatus = SignalStatus.PENDING
    status_ts: datetime | None = None

    # Outcome (filled on close)
    outcome_pnl_pips: float | None = None
    outcome_bars_held: int | None = None
    max_adverse_pips: float | None = None
    max_favor_pips: float | None = None

    # Audit
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


# ── DuckDB schema ────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS signals (
    id                 VARCHAR PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL,
    symbol             VARCHAR     NOT NULL,
    source             VARCHAR     NOT NULL,
    direction          VARCHAR,

    h4_signal          VARCHAR     NOT NULL,
    h1_signal          VARCHAR     NOT NULL,
    m15_signal         VARCHAR     NOT NULL,
    confluence         BOOLEAN     NOT NULL,

    entry_price        DOUBLE,
    sl                 DOUBLE,
    tp                 DOUBLE,
    rr                 DOUBLE,
    sl_pips            DOUBLE,

    score_total        INTEGER,
    score_structure    INTEGER,
    score_momentum     INTEGER,
    score_session      INTEGER,
    score_cost         INTEGER,
    score_label        VARCHAR,
    score_weights      VARCHAR,

    confidence_pct     DOUBLE,
    confidence_n       INTEGER,
    confidence_label   VARCHAR,

    regime             VARCHAR,

    status             VARCHAR     NOT NULL DEFAULT 'pending',
    status_ts          TIMESTAMPTZ,

    outcome_pnl_pips   DOUBLE,
    outcome_bars_held  INTEGER,
    max_adverse_pips   DOUBLE,
    max_favor_pips     DOUBLE,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class SignalStore:
    """DuckDB-backed store for signals with lifecycle and confidence tracking.

    Thread model: single-writer (the daemon calls this from the main loop).
    DuckDB in-process mode is used — no server required.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._con = duckdb.connect(str(db_path))
        self._con.execute(_DDL)
        log.info("SignalStore opened: %s", db_path)

    # ── Write ────────────────────────────────────────────────────────────────

    def insert(self, sig: StoredSignal) -> None:
        """Insert a new pending signal. Ignores duplicate IDs."""
        self._con.execute(
            """
            INSERT OR IGNORE INTO signals (
                id, ts, symbol, source, direction,
                h4_signal, h1_signal, m15_signal, confluence,
                entry_price, sl, tp, rr, sl_pips,
                score_total, score_structure, score_momentum, score_session, score_cost,
                score_label, score_weights,
                confidence_pct, confidence_n, confidence_label,
                regime, status, created_at
            ) VALUES (?, ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?,  ?, ?,  ?, ?, ?,  ?, ?, ?)
            """,
            [
                sig.id,
                sig.ts,
                sig.symbol,
                sig.source,
                sig.direction,
                sig.h4_signal,
                sig.h1_signal,
                sig.m15_signal,
                sig.confluence,
                sig.entry_price,
                sig.sl,
                sig.tp,
                sig.rr,
                sig.sl_pips,
                sig.score.total,
                sig.score.structure,
                sig.score.momentum,
                sig.score.session,
                sig.score.cost,
                sig.score.label,
                sig.score_weights.to_json(),
                sig.confidence_pct,
                sig.confidence_n,
                sig.confidence_label,
                sig.regime,
                sig.status.value,
                sig.created_at,
            ],
        )
        log.debug(
            "Signal inserted: %s score=%d conf=%.0f%%",
            sig.id[:8],
            sig.score.total,
            sig.confidence_pct * 100,
        )

    def update_status(
        self,
        signal_id: str,
        status: SignalStatus,
        *,
        now: datetime | None = None,
        pnl_pips: float | None = None,
        bars_held: int | None = None,
        max_adverse: float | None = None,
        max_favor: float | None = None,
    ) -> None:
        """Update signal lifecycle. Called by the outcome tracker."""
        ts = now or datetime.now(tz=UTC)
        self._con.execute(
            """
            UPDATE signals SET
                status            = ?,
                status_ts         = ?,
                outcome_pnl_pips  = COALESCE(?, outcome_pnl_pips),
                outcome_bars_held = COALESCE(?, outcome_bars_held),
                max_adverse_pips  = COALESCE(?, max_adverse_pips),
                max_favor_pips    = COALESCE(?, max_favor_pips)
            WHERE id = ?
            """,
            [status.value, ts, pnl_pips, bars_held, max_adverse, max_favor, signal_id],
        )
        log.info("Signal %s → %s  pnl=%s", signal_id[:8], status.value, pnl_pips)

    # ── Read — confidence ────────────────────────────────────────────────────

    def win_rate(
        self,
        score_band: tuple[int, int],
        regime: str = "any",
        *,
        min_samples: int = 1,
    ) -> tuple[float, int]:
        """Return (win_rate, sample_size) for closed signals in score band.

        Only WIN and LOSS count; EXPIRED is excluded from win-rate calculation
        because expired signals are ambiguous (neither proved nor disproved).

        Args:
            score_band: (low, high) inclusive score range.
            regime: "any" ignores regime; otherwise filters by regime column.
            min_samples: if fewer samples, return (0.5, 0).
        """
        lo, hi = score_band
        where_regime = "" if regime == "any" else "AND regime = ?"
        params: list[Any] = [lo, hi]
        if regime != "any":
            params.append(regime)

        row = self._con.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'win')  AS wins,
                COUNT(*) FILTER (WHERE status = 'loss') AS losses
            FROM signals
            WHERE status IN ('win', 'loss')
              AND score_total BETWEEN ? AND ?
              {where_regime}
            """,
            params,
        ).fetchone()

        if row is None:
            return 0.5, 0

        wins, losses = int(row[0]), int(row[1])
        n = wins + losses
        if n < min_samples:
            return 0.5, 0

        return wins / n, n

    def confidence(
        self,
        score: int,
        regime: str = "any",
        *,
        band_width: int = 10,
        z: float = 1.645,  # 90% one-sided confidence interval
        min_samples: int = 20,
    ) -> tuple[float, int, str]:
        """Compute Wilson score interval lower bound for the win rate.

        This is the confidence we attach to a new signal: "how confident are
        we, based on history, that a signal of this score in this regime wins?"

        Formula
        -------
        p_wilson = (p_hat + z²/2n - z·sqrt(p_hat(1-p_hat)/n + z²/4n²))
                   / (1 + z²/n)

        Returns
        -------
        (confidence_pct, sample_size, label)
          confidence_pct  Wilson lower bound in [0, 1]
          sample_size     number of closed signals used
          label           ESTABLISHED | DEVELOPING | INSUFFICIENT
        """
        lo = max(0, score - band_width)
        hi = min(100, score + band_width)
        p_hat, n = self.win_rate((lo, hi), regime, min_samples=min_samples)

        if n < min_samples:
            return 0.5, n, "INSUFFICIENT"

        z2 = z * z
        numerator = p_hat + z2 / (2 * n) - z * sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))
        denominator = 1 + z2 / n
        wilson_lower = max(0.0, min(1.0, numerator / denominator))

        if n >= 50:
            label = "ESTABLISHED"
        elif n >= 20:
            label = "DEVELOPING"
        else:
            label = "INSUFFICIENT"

        return wilson_lower, n, label

    # ── Read — analytics ─────────────────────────────────────────────────────

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n signals as dicts (newest first)."""
        cur = self._con.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT ?", [n])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def score_breakdown(self) -> list[dict[str, Any]]:
        """Aggregate win rate by score bucket (0–49, 50–69, 70–100)."""
        cur = self._con.execute(
            """
            SELECT
                CASE
                    WHEN score_total < 50  THEN 'LOW (0-49)'
                    WHEN score_total < 70  THEN 'MEDIUM (50-69)'
                    ELSE                        'HIGH (70-100)'
                END                                                     AS bucket,
                COUNT(*)                                                AS total,
                COUNT(*) FILTER (WHERE status = 'win')                 AS wins,
                COUNT(*) FILTER (WHERE status = 'loss')                AS losses,
                COUNT(*) FILTER (WHERE status = 'expired')             AS expired,
                ROUND(AVG(outcome_pnl_pips) FILTER (
                    WHERE status IN ('win','loss')
                ), 1)                                                   AS avg_pnl_pips
            FROM signals
            GROUP BY bucket
            ORDER BY bucket
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def component_correlations(self) -> dict[str, float]:
        """Pearson correlation of each score component with win outcome.

        Requires at least 30 closed (win/loss) signals.  Returns {} if not
        enough data yet.
        """
        n_closed = self._con.execute(
            "SELECT COUNT(*) FROM signals WHERE status IN ('win','loss')"
        ).fetchone()
        if n_closed is None or n_closed[0] < 30:
            return {}

        row = self._con.execute(
            """
            SELECT
                corr(score_structure, CASE WHEN status = 'win' THEN 1.0 ELSE 0.0 END),
                corr(score_momentum,  CASE WHEN status = 'win' THEN 1.0 ELSE 0.0 END),
                corr(score_session,   CASE WHEN status = 'win' THEN 1.0 ELSE 0.0 END),
                corr(score_cost,      CASE WHEN status = 'win' THEN 1.0 ELSE 0.0 END)
            FROM signals
            WHERE status IN ('win', 'loss')
            """
        ).fetchone()
        if row is None:
            return {}
        return {
            "structure": round(row[0] or 0.0, 3),
            "momentum": round(row[1] or 0.0, 3),
            "session": round(row[2] or 0.0, 3),
            "cost": round(row[3] or 0.0, 3),
        }

    def suggest_weights(self) -> SignalWeights | None:
        """Derive optimised weights from component→outcome correlations.

        Phase 2 weight optimisation:
        1. Compute Pearson r for each component vs win (1) / loss (0).
        2. Clip negatives to 0 (a negative correlation component still
           contributes 0, not a negative weight).
        3. Normalise so the four weights sum to 100.
        4. Return as SignalWeights.

        Returns None if insufficient data (< 30 closed signals).

        This is NOT a full logistic regression — it is a first-order
        approximation that is cheap, interpretable, and needs no ML library.
        When you have 500+ signals, replace with sklearn LogisticRegression.
        """
        corr = self.component_correlations()
        if not corr:
            return None

        raw = {k: max(0.0, v) for k, v in corr.items()}
        total = sum(raw.values())
        if total == 0.0:
            return None

        # Scale so components sum to 100, minimum weight per component = 5
        scaled = {k: max(5, round(v / total * 100)) for k, v in raw.items()}

        # Fix rounding so they sum exactly to 100
        diff = 100 - sum(scaled.values())
        largest = max(scaled, key=lambda k: scaled[k])
        scaled[largest] += diff

        try:
            return SignalWeights(**scaled)
        except ValueError:
            return None

    # ── Archive ──────────────────────────────────────────────────────────────

    def export_month(self, year: int, month: int, out_path: Path) -> int:
        """Export one calendar month of signals to Parquet.

        Returns the number of rows exported.
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._con.execute(
            """
            COPY (
                SELECT * FROM signals
                WHERE year(ts)  = ? AND month(ts) = ?
                ORDER BY ts
            ) TO ? (FORMAT PARQUET, COMPRESSION SNAPPY)
            """,
            [year, month, str(out_path)],
        )
        rows = self._con.execute(
            "SELECT COUNT(*) FROM signals WHERE year(ts) = ? AND month(ts) = ?",
            [year, month],
        ).fetchone()
        n = int(rows[0]) if rows else 0
        log.info("Exported %d signals → %s", n, out_path)
        return n

    def purge_before(self, year: int, month: int) -> int:
        """Delete all signals strictly before the given year/month.

        Call this AFTER export_month() to keep the live DuckDB lean.
        Returns the number of rows deleted.
        """
        result = self._con.execute(
            """
            DELETE FROM signals
            WHERE ts < make_timestamp(?, ?, 1, 0, 0, 0)
            """,
            [year, month],
        )
        n = result.fetchone()
        deleted = int(n[0]) if n else 0
        log.info("Purged %d signals older than %04d-%02d", deleted, year, month)
        return deleted

    def total_count(self) -> int:
        """Return total number of signals in the live store."""
        row = self._con.execute("SELECT COUNT(*) FROM signals").fetchone()
        return int(row[0]) if row else 0

    def count_by_status(self, status: SignalStatus) -> int:
        """Return count of signals with the given status."""
        row = self._con.execute(
            "SELECT COUNT(*) FROM signals WHERE status = ?", [status.value]
        ).fetchone()
        return int(row[0]) if row else 0

    def ids_by_status(self, status: SignalStatus) -> list[str]:
        """Return all signal IDs with the given status."""
        rows = self._con.execute(
            "SELECT id FROM signals WHERE status = ?", [status.value]
        ).fetchall()
        return [row[0] for row in rows]

    def cumulative_pnl_pips(self) -> float:
        """Return sum of pnl_pips for all closed (WIN/LOSS) signals."""
        row = self._con.execute(
            "SELECT COALESCE(SUM(pnl_pips), 0.0) FROM signals "
            "WHERE status IN ('win', 'loss') AND pnl_pips IS NOT NULL"
        ).fetchone()
        return float(row[0]) if row else 0.0

    def close(self) -> None:
        self._con.close()


# ── Signal ID helper ─────────────────────────────────────────────────────────


def make_signal_id(symbol: str, ts: datetime, source: str) -> str:
    """Stable, deterministic signal ID — SHA-256 of key fields."""
    raw = f"{symbol}|{ts.isoformat()}|{source}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
