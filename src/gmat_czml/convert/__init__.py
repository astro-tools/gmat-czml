"""Per-entity converters from the canonical trajectory to CZML packets.

One module per concern: :mod:`~gmat_czml.convert.time` (time-scale to UTC and clock synthesis),
:mod:`~gmat_czml.convert.frames` (frame mapping and the ground-track rotation),
:mod:`~gmat_czml.convert.sampling` (tolerance-bounded decimation),
:mod:`~gmat_czml.convert.ephemeris` (state to position + path),
:mod:`~gmat_czml.convert.groundtrack` (the geodetic polyline),
:mod:`~gmat_czml.convert.contacts` (observer placement and the per-window access link), and
:mod:`~gmat_czml.convert.maneuvers` (impulsive markers and finite-burn arcs on the orbit).
"""

from __future__ import annotations
