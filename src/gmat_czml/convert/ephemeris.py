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
- **The visual style** — the marker (a coloured point or an image billboard), the name label, and
  the orbit path — is driven by the supplied :class:`~gmat_czml.styles.Style`, whose defaults are
  the ``sat-default`` look. Style fields set the colour, width, pixel size, font, and glyph; the
  marker's layout (the label offset and anchoring) is the converter's, not the style's.

Multiple objects are handled upstream (one trajectory per packet); a multi-segment ephemeris is one
chronologically-ordered, concatenated sample series here, so it renders as a single position
property spanning the whole span.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from czml3.enums import HorizontalOrigins, InterpolationAlgorithms, VerticalOrigins
from czml3.properties import (
    Billboard,
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
from gmat_czml.styles import ImageBillboard, LabelStyle, PathStyle, PointStyle, Style

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

# The colours, widths, pixel size, font, and glyph come from the supplied Style (its defaults are
# the sat-default look). The label's *layout* is the converter's, not the style's: the text is
# nudged clear of the marker glyph by this fixed pixel offset and anchored to its left.
_LABEL_PIXEL_OFFSET = (12.0, 0.0)  # nudge the text clear of the marker glyph

# Path lead default (seconds). Trail defaults to the full span (see :func:`orbit_geometry`), so a
# lead of 0 and a full-span trail draw the whole orbit trail behind the point up to the current
# animation time.
_DEFAULT_LEAD_SECONDS = 0.0


@dataclass(frozen=True)
class OrbitGeometry:
    """The CZML geometry for one object's orbit path.

    The properties the converter produces for an entity packet: the sampled ``position`` (metres,
    carrying the interpolation hint and reference frame), the ``path`` (lead / trail), the marker
    glyph, and the ``label``. The marker is *either* a ``point`` (a coloured dot) *or* a
    ``billboard`` (an image), per the style's ``marker`` — exactly one is set and the other is
    ``None``. :func:`gmat_czml.assembly` composes these onto the packet that already carries the
    object's identity and availability.
    """

    position: Position
    path: Path
    point: Point | None
    billboard: Billboard | None
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
    span); the marker and ``label`` mark and name the object. ``label_text`` is the display name
    (the object's name, or its positional id when unnamed).

    ``style`` drives the visual style: ``style.path`` colours and widths the orbit trail,
    ``style.marker`` is the glyph (a coloured point, or an image billboard that replaces it), and
    ``style.label`` colours and fonts the name label. ``Style()`` is the ``sat-default`` look.

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
    point, billboard = _marker(style.marker)
    return OrbitGeometry(
        position=position,
        path=_path(style.path, lead_seconds, trail),
        point=point,
        billboard=billboard,
        label=_label(style.label, label_text),
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


def _path(style: PathStyle, lead_seconds: float, trail_seconds: float) -> Path:
    """The orbit-trail path in the style's path colour and width."""
    return Path(
        show=True,
        leadTime=lead_seconds,
        trailTime=trail_seconds,
        width=style.width,
        material=PolylineMaterial(
            solidColor=SolidColorMaterial(color=Color(rgba=list(style.color)))
        ),
    )


def _marker(marker: PointStyle | ImageBillboard) -> tuple[Point | None, Billboard | None]:
    """The marker glyph: a coloured ``point``, or an image ``billboard`` that replaces it.

    Exactly one is built and the other is ``None``: a :class:`~gmat_czml.styles.PointStyle`
    yields the point, an :class:`~gmat_czml.styles.ImageBillboard` yields the billboard.
    """
    if isinstance(marker, ImageBillboard):
        return None, _billboard(marker)
    return _point(marker), None


def _point(style: PointStyle) -> Point:
    """The marker as a coloured :class:`~czml3.properties.Point` (a dot with an outline)."""
    return Point(
        show=True,
        pixelSize=style.pixel_size,
        color=Color(rgba=list(style.color)),
        outlineColor=Color(rgba=list(style.outline_color)),
        outlineWidth=style.outline_width,
    )


def _billboard(style: ImageBillboard) -> Billboard:
    """The marker as an image :class:`~czml3.properties.Billboard` from the style's image."""
    return Billboard(show=True, image=style.image, scale=style.scale)


def _label(style: LabelStyle, text: str) -> Label:
    """The object's name label in the style's fill colour and font, offset clear of the marker."""
    return Label(
        show=True,
        text=text,
        font=style.font,
        fillColor=Color(rgba=list(style.color)),
        horizontalOrigin=HorizontalOrigins.LEFT,
        verticalOrigin=VerticalOrigins.CENTER,
        pixelOffset=Cartesian2Value(values=list(_LABEL_PIXEL_OFFSET)),
    )
