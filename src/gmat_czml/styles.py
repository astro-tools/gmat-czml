"""Style presets and the customization API.

A default style for the satellite point, label, and path, and the colour / width / glyph
customization API over it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Style"]


@dataclass(frozen=True)
class Style:
    """The visual style applied to a rendered object.

    A single baked-in default (``"sat-default"``) is applied to every object's point, label, and
    path; the colour / width / glyph customization fields and the preset system are a later
    release. ``Style()`` denotes that default, which :func:`gmat_czml.to_czml` also uses when no
    ``style`` is given.
    """

    name: str = "sat-default"
