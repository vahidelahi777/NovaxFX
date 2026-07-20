"""Boot reconciliation for PaperTrader ↔ SignalStore.

On daemon restart the in-memory `PaperPosition` is reloaded from JSON, but the
SignalStore lives in DuckDB.  If a position was open at the time of the crash,
`entry_signal_id` is already persisted in PaperPosition.  We verify the store
row still exists (and is ACTIVE/CONFIRMED) and log a warning if it has gone
missing (e.g. someone manually purged the DB).

If the position is FLAT we check for any orphaned ACTIVE rows in the store and
close them as EXPIRED so they don't pollute win-rate statistics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .signal_store import SignalStatus

if TYPE_CHECKING:
    from .paper_trader import PaperTrader
    from .signal_store import SignalStore

__all__ = ["reconcile_on_boot"]

_OPEN_STATUSES = {SignalStatus.CONFIRMED, SignalStatus.ACTIVE}


def reconcile_on_boot(
    trader: PaperTrader,
    store: SignalStore,
    log: logging.Logger | None = None,
) -> None:
    """Reconcile paper-trader state with the signal store on daemon startup.

    - OPEN position + known entry_signal_id → verify store row exists.
    - OPEN position + no entry_signal_id    → nothing to do (pre-P1.3 state).
    - FLAT position                         → expire any orphaned ACTIVE rows.
    """
    _log = log or logging.getLogger(__name__)
    pos = trader.position

    if pos.direction != "FLAT":
        sig_id = pos.entry_signal_id
        if sig_id is None:
            _log.info(
                "reconcile_on_boot: open %s position with no entry_signal_id"
                " (pre-P1.3 state) — skipping",
                pos.direction,
            )
            return

        # Collect all open rows; check ours is among them.
        open_ids: set[str] = set()
        for status in _OPEN_STATUSES:
            open_ids.update(store.ids_by_status(status))

        if sig_id in open_ids:
            _log.info(
                "reconcile_on_boot: open %s position linked to signal %s — OK",
                pos.direction,
                sig_id[:8],
            )
        else:
            _log.warning(
                "reconcile_on_boot: open %s position linked to signal %s "
                "but that row is NOT in the store (purged?) — clearing link",
                pos.direction,
                sig_id[:8],
            )
            trader.clear_entry_link()
        return

    # FLAT: expire any signals left in CONFIRMED/ACTIVE state.
    orphans: list[str] = []
    for status in _OPEN_STATUSES:
        orphans.extend(store.ids_by_status(status))

    if not orphans:
        _log.info("reconcile_on_boot: flat position, no orphaned signals — OK")
        return

    _log.warning(
        "reconcile_on_boot: flat position but %d orphaned open signal(s) — expiring",
        len(orphans),
    )
    for sig_id in orphans:
        store.update_status(sig_id, SignalStatus.EXPIRED)
        _log.info("reconcile_on_boot: expired orphan %s", sig_id[:8])
