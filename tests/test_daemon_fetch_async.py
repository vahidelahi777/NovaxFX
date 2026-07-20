"""Tests for the retry_fetch helper from novax.data.retry (P1.1).

No network access.  All fetchers are stubs injected at call time.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from novax.data.retry import FETCH_RETRIES, FETCH_RETRY_DELAYS, retry_fetch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sleep_spy() -> tuple[Callable[[float], None], list[float]]:
    """Returns (sleep_fn, recorded_delays)."""
    recorded: list[float] = []
    return (lambda d: recorded.append(d)), recorded


def _fail_n_times(n: int, exc_type: type[Exception] = urllib.error.URLError) -> Callable[[], str]:
    """Return a fetcher that raises exc_type for the first n calls, then returns 'ok'."""
    calls: list[int] = [0]

    def _fetcher() -> str:
        calls[0] += 1
        if calls[0] <= n:
            raise exc_type("simulated error")
        return "ok"

    return _fetcher


def _always_fail(exc_type: type[Exception] = urllib.error.URLError) -> Callable[[], Any]:
    def _fetcher() -> Any:
        raise exc_type("simulated error")

    return _fetcher


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_success_on_first_attempt() -> None:
    sleep_fn, delays = _sleep_spy()
    result = retry_fetch(lambda: "good", sleep_fn=sleep_fn)
    assert result == "good"
    assert delays == []  # no sleep when first attempt succeeds


def test_retries_on_url_error_and_returns_on_success() -> None:
    sleep_fn, delays = _sleep_spy()
    fetcher = _fail_n_times(2)  # fails twice, succeeds on 3rd
    result = retry_fetch(fetcher, sleep_fn=sleep_fn)
    assert result == "ok"
    assert len(delays) == 2
    assert delays[0] == FETCH_RETRY_DELAYS[0]
    assert delays[1] == FETCH_RETRY_DELAYS[1]


def test_retries_on_oserror() -> None:
    sleep_fn, delays = _sleep_spy()
    fetcher = _fail_n_times(1, exc_type=OSError)
    result = retry_fetch(fetcher, sleep_fn=sleep_fn)
    assert result == "ok"
    assert len(delays) == 1


def test_raises_after_max_retries() -> None:
    sleep_fn, delays = _sleep_spy()
    with pytest.raises((urllib.error.URLError, OSError)):
        retry_fetch(_always_fail(), sleep_fn=sleep_fn)
    # slept FETCH_RETRIES - 1 times (no sleep before first attempt)
    assert len(delays) == FETCH_RETRIES - 1


def test_custom_retries_and_delays() -> None:
    sleep_fn, delays = _sleep_spy()
    fetcher = _fail_n_times(2)
    result = retry_fetch(
        fetcher,
        retries=3,
        delays=(5, 10, 20),
        sleep_fn=sleep_fn,
    )
    assert result == "ok"
    assert delays == [5, 10]


def test_gives_up_with_custom_retries() -> None:
    sleep_fn, delays = _sleep_spy()
    with pytest.raises((urllib.error.URLError, OSError)):
        retry_fetch(_always_fail(), retries=2, delays=(7, 14), sleep_fn=sleep_fn)
    assert delays == [7]  # only one sleep between attempt 0 and attempt 1


def test_log_called_on_retry() -> None:
    log = MagicMock()
    sleep_fn, _ = _sleep_spy()
    fetcher = _fail_n_times(1)
    retry_fetch(fetcher, sleep_fn=sleep_fn, log=log)
    log.warning.assert_called_once()


def test_non_network_exception_not_retried() -> None:
    """ValueError should propagate immediately, not trigger retry."""
    sleep_fn, delays = _sleep_spy()

    def _bad() -> str:
        raise ValueError("not a network error")

    with pytest.raises(ValueError, match="not a network error"):
        retry_fetch(_bad, sleep_fn=sleep_fn)
    assert delays == []  # no retry
