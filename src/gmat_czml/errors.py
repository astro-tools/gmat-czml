"""The typed error hierarchy the public surface raises.

Every error gmat-czml raises on purpose descends from :class:`GmatCzmlError`, so a caller
can catch the whole family with one ``except``. The schema-validation failures all descend
from :class:`SchemaError`, which is also a :class:`ValueError` — a malformed canonical input
*is* a bad value, and existing ``except ValueError`` handlers keep working. Each subclass
names exactly what is wrong (a missing column, an unrecognised frame, an absent time scale,
malformed unit metadata) so a producer never has to read a bare ``KeyError`` traceback to
learn what its DataFrame got wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "AmbiguousManeuverTargetError",
    "ContactEntityCollisionError",
    "DuplicateObjectNameError",
    "EmptyTrajectoryError",
    "GmatCzmlError",
    "InvalidUnitsError",
    "MalformedStateError",
    "ManeuverOutsideTrajectoryError",
    "MissingColumnError",
    "MissingFrameError",
    "MissingTimeScaleError",
    "SchemaError",
    "UnknownContactTargetError",
    "UnknownFrameError",
    "UnknownInterpolationError",
    "UnknownTimeScaleError",
    "UnmappableFrameError",
    "UnsupportedCentralBodyError",
]


class GmatCzmlError(Exception):
    """Base class for every error gmat-czml raises deliberately."""


class UnmappableFrameError(GmatCzmlError):
    """A recognised frame that has no CZML reference-frame mapping.

    Raised by the frame mapping for a canonical frame id that validation *recognised* but the
    converter cannot render in a CZML reference frame (``INERTIAL`` / ``FIXED``). Distinct from
    :class:`UnknownFrameError`, which rejects a name outside the recognised set at the input
    boundary: the input here was valid, so this descends from :class:`GmatCzmlError` directly rather
    than :class:`SchemaError`. ``frame`` is the offending id and ``mappable`` the ids that do map.
    """

    def __init__(self, frame: str, mappable: Iterable[str]) -> None:
        self.frame = frame
        self.mappable: tuple[str, ...] = tuple(mappable)
        joined = ", ".join(self.mappable)
        super().__init__(
            f"frame {frame!r} has no CZML reference-frame mapping; mappable frames: {joined}"
        )


class UnsupportedCentralBodyError(GmatCzmlError):
    """A ground track requested for a trajectory about a body other than Earth.

    The sub-satellite projection is WGS84 / Earth-fixed throughout (D1, D5), so the ground track is
    Earth-only. Raised by the ground-track converter when ``attrs['central_body']`` is *declared* as
    something other than Earth; an undeclared body is accepted, since every recognised frame is an
    Earth frame already. Like :class:`UnmappableFrameError`, the input was a valid trajectory — the
    limitation is at render time — so this descends from :class:`GmatCzmlError` directly rather than
    :class:`SchemaError`. ``central_body`` is the offending value.
    """

    def __init__(self, central_body: str) -> None:
        self.central_body = central_body
        super().__init__(
            f"ground track is Earth-only, but the central body is {central_body!r}; "
            "the WGS84 sub-satellite projection is defined for Earth"
        )


class UnknownInterpolationError(GmatCzmlError):
    """A declared interpolation algorithm with no CZML equivalent.

    Raised by the ephemeris converter when ``attrs['interpolation']`` carries a name outside the
    set CZML understands (``LAGRANGE`` / ``HERMITE`` / ``LINEAR``). The interpolation hint is read
    at the converter layer, not validated as part of the schema contract, so — like
    :class:`UnmappableFrameError` — this descends from :class:`GmatCzmlError` directly rather than
    :class:`SchemaError`. The algorithm is mapped, never guessed: an undeclared algorithm defaults,
    but an *unrecognised* one is rejected. ``algorithm`` is the offending name and ``recognised``
    the names that map.
    """

    def __init__(self, algorithm: str, recognised: Iterable[str]) -> None:
        self.algorithm = algorithm
        self.recognised: tuple[str, ...] = tuple(recognised)
        joined = ", ".join(self.recognised)
        super().__init__(
            f"interpolation algorithm {algorithm!r} has no CZML equivalent; "
            f"recognised algorithms: {joined}"
        )


class UnknownContactTargetError(GmatCzmlError):
    """A contact names a target satellite that is not an object in the document.

    The observer → satellite link is a CZML polyline whose endpoints *reference* the observer's and
    the target's position properties, so the target must be one of the rendered objects (its entity
    id is the object's name, or its positional fallback). A contact naming a target no input
    trajectory provides would emit a link with a dangling reference a Cesium client cannot resolve,
    so it is rejected. Like :class:`UnmappableFrameError`, the trajectory input was valid — the
    mismatch is in the ``contacts`` argument — so this descends from :class:`GmatCzmlError` directly
    rather than :class:`SchemaError`. ``target`` is the offending name and ``known`` the object ids
    a contact may target.
    """

    def __init__(self, target: str, known: Iterable[str]) -> None:
        self.target = target
        self.known: tuple[str, ...] = tuple(known)
        joined = ", ".join(self.known) if self.known else "(none)"
        super().__init__(
            f"contact target {target!r} is not an object in the document; "
            f"targetable objects: {joined}"
        )


class ContactEntityCollisionError(GmatCzmlError):
    """A contact would emit a CZML entity whose id collides with another entity.

    Contacts introduce their own entities — one observer per ground station and one
    observer-to-satellite link per contact — each with its own packet id (the observer's name, and
    ``<observer>-to-<target>`` for the link). That id must be unique across the whole document: a
    Cesium client silently merges two packets sharing an id into one entity. This is raised when an
    observer name collides with an object (satellite) id, when one observer name is declared with
    two different placements, or when two contacts share the same observer and target. Like
    :class:`UnknownContactTargetError`, the trajectory input was valid, so this descends from
    :class:`GmatCzmlError` directly. ``entity_id`` is the colliding id.
    """

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        super().__init__(
            f"contact entity id {entity_id!r} collides with another entity in the document; "
            "observer names must be distinct from object names and from each other (with one "
            "placement each), and no two contacts may share an observer and target"
        )


class ManeuverOutsideTrajectoryError(GmatCzmlError):
    """A maneuver whose ignition (or finite-burn cut-off) falls outside the trajectory's time span.

    A maneuver carries no position of its own, so the converter interpolates the marker location
    from the trajectory at the burn epoch. A burn before the first state or after the last has no
    orbit beneath it to pin to, so it is rejected rather than clamped to an endpoint. Like
    :class:`UnknownContactTargetError`, the trajectory input was valid — the mismatch is in the
    ``maneuvers`` argument — so this descends from :class:`GmatCzmlError` directly rather than
    :class:`SchemaError`. ``epoch`` is the offending ignition time (UTC) and ``span`` the
    trajectory's ``(start, end)`` it must fall within.
    """

    def __init__(self, epoch: datetime, span: tuple[datetime, datetime]) -> None:
        self.epoch = epoch
        self.span = span
        start, end = span
        super().__init__(
            f"maneuver ignition {epoch.isoformat()} falls outside the trajectory span "
            f"{start.isoformat()} .. {end.isoformat()}; the marker position is interpolated from "
            "the trajectory, so a burn outside its time span has no orbit to pin to"
        )


class AmbiguousManeuverTargetError(GmatCzmlError):
    """Maneuvers were supplied for a document with more than one object.

    A :class:`~orbit_formats.Maneuver` names neither a position nor a target craft, so gmat-czml
    attributes the maneuvers to the single rendered trajectory; with more than one object it cannot
    tell which craft each burn acts on, and refuses to guess. Like
    :class:`ManeuverOutsideTrajectoryError`, the inputs were individually valid — the ambiguity is
    in pairing them with the ``maneuvers`` argument — so this descends from :class:`GmatCzmlError`
    directly. ``count`` is the number of objects in the document.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"maneuvers are only supported for a single-object document, but {count} objects were "
            "given; a maneuver names no target craft, so which object each burn acts on is unclear"
        )


