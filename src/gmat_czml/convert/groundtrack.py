"""Ground track as a geodetic polyline.

Projects the orbit to the sub-satellite point at each epoch (via the rotation in
:mod:`gmat_czml.convert.frames`) and emits it as a geodetic longitude / latitude / height
polyline, handling the antimeridian wrap.

What this module owns:

- **The geodetic polyline.** The sub-satellite longitude / latitude / height series from
  :func:`gmat_czml.convert.frames.subsatellite_track` becomes a CZML polyline whose positions are
  ``cartographicDegrees`` — ``[lon, lat, height, ...]`` with longitude / latitude in degrees and
  height in **metres** (CZML cartographic height is metric; the projection returns kilometres). The
  track follows the sub-satellite point at the satellite's own geodetic height, so it floats over
  the correct ground position rather than being clamped to the surface.
- **The antimeridian split.** A track crossing ±180° longitude is broken into contiguous segments,
  each its own polyline, with an interpolated seam point placed exactly on the dateline at both
  ends of the break — so the rendered track neither draws a spurious line back across the globe nor
  leaves a gap at the crossing. The arc type is ``GEODESIC`` so each segment follows the shortest
  ground path between samples.
- **The Earth-only guard.** The projection is WGS84 / Earth-fixed throughout (D1, D5), so a
  trajectory *declared* about another central body is rejected rather than silently mis-projected;
  an undeclared body is accepted, since every recognised frame is already an Earth frame.
- **The track style** — its colour and width — comes from the supplied
  :class:`~gmat_czml.styles.Style`'s ``track`` field, whose defaults are the ``sat-default`` look.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from czml3.enums import ArcTypes
from czml3.properties import Color, Polyline, PolylineMaterial, PositionList, SolidColorMaterial
from numpy.typing import NDArray

from gmat_czml.convert.frames import subsatellite_track
from gmat_czml.errors import UnsupportedCentralBodyError
from gmat_czml.schema import CanonicalInput
from gmat_czml.styles import Style, TrackStyle

__all__ = ["GroundTrack", "ground_track"]

# The central body the WGS84 sub-satellite projection is defined for (compared case-insensitively).
# A declared body other than this is rejected; an undeclared body (None) is accepted.
_EARTH = "EARTH"

# Geodetic height (km) -> metres. CZML ``cartographicDegrees`` carry height in metres, while the
# projection returns it in kilometres alongside the degree longitude / latitude.
_KM_TO_METRES = 1000.0

# The longitude jump (degrees) between consecutive samples that marks an antimeridian crossing: a
# real sub-satellite step is far smaller, so a swing past a half-revolution is a ±180° wrap, not
# motion. The seam is interpolated onto the ±180° meridian the track crossed.
_WRAP_THRESHOLD_DEG = 180.0
_ANTIMERIDIAN_DEG = 180.0


@dataclass(frozen=True)
class GroundTrack:
    """The CZML ground-track geometry for one object.

    ``segments`` is one :class:`~czml3.properties.Polyline` per contiguous stretch of the
    sub-satellite track between antimeridian crossings, in chronological order. A track that never
    crosses the dateline is a single segment; one that does is split so no polyline draws a spurious
    wrap across the globe. A degenerate track with fewer than two renderable points yields an empty
    list. :func:`gmat_czml.assembly.to_czml` emits each segment as its own packet.
    """

    segments: list[Polyline]


def ground_track(item: CanonicalInput, style: Style) -> GroundTrack:
    """Convert one validated trajectory into its CZML ground-track geometry.

    Projects the trajectory to its sub-satellite longitude / latitude / height
    (:func:`gmat_czml.convert.frames.subsatellite_track`) and emits a geodetic
    ``cartographicDegrees`` polyline in the style's track colour and width, split at antimeridian
    crossings so the track renders without a spurious wrap line. Height travels in metres (scaled
    from the projection's kilometres); longitude / latitude in degrees.

    ``style`` drives the visual style: ``style.track`` colours and widths the ground-track polyline.
    ``Style()`` is the ``sat-default`` look.

    Raises :class:`~gmat_czml.errors.UnsupportedCentralBodyError` if the trajectory is declared
    about a body other than Earth, and propagates :class:`~gmat_czml.errors.InvalidUnitsError` from
    the projection for an unsupported length unit.
    """
    _require_earth(item)
    lon, lat, height_km = subsatellite_track(item)
    height_m = height_km * _KM_TO_METRES
    runs = _split_at_antimeridian(lon, lat, height_m)
    # A run needs at least two points to draw; a single-sample track yields none.
    segments = [_polyline(run, style.track) for run in runs if len(run[0]) >= 2]
    return GroundTrack(segments=segments)


def _require_earth(item: CanonicalInput) -> None:
    """Reject a ground track for a declared non-Earth central body; allow an undeclared one."""
    body = item.central_body
    if body is not None and body.strip().upper() != _EARTH:
        raise UnsupportedCentralBodyError(body)


# A single contiguous run of the track: parallel longitude / latitude / height arrays.
_Segment = tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]


def _split_at_antimeridian(
    lon: NDArray[np.float64], lat: NDArray[np.float64], height: NDArray[np.float64]
) -> list[_Segment]:
    """Split the sub-satellite track into contiguous runs at each antimeridian crossing.

    Where consecutive longitudes jump by more than half a revolution the track has wrapped across
    ±180°. The run is cut there and an interpolated seam point is appended to the closing run and
    prepended to the opening run, both sitting exactly on the meridian the track crossed (one at
    ``+180``, its mirror at ``-180``), with latitude and height linearly interpolated to the
    crossing — so adjacent segments meet on the dateline with neither a wrap line nor a gap. A track
    that never wraps is returned as a single run.
    """
    cuts = np.nonzero(np.abs(np.diff(lon)) > _WRAP_THRESHOLD_DEG)[0]
    if len(cuts) == 0:
        return [(lon, lat, height)]

    segments: list[_Segment] = []
    start = 0
    leading_seam: tuple[float, float, float] | None = None
    for cut in cuts:
        index = int(cut)
        exit_lon, entry_lon, seam_lat, seam_height = _seam(
            lon[index], lon[index + 1], lat[index], lat[index + 1], height[index], height[index + 1]
        )
        trailing_seam = (exit_lon, seam_lat, seam_height)
        segments.append(_run(lon, lat, height, start, index + 1, leading_seam, trailing_seam))
        leading_seam = (entry_lon, seam_lat, seam_height)
        start = index + 1
    segments.append(_run(lon, lat, height, start, len(lon), leading_seam, None))
    return segments


def _run(
    lon: NDArray[np.float64],
    lat: NDArray[np.float64],
    height: NDArray[np.float64],
    start: int,
    stop: int,
    leading: tuple[float, float, float] | None,
    trailing: tuple[float, float, float] | None,
) -> _Segment:
    """One ``[start:stop)`` run, optionally bracketed by interpolated dateline seam points."""
    lons = [lon[start:stop]]
    lats = [lat[start:stop]]
    heights = [height[start:stop]]
    if leading is not None:
        lons.insert(0, np.array([leading[0]]))
        lats.insert(0, np.array([leading[1]]))
        heights.insert(0, np.array([leading[2]]))
    if trailing is not None:
        lons.append(np.array([trailing[0]]))
        lats.append(np.array([trailing[1]]))
        heights.append(np.array([trailing[2]]))
    return np.concatenate(lons), np.concatenate(lats), np.concatenate(heights)


def _seam(
    lon_a: float,
    lon_b: float,
    lat_a: float,
    lat_b: float,
    height_a: float,
    height_b: float,
) -> tuple[float, float, float, float]:
    """The dateline crossing between two wrapped samples: exit / entry longitude, latitude, height.

    Unwraps the second longitude across the dateline so the step is monotone, finds the fraction at
    which it reaches the crossed ±180° meridian, and interpolates latitude and height there. Returns
    the longitude the closing run exits at (``±180``), the mirror longitude the opening run enters
    at (``∓180``), and the shared seam latitude and height.
    """
    boundary = _ANTIMERIDIAN_DEG if lon_b < lon_a else -_ANTIMERIDIAN_DEG
    unwrapped_b = lon_b + 360.0 if lon_b < lon_a else lon_b - 360.0
    fraction = (boundary - lon_a) / (unwrapped_b - lon_a)
    seam_lat = lat_a + fraction * (lat_b - lat_a)
    seam_height = height_a + fraction * (height_b - height_a)
    return boundary, -boundary, seam_lat, seam_height


def _polyline(segment: _Segment, style: TrackStyle) -> Polyline:
    """One contiguous run as a geodetic ``cartographicDegrees`` polyline in the track style."""
    lon, lat, height = segment
    cartographic = np.column_stack([lon, lat, height]).reshape(-1)
    return Polyline(
        show=True,
        positions=PositionList(cartographicDegrees=[float(value) for value in cartographic]),
        width=style.width,
        arcType=ArcTypes.GEODESIC,
        material=PolylineMaterial(
            solidColor=SolidColorMaterial(color=Color(rgba=list(style.color)))
        ),
    )
