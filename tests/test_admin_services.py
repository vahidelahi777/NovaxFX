"""Tests for novax.admin.services — no network, no DB."""

from __future__ import annotations

from novax.admin.services import health_snapshot


def test_health_snapshot_db_ok() -> None:
    snap = health_snapshot(check_db=lambda: True)
    assert snap["db_ok"] is True


def test_health_snapshot_db_fail() -> None:
    snap = health_snapshot(check_db=lambda: False)
    assert snap["db_ok"] is False


def test_health_snapshot_db_exception_counts_as_fail() -> None:
    def _bad() -> bool:
        raise RuntimeError("connection refused")

    snap = health_snapshot(check_db=_bad)
    assert snap["db_ok"] is False


def test_health_snapshot_has_version() -> None:
    snap = health_snapshot(check_db=lambda: True)
    assert isinstance(snap["version"], str)
    assert snap["version"]  # non-empty


def test_health_snapshot_has_time_utc() -> None:
    snap = health_snapshot(check_db=lambda: True)
    assert "time_utc" in snap
    assert "T" in snap["time_utc"]  # ISO 8601 format


def test_health_snapshot_keys_present() -> None:
    snap = health_snapshot(check_db=lambda: True)
    assert set(snap.keys()) == {"version", "time_utc", "db_ok"}
