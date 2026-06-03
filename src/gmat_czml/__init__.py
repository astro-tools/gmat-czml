"""gmat-czml — convert canonical trajectories to CZML for browser-based Cesium visualization.

gmat-czml takes an already-computed trajectory in the canonical state-series form (the schema
the org's format-I/O library emits, and the schema a headless GMAT run produces) and turns it
into a CZML document a Cesium client can animate. It does not propagate or compute orbits — the
producer is the source of geometric truth.

This module is the public surface. The conversion internals live under
:mod:`gmat_czml.convert`. The input contract and the design decisions are recorded in
``docs/design/decisions.md``.
"""

from __future__ import annotations

from gmat_czml.assembly import TrajectorySource, to_czml
from gmat_czml.document import CzmlDocument
from gmat_czml.errors import (
    DuplicateObjectNameError,
    EmptyTrajectoryError,
    GmatCzmlError,
    InvalidUnitsError,
    MalformedStateError,
    MissingColumnError,
    MissingFrameError,
    MissingTimeScaleError,
    SchemaError,
    UnknownFrameError,
    UnknownTimeScaleError,
)
from gmat_czml.schema import CanonicalInput, normalize_inputs, recognised_frame, validate
from gmat_czml.styles import Style

__all__ = [
    "CanonicalInput",
    "CzmlDocument",
    "DuplicateObjectNameError",
    "EmptyTrajectoryError",
    "GmatCzmlError",
    "InvalidUnitsError",
    "MalformedStateError",
    "MissingColumnError",
    "MissingFrameError",
    "MissingTimeScaleError",
    "SchemaError",
    "Style",
    "TrajectorySource",
    "UnknownFrameError",
    "UnknownTimeScaleError",
    "__version__",
    "normalize_inputs",
    "recognised_frame",
    "to_czml",
    "validate",
]

__version__ = "0.1.0"