class SchemaError(GmatCzmlError, ValueError):
    """A canonical input that does not satisfy the schema contract.

    Base for every validation failure. Also a :class:`ValueError`, so the typed family
    stays catchable as the broad value error a malformed input naturally is.
    """


class MissingColumnError(SchemaError):
    """A required state column is absent from the DataFrame.

    ``columns`` holds the missing column names. ``Epoch, X, Y, Z`` are always required;
    velocity is optional, but declaring it *partially* (some of ``VX, VY, VZ`` but not all
    three) is a malformed declaration and reported here too.
    """

    def __init__(self, columns: Iterable[str]) -> None:
        self.columns: tuple[str, ...] = tuple(columns)
        joined = ", ".join(self.columns)
        super().__init__(f"DataFrame is missing required state column(s): {joined}")


class MissingFrameError(SchemaError):
    """No ``coordinate_system`` is declared on ``DataFrame.attrs``.

    The reference frame is load-bearing for the CZML reference frame, so it is required
    rather than guessed.
    """

    def __init__(self) -> None:
        super().__init__(
            "no reference frame declared; set attrs['coordinate_system'] to one of the "
            "recognised frames (the frame is required, never guessed)"
        )


class UnknownFrameError(SchemaError):
    """A declared ``coordinate_system`` that is not in the recognised set.

    ``frame`` is the offending value and ``recognised`` the names gmat-czml accepts.
    """

    def __init__(self, frame: str, recognised: Iterable[str]) -> None:
        self.frame = frame
        self.recognised: tuple[str, ...] = tuple(recognised)
        joined = ", ".join(self.recognised)
        super().__init__(f"unrecognised reference frame {frame!r}; expected one of: {joined}")


