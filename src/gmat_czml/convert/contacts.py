"""Contact (access) intervals as an observer entity and a per-window link.

A producer's contact windows — the times a ground station can see a satellite — become two kinds
of CZML entity:

- **The observer.** Each ground station is placed as its own entity at its geodetic longitude /
  latitude / height (a static ``cartographicDegrees`` position), with a point glyph and a name
  label. The placement is the only thing read off the station — the thin, explicitly-scoped
  observer-coordinate read the charter carves out for contact placement — not a general
  ground-station parse.
- **The observer → satellite link.** A polyline whose two endpoints *reference* the observer's and
  the target's position properties (CZML ``references``), so Cesium draws the line between the two
  live entities without gmat-czml resampling either. The link is a straight line of sight
  (``arcType`` NONE, not draped on the globe) and is shown only during the access windows: its
  ``availability`` is the set of windows, one CZML interval each.

gmat-czml owns the contact record (:class:`GroundStation` / :class:`Contact`) — orbit-formats has
no access/contact canonical type yet; if one lands, this converges on it the same way the state
schema did. The converter builds the contact entities' packets directly (unlike the orbit-path and
ground-track converters, which decorate an existing object's packet) because contacts introduce
their own entities with their own id scheme: the observer id is the station name and the link id is
``<observer>-to-<target>``, both checked for collision against the document's object ids.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from czml3 import Packet
from czml3.enums import ArcTypes, HorizontalOrigins, VerticalOrigins
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
from czml3.types import Cartesian2Value, TimeInterval, TimeIntervalCollection

from gmat_czml.errors import ContactEntityCollisionError, UnknownContactTargetError
from gmat_czml.styles import Style

__all__ = ["Contact", "GroundStation", "contact_packets"]

# Geodetic height (km) -> metres. CZML ``cartographicDegrees`` carry height in metres; the contact
# record declares the station height in kilometres, the org's km-native convention (and GMAT's own
# GroundStation altitude unit), so it is scaled here exactly as the ground track scales its height.
_KM_TO_METRES = 1000.0

# The contact layer's own baked-in style, applied to every contact entity. RGBA channels are 0-255.
# The observer and the access link are drawn in cyan so they read as the ground / line-of-sight
# layer, distinct from the satellite's orbit trail; this layer is deliberately separate from the
# satellite style's colour / width / glyph customization API (gmat_czml.Style).
_LINK_COLOR = (0, 255, 255, 255)
_LINK_WIDTH = 1.0
_OBSERVER_COLOR = (0, 255, 255, 255)
_OBSERVER_OUTLINE_COLOR = (0, 0, 0, 255)
_OBSERVER_PIXEL_SIZE = 8.0
_OBSERVER_OUTLINE_WIDTH = 1.0
_OBSERVER_LABEL_COLOR = (255, 255, 255, 255)
_OBSERVER_LABEL_FONT = "11pt Lucida Console"
_OBSERVER_LABEL_PIXEL_OFFSET = (12.0, 0.0)  # nudge the text clear of the point glyph


@dataclass(frozen=True)
class GroundStation:
    """An observer's identity and geodetic placement.

    ``name`` is the observer's id (and label text); ``latitude`` and ``longitude`` are geodetic
    degrees (east-positive longitude); ``height`` is kilometres above the WGS84 ellipsoid (scaled
    to the metres CZML cartographic height uses). Equality is structural, so the same station may
    appear in several :class:`Contact` records (one per satellite it tracks) and is placed once —
    but two differently-placed stations sharing a name are rejected.
    """

    name: str
    latitude: float
    longitude: float
    height: float = 0.0


@dataclass(frozen=True)
class Contact:
    """Access windows between one observer and one target satellite.

    ``observer`` is the ground station; ``target`` is the target satellite's object name — it must
    match a rendered object's entity id (its declared name, or its ``object-<index>`` positional
    fallback). ``windows`` is the access intervals, each a ``(start, end)`` pair of
    :class:`~datetime.datetime`; the link is shown only during them. Times are UTC — a naive
    datetime is read as UTC and an aware one is converted. A contact with no windows still places
    its observer but emits no link.
    """

    observer: GroundStation
    target: str
    windows: Sequence[tuple[datetime, datetime]]


def contact_packets(
    contacts: Sequence[Contact], known_targets: Iterable[str], style: Style
) -> list[Packet]:
    """Build the CZML packets for a set of contacts: one observer entity, one per-window link each.

    ``known_targets`` is the entity ids of the rendered objects (a contact may only target one of
    them). ``style`` is accepted for signature parity with the satellite converters but is not read
    here: the contact layer carries its own baked-in style, separate from the satellite style's
    customization API. Returns the observer packets (each distinct station placed once, in
    first-seen order) followed by the link packets (one per contact that has at least one window, in
    contact order).

    Raises :class:`~gmat_czml.errors.UnknownContactTargetError` if a contact targets an object not
    in the document, and :class:`~gmat_czml.errors.ContactEntityCollisionError` if a contact entity
    id would collide with another entity (an observer name clashing with an object id, one observer
    name placed two different ways, or two contacts sharing an observer and target).
    """
    targets = set(known_targets)
    for contact in contacts:
        if contact.target not in targets:
            raise UnknownContactTargetError(contact.target, sorted(targets))

    used: set[str] = set(targets)
    placed: dict[str, GroundStation] = {}
    observers: list[Packet] = []
    for contact in contacts:
        station = contact.observer
        existing = placed.get(station.name)
        if existing is None:
            if station.name in used:
                raise ContactEntityCollisionError(station.name)
            placed[station.name] = station
            used.add(station.name)
            observers.append(_observer_packet(station))
        elif existing != station:
            raise ContactEntityCollisionError(station.name)

    links: list[Packet] = []
    for contact in contacts:
        if not contact.windows:
            continue
        link_id = _link_id(contact.observer.name, contact.target)
        if link_id in used:
            raise ContactEntityCollisionError(link_id)
        used.add(link_id)
        links.append(_link_packet(contact, link_id))

    return observers + links


def _link_id(observer_name: str, target: str) -> str:
    """The link packet id for one observer → target pair."""
    return f"{observer_name}-to-{target}"


def _observer_packet(station: GroundStation) -> Packet:
    """One ground station as a static-position entity with a point glyph and a name label."""
    return Packet(
        id=station.name,
        name=station.name,
        position=Position(
            cartographicDegrees=[
                float(station.longitude),
                float(station.latitude),
                float(station.height) * _KM_TO_METRES,
            ]
        ),
        point=_observer_point(),
        label=_observer_label(station.name),
    )


def _observer_point() -> Point:
    """The ground-station marker glyph in the baked-in contact style."""
    return Point(
        show=True,
        pixelSize=_OBSERVER_PIXEL_SIZE,
        color=Color(rgba=list(_OBSERVER_COLOR)),
        outlineColor=Color(rgba=list(_OBSERVER_OUTLINE_COLOR)),
        outlineWidth=_OBSERVER_OUTLINE_WIDTH,
    )


def _observer_label(text: str) -> Label:
    """The ground-station name label in the baked-in contact style, offset clear of the point."""
    return Label(
        show=True,
        text=text,
        font=_OBSERVER_LABEL_FONT,
        fillColor=Color(rgba=list(_OBSERVER_LABEL_COLOR)),
        horizontalOrigin=HorizontalOrigins.LEFT,
        verticalOrigin=VerticalOrigins.CENTER,
        pixelOffset=Cartesian2Value(values=list(_OBSERVER_LABEL_PIXEL_OFFSET)),
    )


def _link_packet(contact: Contact, link_id: str) -> Packet:
    """One observer → satellite link: a referenced line of sight shown only during the windows."""
    return Packet(
        id=link_id,
        name=f"{contact.observer.name} to {contact.target}",
        availability=_availability(contact.windows),
        polyline=_link_polyline(contact.observer.name, contact.target),
    )


def _availability(windows: Sequence[tuple[datetime, datetime]]) -> TimeIntervalCollection:
    """The access windows as a CZML interval collection, each endpoint in UTC."""
    return TimeIntervalCollection(
        values=[TimeInterval(start=_to_utc(start), end=_to_utc(end)) for start, end in windows]
    )


def _link_polyline(observer_id: str, target_id: str) -> Polyline:
    """The line of sight as a polyline referencing the observer and target position properties."""
    return Polyline(
        show=True,
        positions=PositionList(references=[f"{observer_id}#position", f"{target_id}#position"]),
        width=_LINK_WIDTH,
        arcType=ArcTypes.NONE,
        material=PolylineMaterial(
            solidColor=SolidColorMaterial(color=Color(rgba=list(_LINK_COLOR)))
        ),
    )


def _to_utc(moment: datetime) -> datetime:
    """A window endpoint as UTC-aware: a naive value is read as UTC, an aware one is converted."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
