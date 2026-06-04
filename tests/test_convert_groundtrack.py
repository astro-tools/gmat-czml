"""Tests for the ground-track converter (``gmat_czml.convert.groundtrack``).

The sub-satellite projection itself is delegated to ``convert.frames`` (tested there against an
astropy oracle), so these pin the gmat-czml layer this module owns: that the geodetic series
becomes a ``cartographicDegrees`` polyline with longitude / latitude in degrees and height in
**metres**, that an antimeridian crossing splits into gap-free / wrap-free segments meeting on the
dateline, that a non-Earth central body is rejected, and that the ``sat-default`` style is applied.

The known-track checks use a *fixed* (ITRF) source: its rotation is an identity, so the
sub-satellite longitude / latitude is the closed-form WGS84 projection of the input — an independent
hand computation, no rotation oracle needed.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from czml3.enums import ArcTypes
from czml3.properties import Polyline
from numpy.typing import NDArray

from gmat_czml.convert.groundtrack import ground_track
from gmat_czml.errors import InvalidUnitsError, UnsupportedCentralBodyError
from gmat_czml.schema import CanonicalInput, validate
from gmat_czml.styles import Style

# WGS84 equatorial radius (km) — orbit-formats' default ellipsoid, used to place analytic points.
_WGS84_A = 6378.137


def _equatorial(longitudes_deg: list[float], *, height_km: float = 0.0) -> NDArray[np.float64]:
    """ITRF positions on the equator at the given geodetic longitudes, at ``height_km`` altitude.

    On the equator the geodetic longitude equals the ECEF azimuth and the geodetic point projects to
    that same longitude, latitude 0 — so the expected sub-satellite track is exactly the input
    longitudes, which makes the polyline assertions a closed-form check.
    """
    radius = _WGS84_A + height_km
    radians = np.deg2rad(longitudes_deg)
    return np.column_stack(
        [radius * np.cos(radians), radius * np.sin(radians), np.zeros(len(radians))]
    )


def _input(
    positions: NDArray[np.float64],
    *,
    frame: str = "ITRF",
    central_body: str | None = "Earth",
    length: str = "km",
    epochs: NDArray[np.datetime64] | None = None,
) -> CanonicalInput:
    """A validated single-object input over ``positions`` (an ``(N, 3)`` array, in ``length``)."""
    n = len(positions)
    if epochs is None:
        epochs = np.array(
            pd.date_range("2024-06-01T00:00:00", periods=n, freq="600s"), dtype="datetime64[ns]"
        )
    df = pd.DataFrame(
        {
            "Epoch": epochs,
            "X": positions[:, 0],
            "Y": positions[:, 1],
            "Z": positions[:, 2],
        }
    )
    attrs: dict[str, object] = {
        "object_name": "Sat",
        "coordinate_system": frame,
        "time_scale": "UTC",
        "units": {"length": length, "speed": "km/s"},
    }
    if central_body is not None:
        attrs["central_body"] = central_body
    df.attrs.update(attrs)
    return validate(df)


def _positions(polyline: Polyline) -> NDArray[np.float64]:
    """The polyline's cartographic positions as an ``(N, 3)`` ``[lon, lat, height_m]`` array."""
    parsed: dict[str, Any] = json.loads(polyline.dumps())
    return np.array(parsed["positions"]["cartographicDegrees"], dtype=np.float64).reshape(-1, 3)


# --- the geodetic polyline ----------------------------------------------------------------


def test_single_segment_track_is_one_polyline_over_the_subsatellite_lon_lat() -> None:
    # A short equatorial arc that never nears the dateline: one segment, longitudes preserved,
    # latitude 0, in cartographicDegrees order.
    track = ground_track(_input(_equatorial([0.0, 30.0, 60.0])), Style())
    assert len(track.segments) == 1
    positions = _positions(track.segments[0])
    np.testing.assert_allclose(positions[:, 0], [0.0, 30.0, 60.0], atol=1e-6)
    np.testing.assert_allclose(positions[:, 1], 0.0, atol=1e-6)


def test_height_is_metres_not_kilometres() -> None:
    # The sub-satellite height (the satellite's geodetic altitude) is emitted in metres: a 500 km
    # altitude must come out as 500_000 m, never the raw 500.
    track = ground_track(_input(_equatorial([0.0, 20.0], height_km=500.0)), Style())
    positions = _positions(track.segments[0])
    np.testing.assert_allclose(positions[:, 2], 500_000.0, atol=1e-3)


def test_metres_input_matches_kilometres() -> None:
    # The same physical state declared in metres yields the same polyline positions.
    positions_km = _equatorial([0.0, 25.0, 50.0], height_km=400.0)
    in_km = _positions(ground_track(_input(positions_km, length="km"), Style()).segments[0])
    in_m = _positions(ground_track(_input(positions_km * 1000.0, length="m"), Style()).segments[0])
    np.testing.assert_allclose(in_m, in_km, atol=1e-6)


def test_unsupported_length_unit_is_rejected() -> None:
    with pytest.raises(InvalidUnitsError):
        ground_track(_input(_equatorial([0.0, 10.0]), length="AU"), Style())


# --- the antimeridian split ---------------------------------------------------------------


def test_antimeridian_crossing_splits_into_two_segments() -> None:
    # An eastbound equatorial track 170 -> 175 -> -175 -> -170 wraps once across +180.
    track = ground_track(_input(_equatorial([170.0, 175.0, -175.0, -170.0])), Style())
    assert len(track.segments) == 2


