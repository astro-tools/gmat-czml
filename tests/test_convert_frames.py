"""Tests for frame mapping and the ground-track rotation (``gmat_czml.convert.frames``).

The frame rotation and the geodetic projection are delegated to orbit-formats (already tested
there), so these pin the gmat-czml layer: that a recognised frame id maps to the right CZML
reference frame, that an unmappable frame is rejected, that the inertial -> ITRF -> geodetic path is
wired with the right from / to frames, time scale, and length-unit conversion, and that an inertial
and a fixed expression of the *same* physical state land on the same sub-satellite point.

The independent sub-satellite oracle is astropy — the org's "astropy is the test oracle, not the
implementation" pattern — reaching geodetic longitude / latitude through its own ITRS transform and
``EarthLocation`` (ERFA) geodetic, a different code path than orbit-formats' iteration. It is
available transitively via orbit-formats and guarded with :func:`importorskip`. Earth-orientation
constants are exercised against a safely-past epoch (2024-06-01).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from czml3.enums import ReferenceFrames
from numpy.typing import NDArray

from gmat_czml.convert.frames import czml_reference_frame, subsatellite_track
from gmat_czml.errors import InvalidUnitsError, UnmappableFrameError
from gmat_czml.schema import CanonicalInput, validate

# WGS84 equatorial radius (km) — orbit-formats' default ellipsoid, used to place analytic points.
_WGS84_A = 6378.137


def _epochs(*times: str) -> NDArray[np.datetime64]:
    """A ``datetime64[ns]`` epoch array from ISO strings."""
    return np.array(times, dtype="datetime64[ns]")


def _input(
    positions: NDArray[np.float64],
    *,
    frame: str = "EME2000",
    time_scale: str = "UTC",
    length: str = "km",
    epochs: NDArray[np.datetime64] | None = None,
) -> CanonicalInput:
    """A validated single-object input over ``positions`` (an ``(N, 3)`` array, in ``length``).

    ``epochs`` defaults to an hourly grid; tests that compare against an oracle pass the same
    epoch array used to build the oracle, since the Earth-fixed rotation is epoch-dependent.
    """
    n = len(positions)
    if epochs is None:
        epochs = np.array(
            pd.date_range("2024-06-01T00:00:00", periods=n, freq="3600s"), dtype="datetime64[ns]"
        )
    df = pd.DataFrame(
        {
            "Epoch": epochs,
            "X": positions[:, 0],
            "Y": positions[:, 1],
            "Z": positions[:, 2],
        }
    )
    df.attrs.update(
        {
            "object_name": "Sat",
            "central_body": "Earth",
            "coordinate_system": frame,
            "time_scale": time_scale,
            "units": {"length": length, "speed": "km/s"},
        }
    )
    return validate(df)


# --- czml_reference_frame -----------------------------------------------------------------


@pytest.mark.parametrize("frame_id", ["EME2000", "GCRF", "ICRF", "TEME"])
def test_inertial_frames_map_to_inertial(frame_id: str) -> None:
    assert czml_reference_frame(frame_id) is ReferenceFrames.INERTIAL


def test_itrf_maps_to_fixed() -> None:
    assert czml_reference_frame("ITRF") is ReferenceFrames.FIXED


def test_gmat_spellings_map_through_the_canonical_id() -> None:
    # The GMAT spellings normalise to EME2000 / ITRF at validation, so the recognised id maps.
    pos = np.array([[_WGS84_A, 0.0, 0.0]])
    assert (
        czml_reference_frame(_input(pos, frame="EarthMJ2000Eq").frame) is ReferenceFrames.INERTIAL
    )
    assert czml_reference_frame(_input(pos, frame="EarthFixed").frame) is ReferenceFrames.FIXED


def test_unmappable_frame_is_rejected() -> None:
    with pytest.raises(UnmappableFrameError):
        czml_reference_frame("EarthMeanEcliptic")


# --- subsatellite_track: the fixed (ITRF) path is analytic --------------------------------


def test_fixed_source_geodetic_is_analytic() -> None:
    # An ITRF source is already Earth-fixed: the rotation is an identity and the geodetic point is
    # the closed-form WGS84 projection. Equator/prime-meridian, equator/90E, and +1000 km altitude.
    positions = np.array(
        [
            [_WGS84_A, 0.0, 0.0],
            [0.0, _WGS84_A, 0.0],
            [_WGS84_A + 1000.0, 0.0, 0.0],
        ]
    )
    lon, lat, height = subsatellite_track(_input(positions, frame="ITRF"))
    np.testing.assert_allclose(lon, [0.0, 90.0, 0.0], atol=1e-9)
    np.testing.assert_allclose(lat, [0.0, 0.0, 0.0], atol=1e-9)
    np.testing.assert_allclose(height, [0.0, 0.0, 1000.0], atol=1e-6)


def test_length_unit_metres_matches_kilometres() -> None:
    # The same physical state declared in metres must project to the same sub-satellite point.
    positions_km = np.array([[_WGS84_A + 500.0, 0.0, 0.0], [0.0, _WGS84_A + 500.0, 200.0]])
    in_km = subsatellite_track(_input(positions_km, frame="ITRF", length="km"))
    in_m = subsatellite_track(_input(positions_km * 1000.0, frame="ITRF", length="m"))
    np.testing.assert_allclose(in_m, in_km, atol=1e-9)


def test_unsupported_length_unit_is_rejected() -> None:
    item = _input(np.array([[_WGS84_A, 0.0, 0.0]]), frame="ITRF", length="AU")
    with pytest.raises(InvalidUnitsError):
        subsatellite_track(item)


# --- subsatellite_track: the inertial path ------------------------------------------------


def test_inertial_and_fixed_agree_for_the_same_state() -> None:
    # Build the same physical state two ways — an inertial source, and the Earth-fixed state it
    # rotates into — and confirm both land on the same sub-satellite point. Pins the from / to
    # frame and time-scale wiring without an external oracle.
    from orbit_formats.convert.frames import rotate_state

    epochs = _epochs("2024-06-01T00:00:00", "2024-06-01T06:00:00")
    inertial_pos = np.array([[7000.0, 1000.0, 500.0], [-3000.0, 6500.0, 1200.0]])
    ecef, _ = rotate_state(
        inertial_pos,
        np.zeros_like(inertial_pos),
        epochs,
        time_scale="UTC",
        from_frame="EME2000",
        to_frame="ITRF",
    )
    inertial = subsatellite_track(_input(inertial_pos, frame="EME2000", epochs=epochs))
    fixed = subsatellite_track(_input(ecef, frame="ITRF", epochs=epochs))
    np.testing.assert_allclose(inertial, fixed, atol=1e-9)


def test_time_scale_flows_into_the_rotation() -> None:
    # The same numeric epoch read as UTC vs TAI is 37 s apart in absolute time at this epoch, so the
    # Earth has rotated ~0.15 deg between them. A different sub-satellite longitude proves the scale
    # reaches the rotation rather than being dropped.
    positions = np.array([[7000.0, 0.0, 0.0]])
    epochs = _epochs("2024-06-01T00:00:00")
    utc_lon = subsatellite_track(_input(positions, frame="GCRF", time_scale="UTC", epochs=epochs))[
        0
    ]
    tai_lon = subsatellite_track(_input(positions, frame="GCRF", time_scale="TAI", epochs=epochs))[
        0
    ]
    assert abs(float(utc_lon[0]) - float(tai_lon[0])) > 0.1


def test_subsatellite_matches_astropy_oracle() -> None:
    # Independent oracle: transform the same GCRS state to ITRS and read geodetic lon/lat/height off
    # an EarthLocation (ERFA's WGS84 geodetic) — a different geodetic code path than orbit-formats'.
    pytest.importorskip("astropy")
    import astropy.units as u  # type: ignore[import-untyped]
    from astropy.coordinates import (  # type: ignore[import-untyped]
        GCRS,
        ITRS,
        CartesianRepresentation,
        EarthLocation,
    )
    from astropy.time import Time  # type: ignore[import-untyped]

    epochs = _epochs("2024-06-01T00:00:00", "2024-06-01T03:00:00", "2024-06-01T18:00:00")
    positions = np.array(
        [[7000.0, 1500.0, 1200.0], [-4200.0, 5800.0, -900.0], [600.0, -2500.0, 6700.0]]
    )

    obstime = Time(epochs, format="datetime64", scale="utc")
    gcrs = GCRS(
        CartesianRepresentation(
            positions[:, 0] * u.km, positions[:, 1] * u.km, positions[:, 2] * u.km
        ),
        obstime=obstime,
    )
    itrs = gcrs.transform_to(ITRS(obstime=obstime))
    site = EarthLocation.from_geocentric(itrs.x, itrs.y, itrs.z)
    expected_lon = site.lon.to_value(u.deg)
    expected_lat = site.lat.to_value(u.deg)
    expected_height = site.height.to_value(u.km)

    lon, lat, height = subsatellite_track(_input(positions, frame="GCRF", epochs=epochs))
    # Both paths use astropy's GCRS->ITRS rotation; only the geodetic method differs, so agreement
    # is near machine precision — far inside the ~1 km (~0.01 deg) visualization tolerance.
    np.testing.assert_allclose(lon, expected_lon, atol=1e-6)
    np.testing.assert_allclose(lat, expected_lat, atol=1e-6)
    np.testing.assert_allclose(height, expected_height, atol=1e-6)
