"""The public assembly entry point.

:func:`to_czml` is the one call a producer makes. It validates the canonical input (the
:mod:`gmat_czml.schema` boundary), synthesizes the document clock from the trajectory span,
drives the per-entity converters, and returns a :class:`~gmat_czml.document.CzmlDocument` whose
JSON / dict / file forms are all produced in memory.

The assembly is the skeleton the per-entity converters fill: it lays down the document preamble
with a synthesized clock and one packet per object, carrying each object's identity and
availability. The position property, path, billboard, and label — and the application of a
``style`` — are produced by the ephemeris geometry converter; the leap-second-correct
time-scale → UTC conversion and richer clock tuning are the clock-synthesis converter's.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np
import pandas as pd
from czml3 import CZML_VERSION, Document, Packet
from czml3.properties import Clock
from czml3.types import TimeInterval

from gmat_czml.document import CzmlDocument
from gmat_czml.schema import CanonicalInput, normalize_inputs
from gmat_czml.styles import Style

__all__ = ["to_czml"]

# The CZML document preamble carries the id ``"document"`` by convention, plus the version and
# the document clock.
_DOCUMENT_ID = "document"
_DOCUMENT_NAME = "gmat-czml"

# A starting clock rate (simulated seconds per real second) so the assembled document animates
# rather than playing back at real-time speed. The span-aware default and the rest of clock
# tuning belong to the clock-synthesis converter; this is the structural placeholder.
_DEFAULT_CLOCK_MULTIPLIER = 60


def to_czml(
    ephemeris: object,
    *,
    style: Style | None = None,
    contacts: object = None,
    maneuvers: object = None,
    attitude: object = None,
) -> CzmlDocument:
    """Convert a canonical trajectory into a :class:`~gmat_czml.document.CzmlDocument`.

    ``ephemeris`` is a canonical state-series :class:`~pandas.DataFrame`, an orbit-formats
    ``Ephemeris``, or an iterable of either (one trajectory per object) — whatever
    :func:`gmat_czml.schema.normalize_inputs` accepts. ``style`` selects the visual style;
    ``None`` uses the default. The document is assembled entirely in memory.

    ``contacts``, ``maneuvers``, and ``attitude`` are accepted so the call signature is stable,
    but are not yet emitted — they arrive in a later release.

    Raises a :class:`~gmat_czml.errors.SchemaError` (the typed family) for a malformed input,
    naming exactly what is wrong.
    """
    inputs = normalize_inputs(ephemeris)
    preamble = Packet(
        id=_DOCUMENT_ID,
        name=_DOCUMENT_NAME,
        version=CZML_VERSION,
        clock=_synthesize_clock(inputs),
    )
    entities = [_entity_packet(item, index, style) for index, item in enumerate(inputs)]
    return CzmlDocument(Document(packets=[preamble, *entities]))


def _synthesize_clock(inputs: Sequence[CanonicalInput]) -> Clock:
    """Synthesize the document clock spanning the full trajectory.

    The interval runs from the earliest to the latest epoch across every input, and the clock
    starts at the interval start. Epochs are read as UTC: a UTC trajectory's synthesized span is
    already exact, and the leap-second-correct time-scale → UTC conversion (for TAI / TT / TDB /
    GPS / UT1 inputs) is layered on by the clock-synthesis converter.
    """
    bounds = [_epoch_bounds(item) for item in inputs]
    start = min(lo for lo, _ in bounds)
    end = max(hi for _, hi in bounds)
    return Clock(
        currentTime=start,
        multiplier=_DEFAULT_CLOCK_MULTIPLIER,
        interval=TimeInterval(start=start, end=end),
    )


def _entity_packet(item: CanonicalInput, index: int, style: Style | None) -> Packet:
    """The CZML packet for one object — its identity and availability.

    The position property, path, billboard, and label, and the application of ``style``, are
    filled in by the ephemeris geometry converter; ``style`` is threaded through to that seam.
    """
    start, end = _epoch_bounds(item)
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


def _epoch_bounds(item: CanonicalInput) -> tuple[dt.datetime, dt.datetime]:
    """The earliest and latest epoch of one trajectory, as UTC-aware datetimes."""
    epochs = item.ephemeris.epochs
    return _to_datetime(epochs.min()), _to_datetime(epochs.max())


def _to_datetime(epoch: np.datetime64) -> dt.datetime:
    """A ``datetime64`` epoch as a UTC-aware :class:`~datetime.datetime`."""
    return pd.Timestamp(epoch).to_pydatetime().replace(tzinfo=dt.timezone.utc)
