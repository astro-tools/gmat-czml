"""The public assembly entry point.

:func:`to_czml` is the one call a producer makes. It validates the canonical input (the
:mod:`gmat_czml.schema` boundary), synthesizes the document clock from the trajectory span,
drives the per-entity converters, and returns a :class:`~gmat_czml.document.CzmlDocument` whose
JSON / dict / file forms are all produced in memory.

The assembly lays down the document preamble and one packet per object. The clock and each object's
UTC availability are synthesized by :mod:`gmat_czml.convert.time`; the position property, path,
point, and label — and the application of a ``style`` — are produced by the ephemeris geometry
converter (:mod:`gmat_czml.convert.ephemeris`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeAlias

import pandas as pd
from czml3 import CZML_VERSION, Document, Packet
from czml3.types import TimeInterval
from orbit_formats import Attitude, Ephemeris, Maneuver

from gmat_czml.convert.contacts import Contact, contact_packets
from gmat_czml.convert.ephemeris import orbit_geometry
from gmat_czml.convert.groundtrack import ground_track as build_ground_track
from gmat_czml.convert.maneuvers import maneuver_packets
from gmat_czml.convert.time import synthesize_clock, utc_span
from gmat_czml.document import CzmlDocument
from gmat_czml.errors import AmbiguousManeuverTargetError, DuplicateObjectNameError
from gmat_czml.schema import CanonicalInput, normalize_inputs
from gmat_czml.styles import Style

__all__ = ["TrajectorySource", "to_czml"]

# The accepted input to :func:`to_czml`: a single canonical trajectory or an iterable of them
# (one per object). A trajectory is a canonical state-series ``DataFrame`` or an orbit-formats
# ``Ephemeris``; :func:`~gmat_czml.schema.normalize_inputs` validates and normalises it.
TrajectorySource: TypeAlias = pd.DataFrame | Ephemeris | Iterable[pd.DataFrame | Ephemeris]

# The CZML document preamble carries the id ``"document"`` by convention, plus the version and
# the document clock.
_DOCUMENT_ID = "document"
_DOCUMENT_NAME = "gmat-czml"


def to_czml(
    ephemeris: TrajectorySource,
    *,
    style: Style | None = None,
    playback_seconds: float = 60.0,
    ground_track: bool = False,
    contacts: Sequence[Contact] | None = None,
    maneuvers: Iterable[Maneuver] | None = None,
    attitude: Attitude | None = None,
) -> CzmlDocument:
    """Convert a canonical trajectory into a :class:`~gmat_czml.document.CzmlDocument`.

    ``ephemeris`` is a canonical state-series :class:`~pandas.DataFrame`, an orbit-formats
    ``Ephemeris``, or an iterable of either (one trajectory per object) — whatever
    :func:`gmat_czml.schema.normalize_inputs` accepts. ``style`` selects the visual style;
    ``None`` uses the default. ``playback_seconds`` sets the document clock's default speed: the
    whole trajectory plays back in roughly that many seconds of wall-clock time (floored at 1x).
    The document is assembled entirely in memory.

    ``ground_track`` adds each object's sub-satellite geodetic polyline (one packet per contiguous
    segment, split at the antimeridian). It is **off by default**: the ground track is the only
    path that loads the Earth-orientation rotation (and astropy, transitively, for an inertial
    source), so the core ephemeris path stays free of it unless a ground track is asked for (D6).

    ``contacts`` adds, per :class:`~gmat_czml.convert.contacts.Contact`, an observer entity at its
    geodetic position and an observer → satellite link shown only during each access window. Each
    distinct observer is placed once, and each contact's target must be one of the rendered objects.

    ``maneuvers`` adds, per orbit-formats ``Maneuver``, a marker on the orbit at the burn: an
    impulsive burn becomes a point + label pinned at the burn epoch (shown from then on); a finite
    burn becomes an orange arc over the burn span plus a companion marker. The marker position is
    interpolated from the trajectory, so maneuvers attach to the one rendered object — passing them
    for a multi-object document raises :class:`~gmat_czml.errors.AmbiguousManeuverTargetError`.
    ``attitude`` is accepted so the call signature is stable but is not yet emitted — it arrives in
    a later release and already takes orbit-formats' canonical type.

    Raises a :class:`~gmat_czml.errors.SchemaError` (the typed family) for a malformed input,
    naming exactly what is wrong, :class:`~gmat_czml.errors.UnsupportedCentralBodyError` for a
    ground track about a non-Earth body, :class:`~gmat_czml.errors.UnknownContactTargetError` /
    :class:`~gmat_czml.errors.ContactEntityCollisionError` for a contact that targets a missing
    object or collides with another entity,
    :class:`~gmat_czml.errors.AmbiguousManeuverTargetError` for maneuvers on a multi-object
    document, :class:`~gmat_czml.errors.ManeuverOutsideTrajectoryError` for a burn outside the
    trajectory's time span, or :class:`ValueError` if ``playback_seconds`` is not positive.
    """
    inputs = normalize_inputs(ephemeris)
    entity_ids = _entity_ids(inputs)
    preamble = Packet(
        id=_DOCUMENT_ID,
        name=_DOCUMENT_NAME,
        version=CZML_VERSION,
        clock=synthesize_clock(inputs, playback_seconds=playback_seconds),
    )
    resolved_style = style if style is not None else Style()
    packets: list[Packet] = [preamble]
    for entity_id, item in zip(entity_ids, inputs, strict=True):
        packets.append(_entity_packet(item, entity_id, resolved_style))
        if ground_track:
            packets.extend(_ground_track_packets(item, entity_id, resolved_style))
    if contacts:
        packets.extend(contact_packets(contacts, entity_ids, resolved_style))
    if maneuvers is not None:
        maneuver_list = list(maneuvers)
        if maneuver_list:
            if len(inputs) != 1:
                raise AmbiguousManeuverTargetError(len(inputs))
            packets.extend(
                maneuver_packets(maneuver_list, inputs[0], entity_ids[0], resolved_style)
            )
    return CzmlDocument(Document(packets=packets))


def _entity_packet(item: CanonicalInput, entity_id: str, style: Style) -> Packet:
    """The CZML packet for one object — identity, UTC availability, and orbit-path geometry.

    Identity and availability are assembled here; the position property, path, point, and label —
    and the application of ``style`` — come from the ephemeris geometry converter, keyed to the same
    id used as the label's display name.
    """
    start, end = utc_span(item)
    geometry = orbit_geometry(item, style, label_text=entity_id)
    return Packet(
        id=entity_id,
        name=item.object_name,
        availability=TimeInterval(start=start, end=end),
        position=geometry.position,
        path=geometry.path,
        point=geometry.point,
        label=geometry.label,
    )


def _ground_track_packets(item: CanonicalInput, entity_id: str, style: Style) -> list[Packet]:
    """The ground-track packets for one object — one polyline packet per antimeridian segment.

    Each carries a static sub-satellite geodetic polyline (no availability — the track is valid for
    the whole document). A single-segment track is ``<entity_id>/groundtrack``; a track split at the
    antimeridian numbers its segments ``<entity_id>/groundtrack/<k>``. A degenerate track with no
    renderable segment yields no packets.
    """
    segments = build_ground_track(item, style).segments
    if len(segments) == 1:
        return [Packet(id=f"{entity_id}/groundtrack", name=item.object_name, polyline=segments[0])]
    return [
        Packet(id=f"{entity_id}/groundtrack/{index}", name=item.object_name, polyline=segment)
        for index, segment in enumerate(segments)
    ]


def _entity_ids(inputs: list[CanonicalInput]) -> list[str]:
    """Resolve a unique CZML packet id for every object, rejecting any collision.

    Each id is the object's declared name, or its positional ``object-<index>`` fallback when it is
    unnamed (:func:`_entity_id`). Declared names are already unique across the collection (enforced
    in :func:`~gmat_czml.schema.normalize_inputs`), but a declared name can still collide with
    another object's positional fallback — e.g. a name ``"object-1"`` and an unnamed object at index
    1. That collision would emit two CZML packets sharing an id, which a Cesium client silently
    merges into one entity, so it is rejected here with a typed
    :class:`~gmat_czml.errors.DuplicateObjectNameError` naming the colliding id. Packet-id
    uniqueness is the assembly's output-contract concern; the declared-name uniqueness the schema
    enforces cannot see the positional fallback.
    """
    ids = [_entity_id(item, index) for index, item in enumerate(inputs)]
    seen: set[str] = set()
    for entity_id in ids:
        if entity_id in seen:
            raise DuplicateObjectNameError(entity_id)
        seen.add(entity_id)
    return ids


def _entity_id(item: CanonicalInput, index: int) -> str:
    """A stable CZML id for the object — its declared name, else a position-based fallback.

    Declared object names are unique across the collection (enforced upstream by
    :func:`~gmat_czml.schema.normalize_inputs`); an object without a name gets ``object-<index>``.
    """
    name = item.object_name
    if name is not None and name.strip():
        return name
    return f"object-{index}"
