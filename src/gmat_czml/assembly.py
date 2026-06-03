"""The public assembly entry point.

:func:`to_czml` is the one call a producer makes. It validates the canonical input (the
:mod:`gmat_czml.schema` boundary), synthesizes the document clock from the trajectory span,
drives the per-entity converters, and returns a :class:`~gmat_czml.document.CzmlDocument` whose
JSON / dict / file forms are all produced in memory.

The assembly is the skeleton the per-entity converters fill: it lays down the document preamble
and one packet per object. The clock and each object's UTC availability are synthesized by
:mod:`gmat_czml.convert.time`; the position property, path, billboard, and label — and the
application of a ``style`` — are produced by the ephemeris geometry converter.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeAlias

import pandas as pd
from czml3 import CZML_VERSION, Document, Packet
from czml3.types import TimeInterval
from orbit_formats import Attitude, Ephemeris, Maneuver

from gmat_czml.convert.time import synthesize_clock, utc_span
from gmat_czml.document import CzmlDocument
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
    contacts: object = None,
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

    ``contacts``, ``maneuvers``, and ``attitude`` are accepted so the call signature is stable
    but are not yet emitted — they arrive in a later release. ``maneuvers`` and ``attitude``
    already take orbit-formats' canonical types; ``contacts`` is loosely typed until the
    contact-interval support that defines its shape lands.

    Raises a :class:`~gmat_czml.errors.SchemaError` (the typed family) for a malformed input,
    naming exactly what is wrong, or :class:`ValueError` if ``playback_seconds`` is not positive.
    """
    inputs = normalize_inputs(ephemeris)
    preamble = Packet(
        id=_DOCUMENT_ID,
        name=_DOCUMENT_NAME,
        version=CZML_VERSION,
        clock=synthesize_clock(inputs, playback_seconds=playback_seconds),
    )
    entities = [_entity_packet(item, index, style) for index, item in enumerate(inputs)]
    return CzmlDocument(Document(packets=[preamble, *entities]))


def _entity_packet(item: CanonicalInput, index: int, style: Style | None) -> Packet:
    """The CZML packet for one object — its identity and UTC availability.

    The position property, path, billboard, and label, and the application of ``style``, are
    filled in by the ephemeris geometry converter; ``style`` is threaded through to that seam.
    """
    start, end = utc_span(item)
    return Packet(
        id=_entity_id(item, index),
        name=item.object_name,
        availability=TimeInterval(start=start, end=end),
    )


def _entity_id(item: CanonicalInput, index: int) -> str:
    """A stable CZML id for the object — its declared name, else a position-based fallback.

    Declared object names are unique across the collection (enforced upstream by
    :func:`~gmat_czml.schema.normalize_inputs`); an object without a name gets ``object-<index>``.
    """
    name = item.object_name
    if name is not None and name.strip():
        return name
    return f"object-{index}"
