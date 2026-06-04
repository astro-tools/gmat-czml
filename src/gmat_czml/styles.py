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

The maneuver, contact, and attitude converters carry their own distinct layer styles (orange /
cyan) rather than this satellite style; this customization API covers the satellite layer only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gmat_czml.errors import UnknownStyleError

__all__ = [
    "PRESET_NAMES",
    "RGBA",
    "ImageBillboard",
    "LabelStyle",
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
class Style:
    """The visual style applied to one rendered object's satellite layer.

    ``name`` is the style's identity (the preset name a :func:`preset` lookup returns); the four
    element fields drive the emitted geometry:

    - ``marker`` — the object's glyph, either a coloured :class:`PointStyle` (the default) or an
      :class:`ImageBillboard` image, exactly one of the two;
    - ``label`` — the name :class:`LabelStyle`;
    - ``path`` — the orbit-trail :class:`PathStyle`;
    - ``track`` — the ground-:class:`TrackStyle`.

    The defaults are ``sat-default``, so ``Style()`` is the baked-in look :func:`gmat_czml.to_czml`
    applies when given no ``style``. Build a custom style by overriding any field —
    ``Style(marker=PointStyle(color=(0, 255, 0, 255)), path=PathStyle(width=3.0))`` — or resolve a
    named preset with :func:`preset`.
    """

    name: str = "sat-default"
    marker: PointStyle | ImageBillboard = field(default_factory=PointStyle)
    label: LabelStyle = field(default_factory=LabelStyle)
    path: PathStyle = field(default_factory=PathStyle)
    track: TrackStyle = field(default_factory=TrackStyle)


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
