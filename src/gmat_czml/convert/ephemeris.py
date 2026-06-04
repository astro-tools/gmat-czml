"""State ephemeris to a CZML orbit path.

The core geometry converter: one validated trajectory becomes the four CZML properties an entity
packet carries — a sampled cartesian **position**, a **path**, a **point**, and a **label** — which
:mod:`gmat_czml.assembly` composes onto the packet that already holds the object's identity and UTC
availability.

What this module owns:

- **Metres, not kilometres.** CZML cartesian is metric; the canonical default is kilometres, so
  every position value is scaled to metres by the declared ``units.length`` (D2). A meta-test guards
  against a converter accidentally emitting kilometres.
- **Interpolation passthrough.** The source's ``interpolation`` / ``interpolation_degree`` are
  carried onto the position as ``interpolationAlgorithm`` / ``interpolationDegree`` so the client
  reproduces the curve between sparse samples rather than chording straight lines (D3). An
  undeclared algorithm defaults to Lagrange degree 5; an unknown one is rejected, never guessed.
- **Compact, decimated samples.** Epochs are emitted as a single reference epoch plus per-sample
  second offsets (via :mod:`gmat_czml.convert.time`), and the path is tolerance-bounded-decimated
  (via :mod:`gmat_czml.convert.sampling`) with a ``min_samples`` floor of ``degree + 1`` so the
  declared curve keeps enough support (D9).
- **The reference frame** comes from :func:`gmat_czml.convert.frames.czml_reference_frame`.
- **The baked-in ``sat-default`` style** — the single v0.1 style — is applied to every object; the
  per-name preset system and the customization API are v0.2.

Multiple objects are handled upstream (one trajectory per packet); a multi-segment ephemeris is one
chronologically-ordered, concatenated sample series here, so it renders as a single position
property spanning the whole span.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from czml3.enums import HorizontalOrigins, InterpolationAlgorithms, VerticalOrigins
from czml3.properties import (
    Color,
    Label,
    Path,
    Point,
    PolylineMaterial,
    Position,
    SolidColorMaterial,
)
from czml3.types import Cartesian2Value
from numpy.typing import NDArray

from gmat_czml.convert.frames import czml_reference_frame
from gmat_czml.convert.sampling import DEFAULT_TOLERANCE_KM, decimate
from gmat_czml.convert.time import epoch_relative, to_utc
from gmat_czml.errors import InvalidUnitsError, UnknownInterpolationError
from gmat_czml.schema import CanonicalInput
from gmat_czml.styles import Style

__all__ = ["OrbitGeometry", "orbit_geometry"]

# Declared length unit -> metres (keys upper-cased). CZML cartesian is metric; the canonical default
# is kilometres, so every position component is scaled here (D2). Only the two physically standard
# length units are supported; any other is rejected rather than guessed, as the schema does.
_LENGTH_TO_METRES = {"KM": 1000.0, "M": 1.0}
_SUPPORTED_LENGTH_UNITS = ("km", "m")

# Source interpolation names -> the CZML enum (D3). Lookup is case- and whitespace-insensitive, so a
# GMAT ``Lagrange`` and a CCSDS ``LAGRANGE`` map to the same algorithm.
_INTERPOLATION = {
    "LAGRANGE": InterpolationAlgorithms.LAGRANGE,
    "HERMITE": InterpolationAlgorithms.HERMITE,
    "LINEAR": InterpolationAlgorithms.LINEAR,
}

# The orbit-path default when the source declares no interpolation: Lagrange degree 5 (D3). The same
# degree fills in for a declared algorithm that omits its degree.
_DEFAULT_ALGORITHM = InterpolationAlgorithms.LAGRANGE
_DEFAULT_DEGREE = 5

# The single baked-in "sat-default" style — the only style in v0.1; the customization API and the
# per-name preset system are v0.2. The visual values live here as the converter's rendering defaults
# (not in styles.py, whose per-name resolution is that later preset work) and are applied to every
# object. RGBA channels are 0-255.
_PATH_COLOR = (255, 255, 0, 255)  # a yellow orbit trail
_PATH_WIDTH = 1.5
_POINT_COLOR = (255, 255, 0, 255)
_POINT_OUTLINE_COLOR = (0, 0, 0, 255)
_POINT_PIXEL_SIZE = 10.0
_POINT_OUTLINE_WIDTH = 1.0
_LABEL_COLOR = (255, 255, 255, 255)
_LABEL_FONT = "11pt Lucida Console"
_LABEL_PIXEL_OFFSET = (12.0, 0.0)  # nudge the text clear of the point glyph

# Path lead default (seconds). Trail defaults to the full span (see :func:`orbit_geometry`), so a
# lead of 0 and a full-span trail draw the whole orbit trail behind the point up to the current
# animation time.
_DEFAULT_LEAD_SECONDS = 0.0


@dataclass(frozen=True)
class OrbitGeometry:
    """The CZML geometry for one object's orbit path.

    The four properties the converter produces for an entity packet: the sampled ``position``
    (metres, carrying the interpolation hint and the reference frame), the ``path`` (lead / trail),
    the ``point`` glyph, and the ``label``. :func:`gmat_czml.assembly` composes these onto the
    packet that already carries the object's identity and availability.
    """

    position: Position
    path: Path
    point: Point
    label: Label


def orbit_geometry(
    item: CanonicalInput,
    style: Style,
    *,
    label_text: str,
    tolerance_km: float = DEFAULT_TOLERANCE_KM,
    lead_seconds: float = _DEFAULT_LEAD_SECONDS,
    trail_seconds: float | None = None,
) -> OrbitGeometry:
    """Convert one validated trajectory into its CZML orbit-path geometry.

    Emits the position as a sampled cartesian in **metres** (scaled from the declared length unit),
    tagged with the source's interpolation algorithm and degree (D3) and the CZML reference frame
    (D4), over the samples a tolerance-bounded decimation pass keeps (D9, ``tolerance_km``). Epochs
    travel as a single reference epoch plus per-sample second offsets. The ``path`` shows the orbit
    trail with a configurable ``lead_seconds`` / ``trail_seconds`` (the trail defaults to the full
    span); the ``point`` and ``label`` mark and name the object. ``label_text`` is the display name
    (the object's name, or its positional id when unnamed).

    ``style`` selects the visual style; v0.1 has the single baked-in ``sat-default``, applied to
    every object, so it is accepted as the stable seam the v0.2 preset system plugs into rather than
    branched on here.

    Raises :class:`~gmat_czml.errors.InvalidUnitsError` for an unsupported length unit and
    :class:`~gmat_czml.errors.UnknownInterpolationError` for an interpolation name with no CZML
    equivalent.
    """
    algorithm, degree = _interpolation(item)
    positions_m = _positions_metres(item)
    epoch_iso, offsets = epoch_relative(to_utc(item.ephemeris.epochs, item.time_scale))

    # Decimation shares a unit between positions and tolerance, so the km tolerance goes to metres
    # alongside the metre positions; the floor keeps degree + 1 samples for the declared curve (D9).
    kept = decimate(positions_m, tolerance=tolerance_km * 1000.0, min_samples=degree + 1).indices

    position = Position(
        epoch=epoch_iso,
        referenceFrame=czml_reference_frame(item.frame),
        interpolationAlgorithm=algorithm,
        interpolationDegree=degree,
        cartesian=_cartesian(offsets[kept], positions_m[kept]),
    )
    trail = float(offsets[-1]) if trail_seconds is None else trail_seconds
    return OrbitGeometry(
        position=position,
        path=_path(lead_seconds, trail),
        point=_point(),
        label=_label(label_text),
    )


def _interpolation(item: CanonicalInput) -> tuple[InterpolationAlgorithms, int]:
    """The CZML interpolation algorithm and degree to carry, from the source hint (D3).

    An undeclared algorithm yields the orbit-path default (Lagrange degree 5); a declared one maps
    case-insensitively and keeps its declared degree (defaulting the degree when absent). An
    unrecognised algorithm name raises :class:`~gmat_czml.errors.UnknownInterpolationError`.
    """
    name = item.ephemeris.interpolation
    if name is None:
        return _DEFAULT_ALGORITHM, _DEFAULT_DEGREE
    algorithm = _INTERPOLATION.get(name.strip().upper())
    if algorithm is None:
        raise UnknownInterpolationError(name, sorted(_INTERPOLATION))
    degree = item.ephemeris.interpolation_degree
    return algorithm, _DEFAULT_DEGREE if degree is None else int(degree)


def _positions_metres(item: CanonicalInput) -> NDArray[np.float64]:
    """The trajectory's positions in metres, scaled from the declared length unit (D2)."""
    unit = item.ephemeris.metadata.units.length
    factor = _LENGTH_TO_METRES.get(unit.strip().upper())
    if factor is None:
        supported = ", ".join(_SUPPORTED_LENGTH_UNITS)
        raise InvalidUnitsError(
            f"length unit {unit!r} is not supported by the orbit-path converter; "
            f"supported units: {supported}"
        )
    positions = np.asarray(item.ephemeris.positions, dtype=np.float64)
    return np.asarray(positions * factor, dtype=np.float64)


def _cartesian(offsets: NDArray[np.float64], positions: NDArray[np.float64]) -> list[float]:
    """Interleave epoch offsets and metre positions into a flat ``[t, x, y, z, ...]`` list."""
    samples = np.column_stack([offsets, positions])
    return [float(value) for value in samples.reshape(-1)]


def _path(lead_seconds: float, trail_seconds: float) -> Path:
    """The orbit-trail path in the ``sat-default`` style."""
    return Path(
        show=True,
        leadTime=lead_seconds,
        trailTime=trail_seconds,
        width=_PATH_WIDTH,
        material=PolylineMaterial(
            solidColor=SolidColorMaterial(color=Color(rgba=list(_PATH_COLOR)))
        ),
    )


def _point() -> Point:
    """The object's marker glyph in the ``sat-default`` style.

    A self-contained :class:`~czml3.properties.Point` (a coloured dot), not an image billboard —
    v0.1 ships no asset pipeline, so image-glyph billboards arrive with the v0.2 style system.
    """
    return Point(
        show=True,
        pixelSize=_POINT_PIXEL_SIZE,
        color=Color(rgba=list(_POINT_COLOR)),
        outlineColor=Color(rgba=list(_POINT_OUTLINE_COLOR)),
        outlineWidth=_POINT_OUTLINE_WIDTH,
    )


def _label(text: str) -> Label:
    """The object's name label in the ``sat-default`` style, offset clear of the point."""
    return Label(
        show=True,
        text=text,
        font=_LABEL_FONT,
        fillColor=Color(rgba=list(_LABEL_COLOR)),
        horizontalOrigin=HorizontalOrigins.LEFT,
        verticalOrigin=VerticalOrigins.CENTER,
        pixelOffset=Cartesian2Value(values=list(_LABEL_PIXEL_OFFSET)),
    )