def test_no_segment_carries_a_spurious_wrap() -> None:
    # Within every emitted segment, consecutive longitudes never jump more than half a revolution —
    # the wrap that would draw a line back across the globe has been cut out.
    track = ground_track(_input(_equatorial([170.0, 175.0, -175.0, -170.0])), Style())
    for segment in track.segments:
        lon = _positions(segment)[:, 0]
        assert np.all(np.abs(np.diff(lon)) <= 180.0)


def test_segments_meet_on_the_dateline_without_a_gap() -> None:
    # The closing segment exits at +180 and the opening segment enters at -180, both at the same
    # interpolated latitude — so the track meets on the dateline rather than leaving a gap. The
    # symmetric 175 / -175 crossing puts the seam at latitude 0.
    track = ground_track(_input(_equatorial([170.0, 175.0, -175.0, -170.0])), Style())
    first, second = (_positions(segment) for segment in track.segments)
    np.testing.assert_allclose(first[-1], [180.0, 0.0, 0.0], atol=1e-6)
    np.testing.assert_allclose(second[0], [-180.0, 0.0, 0.0], atol=1e-6)


def test_westbound_crossing_seams_at_minus_180() -> None:
    # A westbound track -175 -> -170(?) ... 170 wraps across -180; the closing segment exits at -180
    # and the opening one enters at +180.
    track = ground_track(_input(_equatorial([-175.0, -170.0, 170.0, 175.0])), Style())
    assert len(track.segments) == 2
    first, second = (_positions(segment) for segment in track.segments)
    np.testing.assert_allclose(first[-1, 0], -180.0, atol=1e-6)
    np.testing.assert_allclose(second[0, 0], 180.0, atol=1e-6)


def test_seam_latitude_is_interpolated_to_the_crossing() -> None:
    # A crossing skewed in latitude: sub-satellite points at (179, 10) and (-179, 20). The dateline
    # sits halfway in unwrapped longitude (179 -> 181), so the seam latitude is the midpoint of the
    # two projected endpoint latitudes — proving the seam is interpolated to the crossing, not just
    # snapped onto ±180. Asserting against the projected endpoints keeps the check independent of
    # the exact ellipsoid the projection uses.
    track = ground_track(_input(_skewed_pair()), Style())
    first, second = (_positions(segment) for segment in track.segments)
    expected_seam_lat = 0.5 * (first[0, 1] + second[-1, 1])
    assert first[-1, 0] == pytest.approx(180.0, abs=1e-6)
    assert second[0, 0] == pytest.approx(-180.0, abs=1e-6)
    assert first[-1, 1] == pytest.approx(expected_seam_lat, abs=1e-6)
    assert second[0, 1] == pytest.approx(expected_seam_lat, abs=1e-6)


def _skewed_pair() -> NDArray[np.float64]:
    """An ITRF pair (179, 10) -> (-179, 20) in geodetic lon/lat — the dateline seam lands at 15."""
    return np.array(
        [_geodetic_to_ecef(179.0, 10.0), _geodetic_to_ecef(-179.0, 20.0)], dtype=np.float64
    )


def _geodetic_to_ecef(lon_deg: float, lat_deg: float, height_km: float = 0.0) -> list[float]:
    """A WGS84 surface point (km) at the given geodetic longitude / latitude — projection inverse.

    Lets a test state a sub-satellite point directly in lon/lat; ``subsatellite_track`` projects it
    straight back, so the expected track is the stated longitude / latitude.
    """
    a = _WGS84_A
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    lon, lat = np.deg2rad(lon_deg), np.deg2rad(lat_deg)
    n = a / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
    x = (n + height_km) * np.cos(lat) * np.cos(lon)
    y = (n + height_km) * np.cos(lat) * np.sin(lon)
    z = (n * (1.0 - e2) + height_km) * np.sin(lat)
    return [float(x), float(y), float(z)]


# --- the Earth-only guard -----------------------------------------------------------------


def test_non_earth_central_body_is_rejected() -> None:
    with pytest.raises(UnsupportedCentralBodyError):
        ground_track(_input(_equatorial([0.0, 10.0]), central_body="Moon"), Style())


def test_undeclared_central_body_is_accepted() -> None:
    # No central body declared: the recognised frame is already an Earth frame, so it renders.
    track = ground_track(_input(_equatorial([0.0, 10.0]), central_body=None), Style())
    assert len(track.segments) == 1


def test_earth_is_matched_case_insensitively() -> None:
    track = ground_track(_input(_equatorial([0.0, 10.0]), central_body="earth"), Style())
    assert len(track.segments) == 1


# --- degenerate tracks --------------------------------------------------------------------


def test_single_sample_track_yields_no_segment() -> None:
    # One sample cannot draw a polyline, so no segment is emitted.
    track = ground_track(_input(_equatorial([42.0])), Style())
    assert track.segments == []


# --- the sat-default style ----------------------------------------------------------------


def test_sat_default_style_is_applied() -> None:
    polyline = ground_track(_input(_equatorial([0.0, 30.0])), Style()).segments[0]
    parsed = json.loads(polyline.dumps())
    assert parsed["show"] is True
    assert parsed["width"] == 2.0
    assert parsed["arcType"] == ArcTypes.GEODESIC.value
    assert parsed["material"]["solidColor"]["color"]["rgba"] == [255, 255, 0, 255]
