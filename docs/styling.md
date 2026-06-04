# Styling

gmat-czml v0.1 ships a **single baked-in visual style**, `sat-default`, applied to every object's
point, label, path, and ground track. It is deliberately minimal: the goal of v0.1 is correct
geometry on a clock, not a theming system.

## The default style

| Element | Appearance |
|---------|------------|
| Point | a yellow dot with a thin black outline |
| Label | the object's name in white, offset clear of the point |
| Orbit path | a yellow trail |
| Ground track | the same yellow, a touch heavier against the globe |

## The `Style` handle

[`Style`][gmat_czml.Style] denotes that default. `to_czml(trajectory)` uses it when no `style` is
given, so these are equivalent:

```python
from gmat_czml import Style, to_czml

to_czml(trajectory)
to_czml(trajectory, style=Style())          # the same default
to_czml(trajectory, style=Style("sat-default"))
```

`Style` is the stable seam the customization API plugs into. Colour / width / glyph fields, named
presets, and image billboards are a later release; in v0.1 `Style` carries only the default name.
The [command line](cli.md) exposes the same single choice through `--style sat-default`.
