# Maneuvers

Burns rendered as markers on the orbit: an impulsive maneuver as a point pinned where it happens, a
finite maneuver as a highlighted arc over the span it fires.

```python
from gmat_czml import to_czml

to_czml(trajectory, maneuvers=maneuvers).save("orbit.czml")
```

`maneuvers` is an iterable of orbit-formats `Maneuver` records — the burns read from a CCSDS OPM or
OCM. Each carries an ignition epoch, a duration (`0` for an impulsive burn), and an optional Δv.

## What the converter does

**An impulsive maneuver** (zero duration) becomes a single marker: a point and a label placed on
the orbit at the burn epoch. Its `availability` runs from that epoch to the end of the document, so
it appears as the playhead reaches the burn and then stays — a record of where the impulse happened.
The label states the Δv magnitude, e.g. `Δv 0.012 km/s`.

**A finite maneuver** (non-zero duration) becomes two entities: an arc tracing the orbit between
ignition and cut-off, and a point + label marker at the ignition point. Both are shown only over the
burn span, so the highlighted segment and its label are present exactly while the burn fires. The
label states the Δv magnitude and the duration, e.g. `Δv 0.006 km/s over 120 s`.

Maneuvers are drawn in orange, so they read as their own layer against the orbit trail.

## Where the marker sits

A `Maneuver` names the burn's epoch but not its position, so the marker location is interpolated from
the trajectory itself — the same trajectory the orbit path is drawn from. The marker therefore lands
on the rendered orbit, in the trajectory's own reference frame.

The maneuver epoch carries no time scale of its own, so it is read in the trajectory's declared
scale (one mission, one time system); the burn span is then carried onto the document's UTC timeline
as the marker's availability.

## One object at a time

A maneuver names no target craft, so its marker attaches to the single rendered trajectory. Passing
`maneuvers` for a multi-object document raises `AmbiguousManeuverTargetError` — which burn acts on
which craft cannot be told from the record. A burn whose epoch (or, for a finite burn, whose
cut-off) falls outside the trajectory's time span raises `ManeuverOutsideTrajectoryError`: there is
no orbit beneath it to pin to, so it is rejected rather than clamped.

## Packets

An impulsive maneuver is one packet, `<object>/maneuver/<k>`. A finite maneuver is its arc,
`<object>/maneuver/<k>`, followed by its companion marker, `<object>/maneuver/<k>/marker`. The index
`k` numbers the maneuvers in the order given.

## Styling

Maneuvers use a single baked-in maneuver style. Customization arrives with the
[style system](../styling.md).
