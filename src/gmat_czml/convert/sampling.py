"""Tolerance-bounded decimation.

Drops samples a client can interpolate back within a stated geometric error bound, keeping the
document small enough to load quickly and to fit an attachment. :func:`decimate` runs an iterative
3D Douglas-Peucker pass on the **cross-track** (perpendicular-to-chord) distance: it keeps the
smallest subset of a sampled path whose polyline stays within ``tolerance`` of every dropped
sample. The two endpoints are always kept, and a ``min_samples`` floor (the converter sets it to
``interpolation_degree + 1``) keeps enough support for the declared Lagrange / Hermite curve, whose
algorithm and degree travel onto the CZML unchanged.

The tolerance is the hard bound; the payload budget is a soft target reported on the result, never
traded against the tolerance — at the tolerance the result is already the fewest samples within the
bound. The pass is pure geometry on an ``(N, 3)`` array: positions and tolerance share a unit (the
converter passes canonical km), so it carries no schema or unit logic of its own.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_PAYLOAD_BUDGET_BYTES",
    "DEFAULT_TOLERANCE_KM",
    "DecimationResult",
    "decimate",
]

# The cross-track distance (in the unit of the positions) a dropped sample may sit from the kept
# polyline — roughly visualization tolerance. The converter passes positions in canonical km.
DEFAULT_TOLERANCE_KM: float = 1.0

# The soft payload target. The tolerance is the hard bound, so a result that exceeds this is
# reported (DecimationResult.within_budget) rather than decimated past the tolerance to fit.
DEFAULT_PAYLOAD_BUDGET_BYTES: int = 5_000_000

# Rough serialized cost of one CZML cartesian sample — an epoch offset plus x / y / z as JSON
# numbers with separators. Only the soft-budget estimate uses it, so an order-of-magnitude figure
# is enough; it is deliberately not tied to czml3's exact formatting.
_BYTES_PER_SAMPLE: int = 64


@dataclass(frozen=True)
class DecimationResult:
    """The outcome of a decimation pass.

    ``indices`` are the kept sample indices into the original series — sorted, both endpoints
    included — to apply to the position / epoch / velocity arrays. ``total`` is the original sample
    count and ``tolerance`` the cross-track bound that was applied (in the unit of the positions).
    ``estimated_bytes`` is a rough serialized payload of the kept samples, checked against the soft
    ``payload_budget``.
    """

    indices: NDArray[np.intp]
    total: int
    tolerance: float
    estimated_bytes: int
    payload_budget: int

    @property
    def kept(self) -> int:
        """The number of samples kept."""
        return int(self.indices.size)

    @property
    def within_budget(self) -> bool:
        """Whether the estimated payload fits the soft budget."""
        return self.estimated_bytes <= self.payload_budget

    @property
    def reduction(self) -> float:
        """The fraction of samples dropped, in ``[0, 1]`` (``0.0`` when nothing was dropped)."""
        if self.total == 0:
            return 0.0
        return 1.0 - self.kept / self.total


def decimate(
    positions: NDArray[np.float64],
    *,
    tolerance: float = DEFAULT_TOLERANCE_KM,
    min_samples: int = 2,
    payload_budget: int = DEFAULT_PAYLOAD_BUDGET_BYTES,
) -> DecimationResult:
    """Decimate a sampled path to the indices a client can interpolate back within ``tolerance``.

    Keeps the smallest subset of ``positions`` (an ``(N, 3)`` array) whose polyline stays within
    ``tolerance`` cross-track (perpendicular) distance of every dropped sample — an iterative 3D
    Douglas-Peucker pass. The two endpoints are always kept, and at least ``min_samples`` samples
    are retained even where the tolerance alone would drop more, so a Lagrange / Hermite curve of
    degree ``min_samples - 1`` keeps enough support.

    ``tolerance`` is in the unit of ``positions`` (the converter passes canonical km, so the default
    is :data:`DEFAULT_TOLERANCE_KM`). It is the hard bound; ``payload_budget`` is only reported on
    the result, never decimated past the tolerance to meet. Returns a :class:`DecimationResult`.

    Raises :class:`ValueError` for a negative ``tolerance``, a ``min_samples`` below 2, or a
    ``positions`` array that is not ``(N, 3)``.
    """
    if tolerance < 0.0:
        raise ValueError(f"tolerance must be non-negative, got {tolerance!r}")
    if min_samples < 2:
        raise ValueError(f"min_samples must be at least 2, got {min_samples!r}")

    pts = np.asarray(positions, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"positions must be an (N, 3) array, got shape {pts.shape}")

    indices = _douglas_peucker(pts, tolerance, min_samples)
    return DecimationResult(
        indices=indices,
        total=int(pts.shape[0]),
        tolerance=tolerance,
        estimated_bytes=int(indices.size) * _BYTES_PER_SAMPLE,
        payload_budget=payload_budget,
    )


def _douglas_peucker(
    positions: NDArray[np.float64], tolerance: float, min_samples: int
) -> NDArray[np.intp]:
    """Indices kept by an iterative Douglas-Peucker pass with a ``min_samples`` floor."""
    n = positions.shape[0]
    if n <= 2:
        return np.arange(n, dtype=np.intp)

    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    kept_count = 2

    # Max-heap of splittable segments keyed by their farthest interior point. heapq is a min-heap,
    # so distances are pushed negated; (i, j) break ties deterministically and the split point k is
    # cached so the peek is O(1).
    heap: list[tuple[float, int, int, int]] = []

    def consider(i: int, j: int) -> None:
        if j - i < 2:  # no interior sample to split on
            return
        k, dist = _farthest(positions, i, j)
        heapq.heappush(heap, (-dist, i, j, k))

    consider(0, n - 1)
    while heap:
        neg_dist, i, j, k = heap[0]
        # Stop once the worst remaining segment is within tolerance and the floor is met; until the
        # floor is met, keep splitting the most-significant segment even within tolerance.
        if -neg_dist <= tolerance and kept_count >= min_samples:
            break
        heapq.heappop(heap)
        keep[k] = True
        kept_count += 1
        consider(i, k)
        consider(k, j)

    return np.flatnonzero(keep).astype(np.intp)


def _farthest(positions: NDArray[np.float64], i: int, j: int) -> tuple[int, float]:
    """The interior index of segment ``[i, j]`` farthest from its chord, and that distance."""
    interior = positions[i + 1 : j]
    distances = _segment_distance(interior, positions[i], positions[j])
    offset = int(np.argmax(distances))
    return i + 1 + offset, float(distances[offset])


def _segment_distance(
    points: NDArray[np.float64], a: NDArray[np.float64], b: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Distance from each of ``points`` to the line segment ``[a, b]`` (cross-track deviation).

    Uses the nearest point on the segment (the projection clamped to the endpoints), so the value
    is the true deviation of a dropped sample from the kept polyline — including the degenerate
    closed-orbit chord ``a == b``, where it reduces to the distance to ``a``.
    """
    chord = b - a
    relative = points - a
    chord_sq = float(chord @ chord)
    if chord_sq == 0.0:
        return np.asarray(np.linalg.norm(relative, axis=1), dtype=np.float64)
    t = np.clip((relative @ chord) / chord_sq, 0.0, 1.0)
    projected = a + np.outer(t, chord)
    return np.asarray(np.linalg.norm(points - projected, axis=1), dtype=np.float64)
