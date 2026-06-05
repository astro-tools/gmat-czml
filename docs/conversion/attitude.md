# Attitude

A spacecraft attitude history rendered as an animated `orientation`: the object's body axes turn over
the trajectory, shown as a small body box.

```python
from gmat_czml import to_czml
from orbit_formats import read

attitude = read("spacecraft.aem")  # a CCSDS-AEM quaternion history
to_czml(trajectory, attitude=attitude).save("orbit.czml")
```

`attitude` is an orbit-formats `Attitude` — a CCSDS-AEM quaternion history, naming the two reference
frames the rotation maps between (an external reference such as `EME2000`, and the spacecraft body
frame) and a quaternion per epoch.

## What the converter does

The attitude becomes a sampled `orientation` on a child entity, `<object>/attitude`, that references
the object's position and carries a body box. As the playhead moves, the box turns to the spacecraft's
orientation at that time, so the body frame is visible against the orbit.

The orientation is sampled epoch-relative — one reference epoch plus a per-sample offset — with a
`LINEAR` interpolation hint, so a Cesium client interpolates smoothly between attitudes. The body box
has three distinct dimensions, so which way the body points reads unambiguously.

## The reference frame

This is the part that needs care. A CZML `orientation` is always interpreted as the rotation from the
**body** axes to the **Earth-fixed (ECEF)** axes — unlike a position, it has no reference-frame field
to declare an inertial frame. An AEM attitude, though, is usually expressed against an **inertial**
reference (for example `EME2000 → SC_BODY`).

So gmat-czml composes the attitude into the body→ECEF convention: it combines the body↔reference
rotation from the AEM with the reference→Earth-fixed rotation at each epoch (the same Earth-orientation
rotation the [ground track](ground-track.md) uses). An inertial-referenced attitude therefore renders
correctly — the body box tracks the spacecraft's real orientation, not one drifting with the Earth's
rotation. An attitude already expressed in an Earth-fixed frame passes straight through.

The rotation direction comes from the AEM's `ATTITUDE_DIR` tag (`A2B` / `B2A`), defaulting to `A2B`
when a file omits it. The quaternion components are read scalar-last (`Q1 Q2 Q3 QC`), matching CZML's
`[X, Y, Z, W]` order directly.

The attitude epochs carry their own time scale (the AEM's `TIME_SYSTEM`), converted to UTC for the
document timeline; the orientation is available over the attitude history's span.

## One object at a time

An attitude orients one spacecraft, so it attaches to the single rendered trajectory. Passing
`attitude` for a multi-object document raises `AmbiguousAttitudeTargetError` — which craft the
attitude belongs to cannot be told from the record. Only the quaternion representation is rendered; an
Euler-angle or spin attitude raises `UnsupportedAttitudeTypeError`. An attitude whose two frames do
not resolve to one recognised external reference plus one body frame raises `AttitudeFrameError`.

## Packets

The attitude is one packet, `<object>/attitude`. It references the object's position
(`<object>#position`) and carries the sampled `orientation` and the body box.

## Styling

The body box defaults to translucent cyan. Recolour its fill and outline with the
[`AttitudeStyle`][gmat_czml.AttitudeStyle] on the [`Style`][gmat_czml.Style]'s `attitude` field; see
[Styling](../styling.md#annotation-layers). The box's dimensions are fixed by the converter; a
glTF-model hook waits on an asset pipeline.