class MissingTimeScaleError(SchemaError):
    """No time scale is declared on ``DataFrame.attrs``.

    Read from ``time_scale``, falling back to ``epoch_scales['Epoch']``; when neither is
    present the scale is required rather than assumed, since the CZML clock is built in UTC.
    """

    def __init__(self) -> None:
        super().__init__(
            "no time scale declared; set attrs['time_scale'] (or attrs['epoch_scales']"
            "['Epoch']) to one of the recognised scales (the scale is required, never assumed)"
        )


class UnknownTimeScaleError(SchemaError):
    """A declared time scale that is not one of the recognised scales.

    ``time_scale`` is the offending value and ``recognised`` the scales gmat-czml accepts.
    """

    def __init__(self, time_scale: str, recognised: Iterable[str]) -> None:
        self.time_scale = time_scale
        self.recognised: tuple[str, ...] = tuple(recognised)
        joined = ", ".join(self.recognised)
        super().__init__(f"unrecognised time scale {time_scale!r}; expected one of: {joined}")


class InvalidUnitsError(SchemaError):
    """The ``units`` metadata is malformed.

    ``attrs['units']`` must be a mapping whose recognised keys (``length`` / ``speed`` /
    ``angle`` / ``time``) carry non-empty unit strings. ``detail`` describes what was wrong.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"malformed units metadata: {detail}")


class EmptyTrajectoryError(SchemaError):
    """There is nothing to convert — a state series with no samples, or no inputs at all."""


class DuplicateObjectNameError(SchemaError):
    """Two inputs in a multi-object collection share the same ``object_name``.

    Object identity comes from ``attrs['object_name']``, so two trajectories carrying the
    same name are ambiguous. ``name`` is the colliding value.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"duplicate object_name {name!r} in the input collection; "
            "object identity must be unique"
        )


class MalformedStateError(SchemaError):
    """The state arrays could not be parsed.

    Non-numeric values, an unparseable epoch, or a shape the canonical layer rejects. Wraps
    the upstream :class:`ValueError` (available as the exception ``__cause__``) so the failure
    surfaces as a typed gmat-czml error rather than a bare parse error.
    """
