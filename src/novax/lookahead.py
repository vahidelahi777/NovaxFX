"""No-lookahead testing helpers.

A feature has lookahead if its value at time t changes when future data is removed.
`assert_no_lookahead` recomputes a feature over progressively truncated history and
fails if any in-sample value disagrees with the value computable using only data
up to that point. This is the single most important test class for a research
platform — lookahead is the likeliest cause of a fake FX edge.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

__all__ = ["FeatureFn", "assert_no_lookahead", "find_lookahead_indices"]


class FeatureFn[T](Protocol):
    """Maps a history of bars/rows to a per-row feature series of equal length."""

    def __call__(self, history: Sequence[T]) -> Sequence[float]: ...


def find_lookahead_indices[T](
    feature_fn: FeatureFn[T], data: Sequence[T], *, check_indices: Sequence[int] | None = None,
    tol: float = 1e-12,
) -> list[int]:
    """Return indices where the feature peeks into the future.

    For each checked index i, compares feature_fn(data)[i] (full history) against
    feature_fn(data[:i+1])[i] (truncated). A clean feature yields the same value;
    a leaky one differs.
    """
    full = list(feature_fn(data))
    if len(full) != len(data):
        raise ValueError("feature_fn must return one value per input row")
    idxs = range(len(data)) if check_indices is None else check_indices
    bad: list[int] = []
    for i in idxs:
        truncated = list(feature_fn(data[: i + 1]))
        if len(truncated) != i + 1:
            raise ValueError("feature_fn must return one value per input row (truncated)")
        a, b = full[i], truncated[i]
        # NaN-safe-ish comparison
        if (a != a and b != b):  # both NaN
            continue
        if abs(a - b) > tol:
            bad.append(i)
    return bad


def assert_no_lookahead[T](
    feature_fn: FeatureFn[T], data: Sequence[T], *, check_indices: Sequence[int] | None = None,
    tol: float = 1e-12,
) -> None:
    bad = find_lookahead_indices(feature_fn, data, check_indices=check_indices, tol=tol)
    if bad:
        raise AssertionError(
            f"lookahead detected at indices {bad[:10]}"
            f"{'...' if len(bad) > 10 else ''} ({len(bad)} total): "
            "feature value at t depends on data after t."
        )
