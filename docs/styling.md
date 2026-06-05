# Styling

Every rendered object carries a **satellite-layer style** — its marker, name label, orbit path, and
ground track. gmat-czml ships named presets and a small colour / width / glyph customization API over
them. The default, `sat-default`, is a yellow dot with a white name label and a yellow orbit trail /
ground track; an unflagged `to_czml(trajectory)` renders exactly that.

## Presets

[`preset(name)`][gmat_czml.preset] resolves a named preset to a [`Style`][gmat_czml.Style]:

```python
from gmat_czml import preset, to_czml

to_czml(trajectory, style=preset("sat-red")).save("orbit.czml")
```

| Preset | Colour |
|--------|--------|
| `sat-default` | yellow |
| `sat-red` | red |
| `sat-green` | green |
| `sat-magenta` | magenta |

The palette presets paint the marker, orbit trail, and ground track a single hue — for telling
several objects apart in a multi-object scene — while keeping the default sizes, outline, and white
label. An unknown name raises `UnknownStyleError` rather than falling back to the default. These are
the same names the [command line](cli.md)'s `--style` flag offers.

## The customization API

A [`Style`][gmat_czml.Style] is four element styles. Override any of them; an unset field keeps its
`sat-default` value:

```python
from gmat_czml import Style, PointStyle, LabelStyle, PathStyle, TrackStyle, to_czml

style = Style(
    marker=PointStyle(color=(0, 200, 255, 255), pixel_size=12.0),
    label=LabelStyle(color=(255, 255, 255, 255), font="13pt Helvetica"),
    path=PathStyle(color=(0, 200, 255, 255), width=3.0),
    track=TrackStyle(color=(255, 0, 128, 255), width=4.0),
)
to_czml(trajectory, style=style, ground_track=True).save("orbit.czml")
```

| Element | Style | Fields |
|---------|-------|--------|
| Marker — point | [`PointStyle`][gmat_czml.PointStyle] | `color`, `pixel_size`, `outline_color`, `outline_width` |
| Marker — billboard | [`ImageBillboard`][gmat_czml.ImageBillboard] | `image`, `scale` |
| Label | [`LabelStyle`][gmat_czml.LabelStyle] | `color`, `font` |
| Orbit path | [`PathStyle`][gmat_czml.PathStyle] | `color`, `width` |
| Ground track | [`TrackStyle`][gmat_czml.TrackStyle] | `color`, `width` |

Colours are RGBA tuples with channels in 0–255.

## Image-billboard glyphs

The marker is a coloured point by default, but it can be an **image billboard** instead — a
screen-facing image. Set the style's `marker` to an [`ImageBillboard`][gmat_czml.ImageBillboard]
with any image URI a Cesium client can load (an `http(s)` URL, or a self-contained `data:` URI):

```python
from gmat_czml import Style, ImageBillboard, to_czml

style = Style(marker=ImageBillboard(image="https://example.com/satellite.png", scale=1.5))
to_czml(trajectory, style=style).save("orbit.czml")
```

The billboard replaces the coloured point. gmat-czml ships no asset pipeline, so the caller supplies
the image.

## Annotation layers

The maneuver, contact, and attitude annotations are separate layers, each with its own default look
— orange burns, cyan ground links and observers, a translucent-cyan attitude box — and its own style
field on `Style`:

| Layer | Style | Fields |
|-------|-------|--------|
| Maneuvers | [`ManeuverStyle`][gmat_czml.ManeuverStyle] | `marker` ([`PointStyle`][gmat_czml.PointStyle]), `label` ([`LabelStyle`][gmat_czml.LabelStyle]), `arc` ([`LineStyle`][gmat_czml.LineStyle]) |
| Contacts | [`ContactStyle`][gmat_czml.ContactStyle] | `observer` ([`PointStyle`][gmat_czml.PointStyle]), `label` ([`LabelStyle`][gmat_czml.LabelStyle]), `link` ([`LineStyle`][gmat_czml.LineStyle]) |
| Attitude | [`AttitudeStyle`][gmat_czml.AttitudeStyle] | `box_fill_color`, `box_outline_color`, `box_outline_width` |

```python
from gmat_czml import Style, ManeuverStyle, ContactStyle, PointStyle, LineStyle, to_czml

style = Style(
    maneuver=ManeuverStyle(
        marker=PointStyle(color=(200, 0, 0, 255)),
        arc=LineStyle(color=(200, 0, 0, 255), width=5.0),
    ),
    contact=ContactStyle(link=LineStyle(color=(0, 180, 0, 255), width=2.0)),
)
to_czml(trajectory, style=style, maneuvers=maneuvers).save("orbit.czml")
```

[`LineStyle`][gmat_czml.LineStyle] (`color`, `width`) is the generic line style the burn arc and the
line of sight reuse. The palette presets recolour only the satellite layer; the annotation layers
keep their semantic defaults unless you override them.
