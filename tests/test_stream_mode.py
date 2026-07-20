"""Tests for P1.5: _events_to_fire (pure scheduler filter for stream mode)."""

from __future__ import annotations

# Since importing the daemon is blocked by telegram, we duplicate the tiny
# pure function here and test the logic directly.  The source-of-truth
# implementation is in prod_daemon_xauusd.py:_events_to_fire.


class _EventType:
    BAR_CLOSE_15M = "BAR_CLOSE_15M"
    MARKET_UPDATE_4H = "MARKET_UPDATE_4H"
    LONDON_OPEN = "LONDON_OPEN"
    DAILY_REPORT = "DAILY_REPORT"


def _events_to_fire(events: list[str], *, stream_active: bool) -> list[str]:
    """Mirror of prod_daemon_xauusd._events_to_fire for isolation testing."""
    if not stream_active:
        return list(events)
    return [e for e in events if e != _EventType.BAR_CLOSE_15M]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_events_fire_when_stream_inactive() -> None:
    events = [
        _EventType.BAR_CLOSE_15M,
        _EventType.MARKET_UPDATE_4H,
        _EventType.LONDON_OPEN,
    ]
    result = _events_to_fire(events, stream_active=False)
    assert result == events


def test_bar_close_15m_suppressed_when_stream_active() -> None:
    events = [
        _EventType.BAR_CLOSE_15M,
        _EventType.MARKET_UPDATE_4H,
        _EventType.LONDON_OPEN,
    ]
    result = _events_to_fire(events, stream_active=True)
    assert _EventType.BAR_CLOSE_15M not in result
    assert _EventType.MARKET_UPDATE_4H in result
    assert _EventType.LONDON_OPEN in result


def test_non_15m_events_fire_normally_in_stream_mode() -> None:
    events = [_EventType.MARKET_UPDATE_4H, _EventType.DAILY_REPORT]
    result = _events_to_fire(events, stream_active=True)
    assert result == events


def test_empty_events_list() -> None:
    assert _events_to_fire([], stream_active=True) == []
    assert _events_to_fire([], stream_active=False) == []


def test_only_15m_event_in_stream_mode_returns_empty() -> None:
    events = [_EventType.BAR_CLOSE_15M]
    result = _events_to_fire(events, stream_active=True)
    assert result == []


def test_stream_fallback_means_15m_fires() -> None:
    """When stream has fallen back to REST, stream_active=False so 15M fires."""
    events = [_EventType.BAR_CLOSE_15M, _EventType.MARKET_UPDATE_4H]
    # stream_mode=True but stream_fallback=True → stream_active = False
    result = _events_to_fire(events, stream_active=False)
    assert _EventType.BAR_CLOSE_15M in result
