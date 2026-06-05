# Contacts

Access intervals rendered as a ground station and a line of sight: each observer is placed on the
globe, and a link to the satellite is drawn only while the station can see it.

```python
from gmat_czml import to_czml, GroundStation, Contact

madrid = GroundStation(name="Madrid", latitude=40.43, longitude=-4.25, height=0.72)
contact = Contact(observer=madrid, target="GmatLeo", windows=windows)

to_czml(trajectory, contacts=[contact], ground_track=True).save("orbit.czml")
```

`windows` is the access intervals — a list of `(start, end)` `datetime` pairs — that a producer (an
access/contact tool such as a GMAT `ContactLocator`) computed for that station and satellite. The
contact record is gmat-czml's own type: orbit-formats has no canonical access type yet, so the
station placement and the windows are supplied directly.

## What the converter does

**The observer** becomes its own entity, placed at its geodetic position — a static
`cartographicDegrees` `[lon, lat, height]` (longitude east-positive, height in metres, scaled from
the record's kilometres) — with a point glyph and a name label. The placement is the only thing read
off the station; it is not a general ground-station model.

**The line of sight** is a polyline whose two endpoints *reference* the observer's and the
satellite's `position` properties (CZML `references`), so a Cesium client draws the line between the
two live entities without gmat-czml resampling either — the link tracks the satellite as it moves.
It is a straight line of sight (`arcType` `NONE`, not draped on the globe) shown **only during the
access windows**: its `availability` is the set of windows, one CZML interval each. A contact with no
windows still places its observer but emits no link.

Times are UTC: a naive `datetime` is read as UTC, an aware one is converted.

## Targets and observers

A `Contact`'s `target` is the satellite's entity id — its declared object name, or its
`object-<index>` positional fallback — and must match one of the rendered objects; a contact aimed at
an object not in the document raises `UnknownContactTargetError`. Contacts therefore compose with a
multi-object scene: each names which craft it tracks, so several stations and satellites coexist in
one document.

A `GroundStation`'s equality is structural, so the **same** station may appear in several `Contact`
records — one per satellite it tracks — and is still placed once. Two *differently*-placed stations
sharing a name, an observer name that collides with a rendered object's id, or two contacts sharing
the same observer and target all raise `ContactEntityCollisionError` rather than silently merging into
one Cesium entity.

## Packets

Each distinct observer is one packet, its id the station name, emitted in first-seen order. Each
contact that has at least one window adds a link packet, id `<observer>-to-<target>`, in contact
order. The observers come first, then the links.

## Styling

The contact layer defaults to cyan — a cyan observer point and line of sight — so it reads as its own
layer, distinct from the satellite's orbit trail. Recolour it with the
[`ContactStyle`][gmat_czml.ContactStyle] on the [`Style`][gmat_czml.Style]'s `contact` field — its
`observer` ([`PointStyle`][gmat_czml.PointStyle]), `label` ([`LabelStyle`][gmat_czml.LabelStyle]), and
`link` ([`LineStyle`][gmat_czml.LineStyle]); see [Styling](../styling.md#annotation-layers).

## From a gmat-run mission

A GMAT `ContactLocator` report names each observer and its access windows but **not** the observer's
position — that lives on the `GroundStation` resource in the mission script. The
[gmat-run adapter](gmat-run-adapter.md) maps a run's contact reports to these records when you supply
each observer's placement, so a whole mission's accesses convert in one call.
