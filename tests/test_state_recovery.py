"""Tests for P1.3: ids_by_status + reconcile_on_boot.

No network, no Telegram. Uses tmp_path for both DuckDB (SignalStore)
and JSON (PaperTrader position).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from novax.live.paper_trader import PaperPosition, PaperTrader
from novax.live.recovery import reconcile_on_boot
from novax.live.signal_score import SignalScore
from novax.live.signal_store import (
    STATIC_WEIGHTS,
    SignalStatus,
    SignalStore,
    StoredSignal,
    make_signal_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
_SCORE = SignalScore(total=70, structure=20, momentum=20, session=15, cost=15)
_WEIGHTS = STATIC_WEIGHTS


def _store(tmp_path: Path) -> SignalStore:
    return SignalStore(tmp_path / "signals.db")


def _signal(
    store: SignalStore, *, source: str = "test", status: SignalStatus = SignalStatus.PENDING
) -> str:
    sig_id = make_signal_id("XAUUSD", _TS, source)
    sig = StoredSignal(
        id=sig_id,
        ts=_TS,
        symbol="XAUUSD",
        source=source,
        direction="LONG",
        h4_signal="LONG",
        h1_signal="LONG",
        m15_signal="LONG",
        confluence=True,
        entry_price=2600.0,
        sl=2580.0,
        tp=2640.0,
        rr=2.0,
        sl_pips=200.0,
        score=_SCORE,
        score_weights=_WEIGHTS,
        confidence_pct=0.5,
        confidence_n=0,
        confidence_label="INSUFFICIENT",
        regime="unknown",
        status=SignalStatus.PENDING,
    )
    store.insert(sig)
    if status != SignalStatus.PENDING:
        store.update_status(sig_id, status)
    return sig_id


def _trader(tmp_path: Path, *, position: PaperPosition | None = None) -> PaperTrader:
    path = tmp_path / "paper.json"
    if position is not None:
        import dataclasses
        import json

        path.write_text(json.dumps(dataclasses.asdict(position)), encoding="utf-8")
    return PaperTrader(path)


# ---------------------------------------------------------------------------
# ids_by_status
# ---------------------------------------------------------------------------


def test_ids_by_status_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.ids_by_status(SignalStatus.ACTIVE) == []


def test_ids_by_status_returns_matching(tmp_path: Path) -> None:
    store = _store(tmp_path)
    active_id = _signal(store, source="s1", status=SignalStatus.ACTIVE)
    _signal(store, source="s2", status=SignalStatus.WIN)
    result = store.ids_by_status(SignalStatus.ACTIVE)
    assert result == [active_id]


def test_ids_by_status_multiple(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = {_signal(store, source=f"s{i}", status=SignalStatus.ACTIVE) for i in range(3)}
    result = set(store.ids_by_status(SignalStatus.ACTIVE))
    assert result == ids


# ---------------------------------------------------------------------------
# reconcile_on_boot: FLAT position
# ---------------------------------------------------------------------------


def test_reconcile_flat_no_orphans(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trader = _trader(tmp_path)
    # Should complete without error — nothing to reconcile.
    reconcile_on_boot(trader, store, logging.getLogger("test"))
    assert trader.position.direction == "FLAT"


def test_reconcile_flat_expires_active_orphans(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sig_id = _signal(store, status=SignalStatus.ACTIVE)
    trader = _trader(tmp_path)

    reconcile_on_boot(trader, store, logging.getLogger("test"))

    assert store.ids_by_status(SignalStatus.ACTIVE) == []
    assert store.ids_by_status(SignalStatus.EXPIRED) == [sig_id]


def test_reconcile_flat_expires_confirmed_orphans(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sig_id = _signal(store, status=SignalStatus.CONFIRMED)
    trader = _trader(tmp_path)

    reconcile_on_boot(trader, store, logging.getLogger("test"))

    assert store.ids_by_status(SignalStatus.CONFIRMED) == []
    assert store.ids_by_status(SignalStatus.EXPIRED) == [sig_id]


# ---------------------------------------------------------------------------
# reconcile_on_boot: OPEN position with valid link
# ---------------------------------------------------------------------------


def test_reconcile_open_with_known_id_ok(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sig_id = _signal(store, status=SignalStatus.ACTIVE)

    pos = PaperPosition(
        direction="LONG",
        entry_price=2600.0,
        entry_ts=_TS.isoformat(),
        sl=2580.0,
        tp=2640.0,
        entry_signal_id=sig_id,
    )
    trader = _trader(tmp_path, position=pos)

    reconcile_on_boot(trader, store, logging.getLogger("test"))

    # Link should still be intact.
    assert trader.position.entry_signal_id == sig_id


# ---------------------------------------------------------------------------
# reconcile_on_boot: OPEN position with missing store row
# ---------------------------------------------------------------------------


def test_reconcile_open_id_not_in_store_clears_link(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # Insert then close the signal — it's no longer in an open status.
    sig_id = _signal(store, status=SignalStatus.WIN)

    pos = PaperPosition(
        direction="LONG",
        entry_price=2600.0,
        entry_ts=_TS.isoformat(),
        sl=2580.0,
        tp=2640.0,
        entry_signal_id=sig_id,
    )
    trader = _trader(tmp_path, position=pos)

    reconcile_on_boot(trader, store, logging.getLogger("test"))

    # Link should be cleared since the row is not in an open status.
    assert trader.position.entry_signal_id is None


# ---------------------------------------------------------------------------
# reconcile_on_boot: OPEN position, no entry_signal_id (pre-P1.3)
# ---------------------------------------------------------------------------


def test_reconcile_open_no_id_is_noop(tmp_path: Path) -> None:
    store = _store(tmp_path)
    orphan_id = _signal(store, status=SignalStatus.ACTIVE)

    pos = PaperPosition(
        direction="LONG",
        entry_price=2600.0,
        entry_ts=_TS.isoformat(),
        entry_signal_id=None,  # pre-P1.3 state — no link persisted
    )
    trader = _trader(tmp_path, position=pos)

    reconcile_on_boot(trader, store, logging.getLogger("test"))

    # Orphan NOT expired — we can't know if it belongs to this position.
    assert store.ids_by_status(SignalStatus.ACTIVE) == [orphan_id]
    # Position unchanged.
    assert trader.position.direction == "LONG"
    assert trader.position.entry_signal_id is None
