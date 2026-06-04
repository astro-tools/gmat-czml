"""Tests for tolerance-bounded decimation (``gmat_czml.convert.sampling``).

The geometric guarantee is checked against an **independent** point-to-polyline distance computed by
brute force (every original sample's nearest point on the kept polyline), not by reusing the
Douglas-Peucker recursion: a decimated path must stay within the stated cross-track tolerance of the
full sample set on known curves (a circle, a 3D helix) and reduce the sample count measurably on a
representative LEO ephemeris. The remaining tests pin the endpoints / ``min_samples`` floor, the
edge cases, and the soft-budget reporting.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from gmat_czml.convert.sampling import (
    DEFAULT_PAYLOAD_BUDGET_BYTES,
    DEFAULT_TOLERANCE_KM,
    decimate,
)


def _circle(n: int, *, radius: float = 7000.0) -> NDArray[np.float64]:
    """An open planar arc of ``n`` samples (first != last), in km."""
    theta = np.linspace(0.0, 1.9 * np.pi, n)
    return np.column_stack([radius * np.cos(theta), radius * np.sin(theta), np.zeros(n)])


def _helix(n: int, *, radius: float = 7000.0, pitch: float = 500.0) -> NDArray[np.float64]:
    """A 3D helix of ``n`` samples - exercises genuinely out-of-plane cross-track distance."""
    theta = np.linspace(0.0, 4.0 * np.pi, n)
    return np.column_stack([radius * np.cos(theta), radius * np.sin(theta), pitch * theta])


def _leo_orbit(n: int) -> NDArray[np.float64]:
    """One revolution of a ~400 km circular orbit inclined 51.6°, ``n`` samples, in km."""
    r = 6778.0
    inc = np.radians(51.6)
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.column_stack(
        [r * np.cos(theta), r * np.sin(theta) * np.cos(inc), r * np.sin(theta) * np.sin(inc)]
    )


def _max_polyline_deviation(positions: NDArray[np.float64], indices: NDArray[np.intp]) -> float:
    """Max distance of any original sample to the kept polyline (brute force over kept segments)."""
    kept = positions[indices]
    best = np.full(positions.shape[0], np.inf)
    for s in range(kept.shape[0] - 1):
        a, b = kept[s], kept[s + 1]
        chord = b - a
        denom = float(chord @ chord)
        relative = positions - a
        if denom == 0.0:
            distances = np.linalg.norm(relative, axis=1)
        else:
            t = np.clip((relative @ chord) / denom, 0.0, 1.0)
            distances = np.linalg.norm(positions - (a + np.outer(t, chord)), axis=1)
        best = np.minimum(best, distances)
    return float(best.max())


# --- the geometric bound on known curves --------------------------------------------------


def test_circle_stays_within_tolerance_and_reduces() -> None:
    pts = _circle(400)
    result = decimate(pts, tolerance=1.0)
    assert _max_polyline_deviation(pts, result.indices) <= 1.0 + 1e-9
    assert result.kept < result.total


def test_helix_3d_stays_within_tolerance() -> None:
    pts = _helix(600)
    result = decimate(pts, tolerance=5.0)
    assert _max_polyline_deviation(pts, result.indices) <= 5.0 + 1e-9
    assert 2 < result.kept < result.total


def test_tighter_tolerance_keeps_more_samples() -> None:
    pts = _circle(400)
    coarse = decimate(pts, tolerance=2.0)
    fine = decimate(pts, tolerance=0.5)
    assert fine.kept > coarse.kept


def test_leo_ephemeris_reduces_measurably_within_bound() -> None:
    pts = _leo_orbit(600)
    result = decimate(pts, tolerance=DEFAULT_TOLERANCE_KM)
    assert _max_polyline_deviation(pts, result.indices) <= DEFAULT_TOLERANCE_KM + 1e-9
    assert result.reduction > 0.5  # a 1 km bound on a ~6778 km LEO drops most samples
    assert result.kept < result.total


# --- endpoints, the min_samples floor, and edge cases -------------------------------------


def test_endpoints_are_always_kept() -> None:
    result = decimate(_circle(40), tolerance=5.0)
    assert int(result.indices[0]) == 0
    assert int(result.indices[-1]) == 39


def test_min_samples_floor_keeps_support() -> None:
    # A straight line is collinear, so the tolerance alone would keep only the two endpoints; the
    # floor keeps degree + 1 samples so a degree-5 interpolation has support.
    line = np.column_stack([np.linspace(0.0, 1000.0, 20), np.zeros(20), np.zeros(20)])
    result = decimate(line, tolerance=1.0, min_samples=6)
    assert result.kept == 6
    assert _max_polyline_deviation(line, result.indices) <= 1e-9


def test_huge_tolerance_drops_to_endpoints() -> None:
    result = decimate(_circle(50), tolerance=1.0e9)
    np.testing.assert_array_equal(result.indices, [0, 49])


def test_zero_tolerance_keeps_every_curved_sample() -> None:
    pts = _circle(30)
    result = decimate(pts, tolerance=0.0)
    np.testing.assert_array_equal(result.indices, np.arange(30))


def test_collinear_path_reduces_to_endpoints() -> None:
    line = np.column_stack([np.arange(10.0), 2.0 * np.arange(10.0), -np.arange(10.0)])
    result = decimate(line, tolerance=1e-9)
    np.testing.assert_array_equal(result.indices, [0, 9])


def test_closed_loop_chord_is_handled() -> None:
    # A full revolution: the first and last samples coincide, so the initial chord is degenerate.
    theta = np.linspace(0.0, 2.0 * np.pi, 60)
    pts = np.column_stack([7000.0 * np.cos(theta), 7000.0 * np.sin(theta), np.zeros(60)])
    result = decimate(pts, tolerance=1.0)
    assert result.kept > 2
    assert _max_polyline_deviation(pts, result.indices) <= 1.0 + 1e-9


def test_exactly_closed_chord_uses_point_distance() -> None:
    # First and last samples identical, so the initial chord is exactly degenerate (a == b) and the
    # distance falls back to point-to-point — an exactly-closed loop, not the cos/sin near-closure.
    pts = np.array(
        [
            [7000.0, 0.0, 0.0],
            [0.0, 7000.0, 0.0],
            [-7000.0, 0.0, 0.0],
            [0.0, -7000.0, 0.0],
            [7000.0, 0.0, 0.0],
        ]
    )
    result = decimate(pts, tolerance=1.0)
    assert result.kept > 2
    assert _max_polyline_deviation(pts, result.indices) <= 1.0 + 1e-9


@pytest.mark.parametrize("n", [0, 1, 2])
def test_short_paths_keep_everything(n: int) -> None:
    result = decimate(np.zeros((n, 3)), tolerance=1.0)
    np.testing.assert_array_equal(result.indices, np.arange(n))
    assert result.kept == n


# --- validation ----------------------------------------------------------------------------


def test_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError):
        decimate(_circle(5), tolerance=-1.0)


def test_rejects_min_samples_below_two() -> None:
    with pytest.raises(ValueError):
        decimate(_circle(5), min_samples=1)


def test_rejects_positions_that_are_not_n_by_3() -> None:
    with pytest.raises(ValueError):
        decimate(np.zeros((5, 2)))
    with pytest.raises(ValueError):
        decimate(np.zeros(5))


# --- the soft payload budget ---------------------------------------------------------------


def test_small_path_is_within_the_default_budget() -> None:
    result = decimate(_circle(100), tolerance=1.0)
    assert result.payload_budget == DEFAULT_PAYLOAD_BUDGET_BYTES
    assert result.within_budget is True
    assert result.estimated_bytes == result.kept * 64


def test_over_budget_is_reported_not_enforced() -> None:
    pts = _circle(400)
    result = decimate(pts, tolerance=1.0, payload_budget=10)
    assert result.within_budget is False
    assert result.estimated_bytes > 10
    # The tolerance is still respected despite the tiny budget — the budget never overrides it.
    assert _max_polyline_deviation(pts, result.indices) <= 1.0 + 1e-9


def test_reduction_is_the_dropped_fraction() -> None:
    result = decimate(_circle(400), tolerance=1.0)
    assert 0.0 < result.reduction < 1.0
    assert result.reduction == pytest.approx(1.0 - result.kept / result.total)


def test_reduction_is_zero_when_nothing_is_dropped() -> None:
    assert decimate(_circle(30), tolerance=0.0).reduction == 0.0
    assert decimate(np.zeros((0, 3))).reduction == 0.0
