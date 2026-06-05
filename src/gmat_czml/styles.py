"""Style presets and the colour / width / glyph customization API.

A :class:`Style` is the visual style applied to one rendered object's **satellite layer** — its
marker (a coloured :class:`PointStyle` *or* an :class:`ImageBillboard` glyph), its name
:class:`LabelStyle`, its orbit-:class:`PathStyle`, and its ground-:class:`TrackStyle`. The
ephemeris and ground-track converters read these fields to drive their output, so a custom
``Style`` changes the emitted colour, width, pixel size, font, and glyph.

The defaults reproduce the ``sat-default`` look — a yellow dot, a white name label, and a yellow
orbit trail / ground track — so ``Style()`` (and an unflagged :func:`gmat_czml.to_czml`) renders
exactly that. Named presets resolve through :func:`preset`: ``sat-default`` plus a small palette of
single-colour variants for telling several objects apart in a multi-object scene.

The maneuver, contact, and attitude annotations are separate layers with their own styles (orange /
cyan by default) — :class:`ManeuverStyle`, :class:`ContactStyle`, and :class:`AttitudeStyle`, also
carried on :class:`Style` — so a custom style can recolour those layers too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gmat_czml.errors import UnknownStyleError

__all__ = [
    "PRESET_NAMES",
    "RGBA",
    "AttitudeStyle",
    "ContactStyle",
    "ImageBillboard",
    "LabelStyle",
    "LineStyle",
    "ManeuverStyle",
    "PathStyle",
    "PointStyle",
    "Style",
    "TrackStyle",
    "preset",
]

# An RGBA colour with channels in 0-255, the order CZML's ``Color.rgba`` carries.
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class PointStyle:
    """The marker glyph as a coloured point — a filled dot with an outline.

    ``color`` fills the dot and ``outline_color`` / ``outline_width`` draw its border;
    ``pixel_size`` is the dot's screen size in pixels. Channels are 0-255. The defaults are the
    ``sat-default`` marker: a yellow dot with a thin black outline.
    """

    color: RGBA = (255, 255, 0, 255)
    pixel_size: float = 10.0
    outline_color: RGBA = (0, 0, 0, 255)
    outline_width: float = 1.0


@dataclass(frozen=True)
class ImageBillboard:
    """The marker glyph as an image billboard — a screen-facing image in place of the point.

    ``image`` is the image source: any URI a Cesium client can load, including an ``http(s)`` URL or
    a ``data:`` URI with the image inlined (gmat-czml ships no asset pipeline, so the caller
    supplies the image). ``scale`` multiplies the image's native pixel size. Setting a ``Style``'s
    ``marker`` to an :class:`ImageBillboard` replaces the coloured point with the billboard.
    """

    image: str
    scale: float = 1.0


@dataclass(frozen=True)
class LabelStyle:
    """The object's name label — its fill colour and font.

    ``color`` is the text fill (channels 0-255) and ``font`` is a CSS-style font string. The label's
    layout (its offset clear of the marker and its anchoring) is fixed by the converter, not styled
    here. The defaults are the ``sat-default`` label: white text in a small monospace font.
    """

    color: RGBA = (255, 255, 255, 255)
    font: str = "11pt Lucida Console"


@dataclass(frozen=True)
class PathStyle:
    """The orbit trail — its line colour and width.

    ``color`` (channels 0-255) and ``width`` (pixels) draw the trailing orbit path behind the
    object. The defaults are the ``sat-default`` trail: a thin yellow line.
    """

    color: RGBA = (255, 255, 0, 255)
    width: float = 1.5


@dataclass(frozen=True)
class TrackStyle:
    """The ground track — its line colour and width.

    ``color`` (channels 0-255) and ``width`` (pixels) draw the sub-satellite ground-track polyline.
    The defaults are the ``sat-default`` track: the orbit trail's yellow, a touch heavier so it
    reads against the globe.
    """

    color: RGBA = (255, 255, 0, 255)
    width: float = 2.0


@dataclass(frozen=True)
class LineStyle:
    """A line — its colour and width.

    ``color`` (channels 0-255) and ``width`` (pixels) draw a generic line: the maneuver burn arc and
    the contact line of sight. Unlike :class:`PathStyle` / :class:`TrackStyle`, which name the
    satellite's own orbit trail and ground track, this is the neutral line style the annotation
    layers reuse.
    """

    color: RGBA
    width: float


@dataclass(frozen=True)
class ManeuverStyle:
    """The maneuver annotation layer — its marker, label, and burn-arc styles.

    A maneuver renders as a marker (a point + label, for an impulsive burn or a finite burn's
    companion) and, for a finite burn, a burn arc. ``marker`` styles the point, ``label`` the text,
    and ``arc`` the finite-burn line. The defaults are the baked-in maneuver look: an orange marker
    and arc with a white label, drawn as their own layer distinct from the satellite.
    """

    marker: PointStyle = field(
        default_factory=lambda: PointStyle(color=(255, 140, 0, 255), pixel_size=11.0)
    )
    label: LabelStyle = field(default_factory=LabelStyle)
    arc: LineStyle = field(default_factory=lambda: LineStyle(color=(255, 140, 0, 255), width=3.0))


@dataclass(frozen=True)
class ContactStyle:
    """The contact annotation layer — its observer marker, label, and line-of-sight styles.

    A contact renders an observer entity (a point + label at the ground station) and an observer ->
    satellite link. ``observer`` styles the point, ``label`` the text, and ``link`` the line of
    sight. The defaults are the baked-in contact look: a cyan observer and link with a white label,
    drawn as the ground / line-of-sight layer distinct from the satellite.
    """

    observer: PointStyle = field(
        default_factory=lambda: PointStyle(color=(0, 255, 255, 255), pixel_size=8.0)
    )
    label: LabelStyle = field(default_factory=LabelStyle)
    link: LineStyle = field(default_factory=lambda: LineStyle(color=(0, 255, 255, 255), width=1.0))


@dataclass(frozen=True)
class AttitudeStyle:
    """The attitude annotation layer — the body box's fill and outline colours.

    The attitude marker is a schematic body box; ``box_fill_color`` fills it (channels 0-255, with a
    translucent alpha by default) and ``box_outline_color`` / ``box_outline_width`` draw its edges.
    The box's dimensions are fixed by the converter (three distinct, exaggerated axes so the
    orientation reads), not styled here. The defaults are the baked-in translucent-cyan body box.
    """

    box_fill_color: RGBA = (0, 200, 255, 110)
    box_outline_color: RGBA = (0, 200, 255, 255)
    box_outline_width: float = 1.0


@dataclass(frozen=True)
class Style:
    """The visual style applied to one rendered object and its annotation layers.

    ``name`` is the style's identity (the preset name a :func:`preset` lookup returns). The
    **satellite-layer** fields drive the object's own geometry:

    - ``marker`` — the object's glyph, either a coloured :class:`PointStyle` (the default) or an
      :class:`ImageBillboard` image, exactly one of the two;
    - ``label`` — the name :class:`LabelStyle`;
    - ``path`` — the orbit-trail :class:`PathStyle`;
    - ``track`` — the ground-:class:`TrackStyle`.

    The **annotation-layer** fields style the optional annotations, each with its own default look:

    - ``maneuver`` — the :class:`ManeuverStyle` for burn markers and arcs (orange);
    - ``contact`` — the :class:`ContactStyle` for observers and lines of sight (cyan);
    - ``attitude`` — the :class:`AttitudeStyle` for the body-orientation box (translucent cyan).

    The defaults are ``sat-default``, so ``Style()`` is the baked-in look :func:`gmat_czml.to_czml`
    applies when given no ``style``. Build a custom style by overriding any field —
    ``Style(marker=PointStyle(color=(0, 255, 0, 255)), path=PathStyle(width=3.0))`` — or resolve a
    named preset with :func:`preset`. The palette presets recolour only the satellite layer; the
    annotation layers keep their semantic colours unless you override them.
    """

    name: str = "sat-default"
    marker: PointStyle | ImageBillboard = field(default_factory=PointStyle)
    label: LabelStyle = field(default_factory=LabelStyle)
    path: PathStyle = field(default_factory=PathStyle)
    track: TrackStyle = field(default_factory=TrackStyle)
    maneuver: ManeuverStyle = field(default_factory=ManeuverStyle)
    contact: ContactStyle = field(default_factory=ContactStyle)
    attitude: AttitudeStyle = field(default_factory=AttitudeStyle)


# The single-colour palette presets, beyond ``sat-default``: well-separated hues (distinct from each
# other and from the orange maneuver / cyan contact layers) for telling several objects apart in a
# multi-object scene. Each colours the marker, the orbit trail, and the ground track the same hue,
# keeping the ``sat-default`` sizes, outline, and white label.
_PALETTE: dict[str, RGBA] = {
    "sat-red": (255, 80, 80, 255),
    "sat-green": (60, 200, 120, 255),
    "sat-magenta": (235, 90, 235, 255),
}


def _solid(name: str, color: RGBA) -> Style:
    """A preset that paints the marker, orbit trail, and ground track a single ``color``."""
    return Style(
        name=name,
        marker=PointStyle(color=color),
        path=PathStyle(color=color),
        track=TrackStyle(color=color),
    )


# The named-preset registry. ``sat-default`` is the seed (the bare defaults); the palette presets
# follow. :data:`PRESET_NAMES` and the CLI ``--style`` choices both derive from this, so adding a
# preset here surfaces it everywhere.
_PRESETS: dict[str, Style] = {
    "sat-default": Style(),
    **{name: _solid(name, color) for name, color in _PALETTE.items()},
}

# The recognised preset names, in registry order (``sat-default`` first). The CLI ``--style`` flag
# offers exactly these.
PRESET_NAMES: tuple[str, ...] = tuple(_PRESETS)


def preset(name: str) -> Style:
    """The named preset :class:`Style`, or raise :class:`~gmat_czml.errors.UnknownStyleError`.

    ``name`` must be one of :data:`PRESET_NAMES` (``sat-default`` plus the colour palette). The
    preset is resolved, never guessed: an unrecognised name is rejected with the recognised set
    rather than silently falling back to the default.
    """
    try:
        return _PRESETS[name]
    except KeyError:
        raise UnknownStyleError(name, PRESET_NAMES) from None
