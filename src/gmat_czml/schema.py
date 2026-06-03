"""The canonical input boundary.

gmat-czml consumes the canonical state-series schema owned by the org's format-I/O library
(orbit-formats): columns ``Epoch, X, Y, Z`` (with optional ``VX, VY, VZ``) and a metadata
spine on ``DataFrame.attrs`` (``coordinate_system`` / ``central_body`` / ``time_scale`` /
``units`` / ``interpolation`` / ``interpolation_degree`` / ``object_name``). The contract is
specified in ``docs/design/decisions.md``.

This module is the thin gmat-czml boundary over that schema. Parsing the state arrays and the
``attrs`` spine is delegated to the upstream canonical layer — ``Ephemeris.from_dataframe`` —
so there is one schema, owned upstream, and gmat-czml is a pure consumer. On top of that this
module adds the gmat-czml-specific guards the renderer needs and the upstream does not enforce:

- a **recognised reference frame** — a small superset of orbit-formats' frame alias table that
  also accepts GMAT's own ``EarthMJ2000Eq`` / ``EarthFixed`` spellings, the frames a headless
  GMAT run actually tags its states with;
- a **required time scale** — present and recognised, never assumed, since the CZML clock is
  synthesised in UTC;
- **well-formed unit metadata**;

and it turns every upstream ``ValueError`` (and every absent-but-required element) into a typed
:class:`~gmat_czml.errors.SchemaError` naming exactly what is wrong.

The validated unit of work is a :class:`CanonicalInput` — the parsed upstream ``Ephemeris``
plus the recognised frame id and whether real velocity was supplied. Several objects are an
*iterable* of canonical inputs, one per object; :func:`normalize_inputs` accepts a single
trajectory or an iterable of them and is the entry point the converters build on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from orbit_formats import Ephemeris
from orbit_formats.canonical.metadata import TIME_SCALES
from orbit_formats.convert.frames import normalize_frame

from gmat_czml.errors import (
    DuplicateObjectNameError,
    EmptyTrajectoryError,
    InvalidUnitsError,
    MalformedStateError,
    MissingColumnError,
    MissingFrameError,
    MissingTimeScaleError,
    UnknownFrameError,
    UnknownTimeScaleError,
)

__all__ = [
    "CanonicalInput",
    "normalize_inputs",
    "recognised_frame",
    "validate",
]

# The required and optional state columns of the canonical schema.
_EPOCH_COLUMN = "Epoch"
_POSITION_COLUMNS = ("X", "Y", "Z")
_VELOCITY_COLUMNS = ("VX", "VY", "VZ")
_UNIT_KEYS = ("length", "speed", "angle", "time")

# gmat-czml's frame-recognition superset. orbit-formats' ``normalize_frame`` knows the CCSDS /
# Cesium frame names (EME2000 / J2000 / GCRF / ICRF / TEME / ITRF); these are GMAT's own
# coordinate-system spellings, which a GMAT report / ephemeris tags its states with and which
# the upstream table does not carry. Only the two equatorial frames the design recognises are
# aliased — GMAT's ecliptic and epoch-of-date systems are deliberately left unrecognised rather
# than silently mapped to the wrong axes. Keys are upper-cased; lookup is via ``normalize_frame``
# first, so this only ever supplements the upstream set. The recognised id (its value) is the
# orbit-formats canonical frame id the downstream frame mapping classifies as INERTIAL / FIXED.
_GMAT_FRAME_ALIASES = {
    "EARTHMJ2000EQ": "EME2000",
    "EARTHFIXED": "ITRF",
}

# The frame names a producer can use, for the error message naming the recognised set.
_RECOGNISED_FRAMES = (
    "EME2000",
    "J2000",
    "GCRF",
    "ICRF",
    "TEME",
    "ITRF",
    "EarthMJ2000Eq",
    "EarthFixed",
)


def recognised_frame(name: str) -> str | None:
    """The canonical frame id for ``name``, or ``None`` if it is outside the recognised set.

    Case- and whitespace-insensitive. Defers to orbit-formats' shared frame alias table and
    supplements it with GMAT's own ``EarthMJ2000Eq`` / ``EarthFixed`` spellings, so the two
    libraries agree on every name they share and a GMAT-tagged state is recognised too. The
    returned id is the orbit-formats canonical frame id the downstream frame mapping consumes.
    """
    upstream = normalize_frame(name)
    if upstream is not None:
        return upstream
    return _GMAT_FRAME_ALIASES.get(name.strip().upper())


@dataclass(frozen=True)
class CanonicalInput:
    """A validated single-object trajectory ready for conversion.

    ``ephemeris`` is the parsed upstream canonical object (epochs, positions, velocities, and
    the metadata spine); ``frame`` is the recognised canonical frame id (e.g. ``"EME2000"`` /
    ``"ITRF"``); ``has_velocity`` records whether real velocity columns were supplied, since
    the schema makes velocity optional and a position-only source carries ``NaN`` velocities.
    """

    ephemeris: Ephemeris
    frame: str
    has_velocity: bool

    @property
    def object_name(self) -> str | None:
        """The object's identity, from ``attrs['object_name']`` (``None`` when undeclared)."""
        return self.ephemeris.metadata.object_name

    @property
    def central_body(self) -> str | None:
        """The central body (e.g. ``"Earth"``), from ``attrs['central_body']`` if declared."""
        return self.ephemeris.metadata.central_body


