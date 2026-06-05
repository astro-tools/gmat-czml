# gmat-czml

Convert GMAT — and any canonical-schema — trajectories to **CZML** for browser-based 3D Cesium
visualization.

![A GMAT LEO ephemeris animated in Cesium with its ground track](assets/gallery/leo-ground-track.gif){ width="640" }

gmat-czml takes an **already-computed** trajectory — a state history in the canonical state-series
form — and turns it into a [CZML](https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Structure)
document a [Cesium](https://cesium.com/) client can animate: an orbit path, a ground track, a point
and a label, on a clock synthesized from the trajectory's own time span. The input is not
GMAT-specific — any producer that yields the canonical schema (a TLE propagation, a transfer, a
read ephemeris) renders through one call.

```python
from gmat_czml import to_czml

czml = to_czml(trajectory, ground_track=True)
czml.save("orbit.czml")        # load in any Cesium viewer
```

It does not propagate, integrate, or solve orbits, and it does not render: the producer is the
source of geometric truth, and Cesium is the renderer. gmat-czml is the bridge between them.

## Where to go next

- **[Getting started](getting-started.md)** — install, the one call, and how to view the result.
- **[Canonical input schema](schema.md)** — the state-series contract every producer feeds.
- **[Orbit path](conversion/orbit-path.md)** and **[ground track](conversion/ground-track.md)** —
  what each entity becomes in CZML.
- **[Maneuvers](conversion/maneuvers.md)**, **[attitude](conversion/attitude.md)**, and
  **[contacts](conversion/contacts.md)** — the annotation layers, with **[styling](styling.md)** over
  all of them.
- **[Command line](cli.md)** — the `gmat-czml convert` subcommand.
- **[Gallery](gallery.md)** — runnable examples with rendered output.
- **[API reference](api.md)** — the full public surface.

## What it is not

- **Not** a propagation or astrodynamics library — it converts a trajectory, it does not compute
  one.
- **Not** a CZML renderer — it produces CZML; Cesium renders it.
- **Not** a format parser — reading trajectory files is delegated to the org's format-I/O library.
- **Not** a hosted service — viewing happens in your own Cesium client.

## Installation

```bash
pip install gmat-czml
```

gmat-czml requires Python 3.10, 3.11, or 3.12.
