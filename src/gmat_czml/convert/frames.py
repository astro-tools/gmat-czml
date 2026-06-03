"""Reference-frame mapping and the ground-track rotation.

Two things the rest of the converter needs from a recognised source frame:

- **The CZML reference frame it renders in.** :func:`czml_reference_frame` classifies a
  recognised canonical frame id (``CanonicalInput.frame``) as ``INERTIAL`` or ``FIXED`` — the
  ``referenceFrame`` Cesium reads off the position property. The inertial frames differ from
  Cesium's ICRF only by a frame bias / small rotation far below visualization tolerance, so they
  map uncorrected; a recognised id with no mapping is rejected with a typed error, not guessed.
- **The sub-satellite ground point.** :func:`subsatellite_track` projects the trajectory to
  geodetic longitude / latitude / height at each epoch. The inertial -> Earth-fixed rotation
  (precession / nutation / Earth-orientation) and the WGS84 ECEF -> geodetic step are both
  delegated to the format-I/O library's astropy-backed helpers; gmat-czml carries neither of its
  own. A fixed source short-circuits the rotation to an identity and never loads astropy.
"""

from __future__ import annotations

import numpy as np
from czml3.enums import ReferenceFrames
from numpy.typing import NDArray
from orbit_formats.convert.frames import rotate_state
from orbit_formats.convert.geodetic import cartesian_to_geodetic

from gmat_czml.errors import InvalidUnitsError, UnmappableFrameError
from gmat_czml.schema import CanonicalInput

__all__ = ["czml_reference_frame", "subsatellite_track"]

# Canonical frame ids (from orbit-formats' alias table, via schema.recognised_frame) grouped by the
# CZML reference frame they render in. Cesium's inertial frame is ICRF; EME2000 differs by a
# tens-of-milliarcsecond bias and TEME by a small rotation — both far below visualization tolerance,
# so they map to INERTIAL uncorrected (D4). ITRF is the Earth-fixed frame.
_INERTIAL_FRAMES = frozenset({"EME2000", "GCRF", "ICRF", "TEME"})
_FIXED_FRAMES = frozenset({"ITRF"})

# The Earth-fixed frame the sub-satellite projection rotates into before the geodetic step.
_ECEF_FRAME = "ITRF"

# Declared length unit -> kilometres (keys upper-cased). The rotation and geodetic helpers are
# km-native, but ``Ephemeris.positions`` carries the producer's declared unit unchanged, so the
# ground track converts here. Only the two physically standard length units are supported; any other
# is rejected rather than guessed, consistent with the schema's no-guessing stance.
_LENGTH_TO_KM = {"KM": 1.0, "M": 1.0e-3}
_SUPPORTED_LENGTH_UNITS = ("km", "m")


def czml_reference_frame(frame_id: str) -> ReferenceFrames:
    """The CZML reference frame a recognised canonical frame id renders in.

    ``frame_id`` is an orbit-formats canonical id, as produced by
    :func:`gmat_czml.schema.recognised_frame` (``CanonicalInput.frame``). The inertial frames
    ``EME2000`` / ``GCRF`` / ``ICRF`` / ``TEME`` map to ``INERTIAL`` and the Earth-fixed ``ITRF``
    to ``FIXED``. A recognised id with no mapping raises
    :class:`~gmat_czml.errors.UnmappableFrameError` — the typed boundary between frames the
    converter can render and those it cannot.
    """
    if frame_id in _INERTIAL_FRAMES:
        return ReferenceFrames.INERTIAL
    if frame_id in _FIXED_FRAMES:
        return ReferenceFrames.FIXED
    raise UnmappableFrameError(frame_id, sorted(_INERTIAL_FRAMES | _FIXED_FRAMES))


def subsatellite_track(
    item: CanonicalInput,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """The geodetic sub-satellite track of one trajectory: longitude, latitude, height.

    Rotates the source state to the Earth-fixed ``ITRF`` frame (precession / nutation /
    Earth-orientation via orbit-formats' ``rotate_state``; a fixed source short-circuits to an
    identity) and projects it onto the WGS84 ellipsoid with its ``cartesian_to_geodetic``. Returns
    three length-N ``float64`` arrays: geodetic longitude and latitude in **degrees**
    (east-positive longitude) and ellipsoidal height in **km**, one per epoch.

    Velocity is irrelevant to the sub-satellite point — the position rotation does not depend on
    it — so a zero velocity is passed and the rotated velocity discarded, which also lets a
    position-only (``NaN``-velocity) source project cleanly. Raises
    :class:`~gmat_czml.errors.InvalidUnitsError` if the declared length unit is unsupported.
    """
    positions_km = _positions_km(item)
    ecef, _ = rotate_state(
        positions_km,
        np.zeros_like(positions_km),
        item.ephemeris.epochs,
        time_scale=item.time_scale,
        from_frame=item.frame,
        to_frame=_ECEF_FRAME,
    )
    return cartesian_to_geodetic(ecef)


def _positions_km(item: CanonicalInput) -> NDArray[np.float64]:
    """The trajectory's positions in kilometres, converting from the declared length unit."""
    unit = item.ephemeris.metadata.units.length
    factor = _LENGTH_TO_KM.get(unit.strip().upper())
    if factor is None:
        supported = ", ".join(_SUPPORTED_LENGTH_UNITS)
        raise InvalidUnitsError(
            f"length unit {unit!r} is not supported by the ground-track projection; "
            f"supported units: {supported}"
        )
    positions = np.asarray(item.ephemeris.positions, dtype=np.float64)
    return np.asarray(positions * factor, dtype=np.float64)
