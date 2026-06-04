# Orbit path

The core conversion: one validated trajectory becomes the CZML properties an entity packet
carries — a sampled **position**, a **path**, a **marker** (a point or an image billboard), and a
**label** — on a packet that also holds the object's identity and UTC availability.

![A geostationary orbit rendered in Cesium](../assets/gallery/geo.png){ width="520" }

```python
from gmat_czml import to_czml

to_czml(trajectory).save("orbit.czml")
```

## What the converter does

**Metres, not kilometres.** CZML cartesian positions are metric; the canonical default is
kilometres. Every position is scaled to metres by the declared `units.length` (`km` or `m`). The
declared unit is authoritative — there is no unit guessing — and an unsupported unit is rejected.

**Interpolation passthrough.** The source's `interpolation` and `interpolation_degree` are carried
onto the CZML position as `interpolationAlgorithm` and `interpolationDegree`, so the client
reproduces the curve between sparse samples instead of chording straight lines. Source names map to
the CZML enum (`LAGRANGE`, `HERMITE`, `LINEAR`), case-insensitively. When the source declares no
interpolation, the orbit path defaults to **Lagrange degree 5**; an *unrecognised* algorithm is
rejected rather than guessed.

**Compact, decimated samples.** Epochs travel as a single reference epoch plus per-sample second
offsets, so the document carries one absolute timestamp rather than one per sample. The path is then
**tolerance-bounded-decimated**: an iterative cross-track Douglas–Peucker pass drops samples that
stay within ~1 km of the kept polyline, keeping the document small while preserving the geometry. A
`degree + 1` floor guarantees enough support for the declared interpolation curve.

**The reference frame** is taken from the recognised frame id — inertial frames render in CZML
`INERTIAL`, Earth-fixed in `FIXED` (see the [schema reference](../schema.md#recognised-reference-frames)).

## The properties

| Property | What it is |
|----------|------------|
| `position` | the sampled cartesian (metres), tagged with the interpolation hint and the reference frame |
| `path` | the orbit trail — a lead time of 0 and a trail spanning the whole trajectory by default |
| `point` / `billboard` | the object's marker glyph — a coloured dot by default, or an image billboard |
| `label` | the object's name, offset clear of the marker |

A multi-segment ephemeris is concatenated into one chronological sample series, so it renders as a
single position property spanning the whole span. Multiple objects are handled one packet each — see
[the schema's multi-object note](../schema.md#multiple-objects).

## Styling

The marker, label, and orbit path are driven by the supplied [`Style`][gmat_czml.Style] — its
colour, width, pixel size, font, and glyph (a coloured point or an image billboard). The default is
`sat-default`; named presets and the customization API are covered in [Styling](../styling.md).
