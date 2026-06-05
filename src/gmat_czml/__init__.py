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
from gmat_czml.convert.contacts import Contact, GroundStation
from gmat_czml.document import CzmlDocument
from gmat_czml.errors import (
    AmbiguousAttitudeTargetError,
    AmbiguousManeuverTargetError,
    AttitudeFrameError,
    ContactEntityCollisionError,
    DuplicateObjectNameError,
    EmptyAttitudeError,
    EmptyTrajectoryError,
    GmatCzmlError,
    InvalidUnitsError,
    IonUploadError,
    MalformedStateError,
    ManeuverOutsideTrajectoryError,
    MissingColumnError,
    MissingFrameError,
    MissingTimeScaleError,
    SchemaError,
    UnknownContactTargetError,
    UnknownFrameError,
    UnknownStyleError,
    UnknownTimeScaleError,
    UnsupportedAttitudeTypeError,
)
from gmat_czml.schema import CanonicalInput, normalize_inputs, recognised_frame, validate
from gmat_czml.styles import (
    PRESET_NAMES,
    RGBA,
    AttitudeStyle,
    ContactStyle,
    ImageBillboard,
    LabelStyle,
    LineStyle,
    ManeuverStyle,
    PathStyle,
    PointStyle,
    Style,
    TrackStyle,
    preset,
)

__all__ = [
    "PRESET_NAMES",
    "RGBA",
    "AmbiguousAttitudeTargetError",
    "AmbiguousManeuverTargetError",
    "AttitudeFrameError",
    "AttitudeStyle",
    "CanonicalInput",
    "Contact",
    "ContactEntityCollisionError",
    "ContactStyle",
    "CzmlDocument",
    "DuplicateObjectNameError",
    "EmptyAttitudeError",
    "EmptyTrajectoryError",
    "GmatCzmlError",
    "GroundStation",
    "ImageBillboard",
    "InvalidUnitsError",
    "IonUploadError",
    "LabelStyle",
    "LineStyle",
    "MalformedStateError",
    "ManeuverOutsideTrajectoryError",
    "ManeuverStyle",
    "MissingColumnError",
    "MissingFrameError",
    "MissingTimeScaleError",
    "PathStyle",
    "PointStyle",
    "SchemaError",
    "Style",
    "TrackStyle",
    "TrajectorySource",
    "UnknownContactTargetError",
    "UnknownFrameError",
    "UnknownStyleError",
    "UnknownTimeScaleError",
    "UnsupportedAttitudeTypeError",
    "__version__",
    "normalize_inputs",
    "preset",
    "recognised_frame",
    "to_czml",
    "validate",
]

__version__ = "0.2.0"