def validate(df: pd.DataFrame) -> CanonicalInput:
    """Validate a single-object canonical DataFrame and return a :class:`CanonicalInput`.

    Checks the gmat-czml guards (required columns, a recognised frame, a required-and-recognised
    time scale, well-formed units), then delegates the array / spine parsing to
    ``Ephemeris.from_dataframe``. A position-only frame (no ``VX, VY, VZ``) is accepted; the
    velocity is filled with ``NaN`` and :attr:`CanonicalInput.has_velocity` is ``False``.

    Raises a specific :class:`~gmat_czml.errors.SchemaError` for each malformed case, naming
    what is wrong rather than surfacing a bare ``KeyError`` / ``ValueError``.
    """
    _require_columns(df)
    if len(df) == 0:
        raise EmptyTrajectoryError("the state series has no samples")

    frame_id = _resolve_frame(df)
    time_scale = _resolve_time_scale(df)
    _check_units(df)
    has_velocity = _velocity_present(df)

    work = _with_resolved_attrs(df, time_scale=time_scale, pad_velocity=not has_velocity)
    try:
        ephemeris = Ephemeris.from_dataframe(work)
    except ValueError as exc:
        raise MalformedStateError(str(exc)) from exc

    return CanonicalInput(ephemeris=ephemeris, frame=frame_id, has_velocity=has_velocity)


def normalize_inputs(source: object) -> list[CanonicalInput]:
    """Validate one trajectory or a collection of them into a list of :class:`CanonicalInput`.

    Accepts a single canonical ``DataFrame``, a single upstream ``Ephemeris``, or an iterable
    of either (the multi-object contract: one trajectory per object, identity from
    ``attrs['object_name']``). Returns one :class:`CanonicalInput` per object. Object names, when
    declared, must be unique across the collection.
    """
    if isinstance(source, (pd.DataFrame, Ephemeris)):
        items: list[object] = [source]
    elif isinstance(source, Mapping):
        raise TypeError(
            "pass an iterable of per-object trajectories, not a mapping; "
            "object identity comes from attrs['object_name']"
        )
    elif isinstance(source, Iterable) and not isinstance(source, (str, bytes)):
        items = list(source)
    else:
        raise TypeError(
            f"unsupported input {type(source).__name__!r}; expected a canonical DataFrame, an "
            "orbit-formats Ephemeris, or an iterable of them"
        )

    if not items:
        raise EmptyTrajectoryError("no trajectories provided")

    results = [_validate_item(item) for item in items]
    _require_unique_object_names(results)
    return results


def _validate_item(item: object) -> CanonicalInput:
    if isinstance(item, pd.DataFrame):
        return validate(item)
    if isinstance(item, Ephemeris):
        return _from_ephemeris(item)
    raise TypeError(
        f"unsupported trajectory {type(item).__name__!r}; expected a canonical DataFrame or an "
        "orbit-formats Ephemeris"
    )


