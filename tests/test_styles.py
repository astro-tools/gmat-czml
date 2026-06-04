"""Tests for the style model and the preset registry (``gmat_czml.styles``).

These pin the customization API this module owns: that the default :class:`~gmat_czml.styles.Style`
is the ``sat-default`` look (so an unflagged render reproduces it), that the sub-styles carry
the right defaults and are freely overridable, that the marker is a point *or* an image billboard,
and that named presets resolve through :func:`~gmat_czml.styles.preset` — the palette colouring the
marker / path / track a single hue, and an unknown name rejected rather than guessed.

The byte-for-byte equality of the ``sat-default`` *output* is locked by the golden suite; here the
concern is the data model and the registry.
"""

from __future__ import annotations

import dataclasses

import pytest

from gmat_czml import (
    PRESET_NAMES,
    ImageBillboard,
    LabelStyle,
    PathStyle,
    PointStyle,
    Style,
    TrackStyle,
    preset,
)
from gmat_czml.errors import UnknownStyleError

# --- the sat-default defaults -------------------------------------------------------------


def test_default_style_is_sat_default() -> None:
    style = Style()
    assert style.name == "sat-default"
    assert isinstance(style.marker, PointStyle)


def test_element_defaults_are_the_sat_default_values() -> None:
    # The defaults are the baked-in sat-default look: a yellow dot with a thin black outline, a
    # white name label, a thin yellow orbit trail, and a slightly heavier yellow ground track.
    assert PointStyle() == PointStyle(
        color=(255, 255, 0, 255), pixel_size=10.0, outline_color=(0, 0, 0, 255), outline_width=1.0
    )
    assert LabelStyle() == LabelStyle(color=(255, 255, 255, 255), font="11pt Lucida Console")
    assert PathStyle() == PathStyle(color=(255, 255, 0, 255), width=1.5)
    assert TrackStyle() == TrackStyle(color=(255, 255, 0, 255), width=2.0)


def test_styles_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Style().name = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        PointStyle().pixel_size = 99.0  # type: ignore[misc]


# --- the customization API ----------------------------------------------------------------


def test_fields_are_overridable_independently() -> None:
    style = Style(
        marker=PointStyle(color=(1, 2, 3, 255), pixel_size=4.0),
        label=LabelStyle(font="20pt Arial"),
        path=PathStyle(width=9.0),
        track=TrackStyle(color=(9, 8, 7, 255)),
    )
    assert style.marker == PointStyle(color=(1, 2, 3, 255), pixel_size=4.0)
    assert style.label.font == "20pt Arial"
    # An unset field on an overridden element keeps its default (the outline stays default black).
    assert isinstance(style.marker, PointStyle)
    assert style.marker.outline_color == (0, 0, 0, 255)
    assert style.path.width == 9.0
    assert style.path.color == (255, 255, 0, 255)  # path colour untouched


def test_image_billboard_marker() -> None:
    glyph = ImageBillboard(image="data:image/png;base64,AAAA")
    assert glyph.scale == 1.0  # default scale
    style = Style(marker=glyph)
    assert style.marker is glyph


# --- the preset registry ------------------------------------------------------------------


def test_sat_default_preset_is_the_default_style() -> None:
    assert preset("sat-default") == Style()


def test_preset_names_lists_sat_default_first() -> None:
    assert PRESET_NAMES[0] == "sat-default"
    assert set(PRESET_NAMES) == {"sat-default", "sat-red", "sat-green", "sat-magenta"}


@pytest.mark.parametrize("name", [n for n in PRESET_NAMES if n != "sat-default"])
def test_palette_preset_colours_marker_path_and_track_one_hue(name: str) -> None:
    style = preset(name)
    assert style.name == name
    assert isinstance(style.marker, PointStyle)
    colour = style.marker.color
    # The palette presets paint the marker, orbit trail, and ground track the same hue...
    assert style.path.color == colour
    assert style.track.color == colour
    assert colour != (255, 255, 0, 255)  # ...a hue distinct from the sat-default yellow
    # ...while keeping the sat-default sizes, outline, and white label.
    assert style.marker.pixel_size == 10.0
    assert style.marker.outline_color == (0, 0, 0, 255)
    assert style.label == LabelStyle()
    assert style.path.width == 1.5
    assert style.track.width == 2.0


def test_unknown_preset_is_rejected_with_the_recognised_set() -> None:
    with pytest.raises(UnknownStyleError) as excinfo:
        preset("sat-bogus")
    assert excinfo.value.name == "sat-bogus"
    assert excinfo.value.recognised == PRESET_NAMES
