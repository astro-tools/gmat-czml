# gmat-czml

Convert GMAT — and any canonical-schema — trajectories to **CZML** for browser-based 3D Cesium
visualization.

gmat-czml takes an already-computed trajectory in the canonical state-series form and turns it
into a CZML document any Cesium client (CesiumJS, Cesium ion, Resium) can animate. It does not
propagate or compute orbits; the producer is the source of geometric truth.

!!! note "Under construction"
    gmat-czml is in early development. This site grows as the v0.1 surface lands. The input
    contract and the design decisions are recorded in [Design → Decisions](design/decisions.md).

## What it is not

- **Not** a propagation or astrodynamics library — it converts a trajectory, it does not compute
  one.
- **Not** a CZML renderer — it produces CZML; Cesium renders it.
- **Not** a format parser — reading trajectory files is delegated to the org's format-I/O library.

## Installation

```bash
pip install gmat-czml
```

gmat-czml requires Python 3.10, 3.11, or 3.12.