def _from_ephemeris(ephemeris: Ephemeris) -> CanonicalInput:
    """Validate an already-parsed upstream ``Ephemeris`` against the gmat-czml guards."""
    if len(ephemeris) == 0:
        raise EmptyTrajectoryError("the state series has no samples")

    metadata = ephemeris.metadata
    frame = metadata.reference_frame
    if frame is None:
        raise MissingFrameError
    frame_id = recognised_frame(frame)
    if frame_id is None:
        raise UnknownFrameError(frame, _RECOGNISED_FRAMES)

    if metadata.time_scale is None:
        raise MissingTimeScaleError
    # An Ephemeris validates its own time scale on construction, so a non-None scale is known.

    has_velocity = not bool(np.isnan(ephemeris.velocities).all())
    return CanonicalInput(ephemeris=ephemeris, frame=frame_id, has_velocity=has_velocity)


def _require_columns(df: pd.DataFrame) -> None:
    """Require ``Epoch, X, Y, Z``; reject a partial velocity declaration."""
    required = (_EPOCH_COLUMN, *_POSITION_COLUMNS)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise MissingColumnError(missing)
    present_velocity = [c for c in _VELOCITY_COLUMNS if c in df.columns]
    if present_velocity and len(present_velocity) != len(_VELOCITY_COLUMNS):
        absent = [c for c in _VELOCITY_COLUMNS if c not in df.columns]
        raise MissingColumnError(absent)


def _velocity_present(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in _VELOCITY_COLUMNS)


def _resolve_frame(df: pd.DataFrame) -> str:
    frame = df.attrs.get("coordinate_system")
    if frame is None:
        raise MissingFrameError
    frame_id = recognised_frame(str(frame))
    if frame_id is None:
        raise UnknownFrameError(str(frame), _RECOGNISED_FRAMES)
    return frame_id


def _resolve_time_scale(df: pd.DataFrame) -> str:
    scale = df.attrs.get("time_scale")
    if scale is None:
        epoch_scales = df.attrs.get("epoch_scales")
        if isinstance(epoch_scales, Mapping):
            scale = epoch_scales.get(_EPOCH_COLUMN)
    if scale is None:
        raise MissingTimeScaleError
    scale = str(scale)
    if scale not in TIME_SCALES:
        raise UnknownTimeScaleError(scale, sorted(TIME_SCALES))
    return scale


def _check_units(df: pd.DataFrame) -> None:
    units = df.attrs.get("units")
    if units is None:
        return
    if not isinstance(units, Mapping):
        raise InvalidUnitsError(f"expected a mapping, got {type(units).__name__}")
    for key in _UNIT_KEYS:
        if key not in units:
            continue
        value = units[key]
        if not isinstance(value, str) or not value.strip():
            raise InvalidUnitsError(f"{key} must be a non-empty unit string, got {value!r}")


def _with_resolved_attrs(df: pd.DataFrame, *, time_scale: str, pad_velocity: bool) -> pd.DataFrame:
    """A shallow copy with the time scale materialised and velocity padded if absent.

    The caller's DataFrame is never mutated: the copy carries its own ``attrs`` dict (with the
    resolved ``time_scale`` injected so the upstream spine parse sees it, honouring the
    ``epoch_scales`` fallback) and, for a position-only source, ``NaN`` velocity columns so the
    upstream parse — which requires all six state columns — succeeds.
    """
    work: pd.DataFrame = df.copy(deep=False)
    work.attrs = {**df.attrs, "time_scale": time_scale}
    if pad_velocity:
        nan_column = np.full(len(df), np.nan, dtype=np.float64)
        for column in _VELOCITY_COLUMNS:
            work[column] = nan_column
    return work


def _require_unique_object_names(items: Iterable[CanonicalInput]) -> None:
    seen: set[str] = set()
    for item in items:
        name = item.object_name
        if name is None:
            continue
        if name in seen:
            raise DuplicateObjectNameError(name)
        seen.add(name)
