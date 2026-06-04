"""Maneuvers (impulsive + finite) as markers on the orbit.

A producer's maneuvers — the burns orbit-formats reads from a CCSDS OPM / OCM and carries as its
canonical :class:`~orbit_formats.Maneuver` record — become CZML annotations pinned to the trajectory
they act on:

- **An impulsive maneuver** (zero duration) is a single marker: a point and a label placed on the
  orbit at the burn epoch, shown from that epoch onward so it appears as the playhead reaches the
  burn and stays as a record of where the impulse happened.
- **A finite maneuver** (non-zero duration) is two entities: a distinctly-coloured *arc* tracing
  the orbit between ignition and cut-off, and a point + label *marker* at the ignition point — both
  shown only over the burn span, so the highlighted segment and its label are present exactly while
  the burn is firing.

The ``Maneuver`` record carries the burn's epoch, frame, duration, and Δv, but **no position and no
target object** — a burn names neither where it sits in space nor which craft it acts on. gmat-czml
therefore *interpolates* the marker location from the trajectory itself (the same trajectory the
orbit path is drawn from, scaled to metres and tagged with the same reference frame), so every
marker lands on the rendered orbit, and attributes the maneuvers to that one trajectory — the
assembly rejects maneuvers for a multi-object document, where the target craft is ambiguous. The
maneuver epoch carries no time scale of its own, so it is read in the trajectory's declared scale
(one mission, one time system) and the burn span is carried onto the document's UTC timeline as
each entity's ``availability``.

Because a maneuver introduces its own entities rather than decorating the object's packet, the
converter builds the packets directly, under the object-namespaced id scheme
``<object>/maneuver/<k>`` (plus ``<object>/maneuver/<k>/marker`` for a finite arc's companion
marker) — collision-free against the object and ground-track ids the assembly already emits.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from czml3 import Packet
from czml3.enums import ArcTypes, HorizontalOrigins, ReferenceFrames, VerticalOrigins
from czml3.properties import (
    Color,
    Label,
    Point,
    Polyline,
    PolylineMaterial,
    Position,
    PositionList,
    SolidColorMaterial,
)
from czml3.types import Cartesian2Value, TimeInterval
from numpy.typing import NDArray
from orbit_formats import Maneuver

from gmat_czml.convert.frames import czml_reference_frame
from gmat_czml.convert.time import to_utc, utc_span
from gmat_czml.errors import InvalidUnitsError, ManeuverOutsideTrajectoryError
from gmat_czml.schema import CanonicalInput
from gmat_czml.styles import Style

__all__ = ["maneuver_packets"]

# Declared length unit -> metres (keys upper-cased). CZML cartesian is metric and the canonical
# default is kilometres, so the interpolated marker position is scaled here exactly as the
# orbit-path converter scales the orbit (D2) — the marker must land on the path, so it shares the
# same scaling.
_LENGTH_TO_METRES = {"KM": 1000.0, "M": 1.0}
_SUPPORTED_LENGTH_UNITS = ("km", "m")

# The single baked-in maneuver style — the only style until the v0.2 preset / customization system.
# The values live here as the converter's rendering defaults, applied to every maneuver entity. RGBA
# channels are 0-255. Maneuvers are drawn in orange so they read as their own layer, distinct from
# the satellite's yellow orbit trail and the cyan contact line of sight.
_MARKER_COLOR = (255, 140, 0, 255)
_MARKER_OUTLINE_COLOR = (0, 0, 0, 255)
_MARKER_PIXEL_SIZE = 11.0
_MARKER_OUTLINE_WIDTH = 1.0
_LABEL_COLOR = (255, 255, 255, 255)
_LABEL_FONT = "11pt Lucida Console"
_LABEL_PIXEL_OFFSET = (12.0, 0.0)  # nudge the text clear of the point glyph
_ARC_COLOR = (255, 140, 0, 255)
_ARC_WIDTH = 3.0


def maneuver_packets(
    maneuvers: Sequence[Maneuver], item: CanonicalInput, entity_id: str, style: Style
) -> list[Packet]:
    """Build the CZML packets for a trajectory's maneuvers — one marker per impulsive burn, an arc
    plus a marker per finite burn.

    ``item`` is the trajectory the maneuvers act on (the source of the interpolated marker position
    and the reference frame); ``entity_id`` is its packet id, under which the maneuver ids are
    namespaced. ``style`` selects the visual style; the single baked-in maneuver style is applied to
    every entity, so it is accepted as the stable seam the v0.2 preset system plugs into rather than
    branched on here. Packets are returned in maneuver order: an impulsive maneuver yields one
    packet (``<entity_id>/maneuver/<k>``); a finite one yields its arc (same id) then its companion
    marker (``<entity_id>/maneuver/<k>/marker``).

    Raises :class:`~gmat_czml.errors.ManeuverOutsideTrajectoryError` if a burn's ignition (or, for a
    finite burn, its cut-off) falls outside the trajectory's time span — the marker position is
    interpolated from the trajectory, so a burn with no orbit beneath it is rejected, never
    clamped — and propagates :class:`~gmat_czml.errors.InvalidUnitsError` for an unsupported length
    unit.
    """
    frame = czml_reference_frame(item.frame)
    epochs = np.asarray(item.ephemeris.epochs, dtype="datetime64[ns]")
    positions_m = _positions_metres(item)
    reference = epochs[0]
    epoch_seconds = (epochs - reference) / np.timedelta64(1, "s")
    span_start_s, span_end_s = float(epoch_seconds[0]), float(epoch_seconds[-1])
    traj_start, traj_end = utc_span(item)

    packets: list[Packet] = []
    for index, maneuver in enumerate(maneuvers):
        ignition_s = float((maneuver.epoch_ignition - reference) / np.timedelta64(1, "s"))
        ignition_utc = _to_utc_datetime(maneuver.epoch_ignition, item.time_scale)
        cutoff_s = ignition_s + maneuver.duration
        latest_s = cutoff_s if maneuver.duration > 0.0 else ignition_s
        if ignition_s < span_start_s or latest_s > span_end_s:
            raise ManeuverOutsideTrajectoryError(epoch=ignition_utc, span=(traj_start, traj_end))

        maneuver_id = f"{entity_id}/maneuver/{index}"
        name = f"{entity_id} maneuver {index}"
        position = Position(
            referenceFrame=frame,
            cartesian=_interpolate(epoch_seconds, positions_m, ignition_s),
        )
        if maneuver.duration > 0.0:
            cutoff_utc = ignition_utc + timedelta(seconds=maneuver.duration)
            availability = TimeInterval(start=ignition_utc, end=cutoff_utc)
            arc = _arc_cartesian(epoch_seconds, positions_m, ignition_s, cutoff_s)
            packets.append(
                Packet(
                    id=maneuver_id, name=name, availability=availability, polyline=_arc(frame, arc)
                )
            )
            packets.append(
                Packet(
                    id=f"{maneuver_id}/marker",
                    name=name,
                    availability=availability,
                    position=position,
                    point=_marker_point(),
                    label=_marker_label(_finite_label(maneuver)),
                )
            )
        else:
            packets.append(
                Packet(
                    id=maneuver_id,
                    name=name,
                    availability=TimeInterval(start=ignition_utc, end=traj_end),
                    position=position,
                    point=_marker_point(),
                    label=_marker_label(_impulsive_label(maneuver)),
                )
            )
    return packets


def _positions_metres(item: CanonicalInput) -> NDArray[np.float64]:
    """The trajectory's positions in metres, scaled from the declared length unit (D2).

    Mirrors the orbit-path converter's scaling so an interpolated marker lands on the rendered path.
    """
    unit = item.ephemeris.metadata.units.length
    factor = _LENGTH_TO_METRES.get(unit.strip().upper())
    if factor is None:
        supported = ", ".join(_SUPPORTED_LENGTH_UNITS)
        raise InvalidUnitsError(
            f"length unit {unit!r} is not supported by the maneuver converter; "
            f"supported units: {supported}"
        )
    positions = np.asarray(item.ephemeris.positions, dtype=np.float64)
    return np.asarray(positions * factor, dtype=np.float64)


def _interpolate(
    epoch_seconds: NDArray[np.float64], positions_m: NDArray[np.float64], at_second: float
) -> list[float]:
    """The orbit position (metres) at ``at_second``, linearly interpolated per axis.

    ``epoch_seconds`` is the trajectory's per-sample offsets from its first epoch (strictly
    increasing), against which the burn time is interpolated. Linear interpolation is exact at a
    sample and within a marker's tolerance between samples — the pin annotates the orbit, it does
    not re-derive the declared interpolation curve.
    """
    return [float(np.interp(at_second, epoch_seconds, positions_m[:, axis])) for axis in range(3)]


def _arc_cartesian(
    epoch_seconds: NDArray[np.float64],
    positions_m: NDArray[np.float64],
    start_second: float,
    end_second: float,
) -> list[float]:
    """The burn arc as a flat ``[x, y, z, ...]`` cartesian list spanning ``[start, end]`` seconds.

    Interpolated endpoints at exactly ignition and cut-off bracket the trajectory's own samples
    that fall strictly inside the burn, so the arc follows the real orbit over the burn span and
    meets the span ends precisely. A burn shorter than the sample step yields the two endpoints
    alone — still a drawable segment.
    """
    interior = (epoch_seconds > start_second) & (epoch_seconds < end_second)
    start = np.asarray(_interpolate(epoch_seconds, positions_m, start_second))
    end = np.asarray(_interpolate(epoch_seconds, positions_m, end_second))
    points = np.vstack([start, positions_m[interior], end])
    return [float(value) for value in points.reshape(-1)]


def _to_utc_datetime(epoch: np.datetime64, time_scale: str) -> datetime:
    """A maneuver epoch (read in the trajectory's ``time_scale``) as a UTC-aware datetime."""
    utc = to_utc(np.asarray([epoch], dtype="datetime64[ns]"), time_scale)[0]
    return pd.Timestamp(utc).to_pydatetime().replace(tzinfo=timezone.utc)


def _impulsive_label(maneuver: Maneuver) -> str:
    """The marker text for an impulsive burn: its Δv magnitude, or a bare label if none stated."""
    if maneuver.delta_v is None:
        return "maneuver"
    return f"Δv {float(np.linalg.norm(maneuver.delta_v)):.3f} km/s"


def _finite_label(maneuver: Maneuver) -> str:
    """The marker text for a finite burn: its Δv magnitude and duration, or duration alone."""
    duration = f"{maneuver.duration:g} s"
    if maneuver.delta_v is None:
        return f"burn {duration}"
    return f"Δv {float(np.linalg.norm(maneuver.delta_v)):.3f} km/s over {duration}"


def _arc(frame: ReferenceFrames, cartesian: list[float]) -> Polyline:
    """The burn arc as an orange polyline of straight segments in the trajectory's frame."""
    return Polyline(
        show=True,
        positions=PositionList(referenceFrame=frame, cartesian=cartesian),
        width=_ARC_WIDTH,
        arcType=ArcTypes.NONE,
        material=PolylineMaterial(
            solidColor=SolidColorMaterial(color=Color(rgba=list(_ARC_COLOR)))
        ),
    )


def _marker_point() -> Point:
    """The maneuver marker glyph in the baked-in maneuver style."""
    return Point(
        show=True,
        pixelSize=_MARKER_PIXEL_SIZE,
        color=Color(rgba=list(_MARKER_COLOR)),
        outlineColor=Color(rgba=list(_MARKER_OUTLINE_COLOR)),
        outlineWidth=_MARKER_OUTLINE_WIDTH,
    )


def _marker_label(text: str) -> Label:
    """The maneuver label in the baked-in maneuver style, offset clear of the point."""
    return Label(
        show=True,
        text=text,
        font=_LABEL_FONT,
        fillColor=Color(rgba=list(_LABEL_COLOR)),
        horizontalOrigin=HorizontalOrigins.LEFT,
        verticalOrigin=VerticalOrigins.CENTER,
        pixelOffset=Cartesian2Value(values=list(_LABEL_PIXEL_OFFSET)),
    )
