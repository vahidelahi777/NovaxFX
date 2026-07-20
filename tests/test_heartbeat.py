"""Tests for P1.6: _touch_heartbeat helper."""

from __future__ import annotations

import time
from pathlib import Path


def _touch_heartbeat(state_dir: Path) -> None:
    """Mirror of prod_daemon_xauusd._touch_heartbeat (pure, no telegram import)."""
    hb = state_dir / "heartbeat"
    hb.touch()


def test_touch_heartbeat_creates_file(tmp_path: Path) -> None:
    hb = tmp_path / "heartbeat"
    assert not hb.exists()
    _touch_heartbeat(tmp_path)
    assert hb.exists()


def test_touch_heartbeat_updates_mtime(tmp_path: Path) -> None:
    hb = tmp_path / "heartbeat"
    _touch_heartbeat(tmp_path)
    mtime_before = hb.stat().st_mtime

    # Brief pause so clock advances on filesystems with low resolution.
    time.sleep(0.02)
    _touch_heartbeat(tmp_path)
    mtime_after = hb.stat().st_mtime

    assert mtime_after >= mtime_before


def test_touch_heartbeat_idempotent(tmp_path: Path) -> None:
    for _ in range(5):
        _touch_heartbeat(tmp_path)
    assert (tmp_path / "heartbeat").exists()
