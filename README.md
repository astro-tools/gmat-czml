# gmat-czml

[![CI](https://github.com/astro-tools/gmat-czml/actions/workflows/ci.yml/badge.svg)](https://github.com/astro-tools/gmat-czml/actions/workflows/ci.yml)
[![Docs](https://github.com/astro-tools/gmat-czml/actions/workflows/docs.yml/badge.svg)](https://astro-tools.github.io/gmat-czml/)
[![PyPI](https://img.shields.io/pypi/v/gmat-czml.svg)](https://pypi.org/project/gmat-czml/)
[![Python versions](https://img.shields.io/pypi/pyversions/gmat-czml.svg)](https://pypi.org/project/gmat-czml/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Convert GMAT (and any canonical-schema) trajectories to CZML for browser-based 3D Cesium
visualization.

> **Status:** early development. The package skeleton, tooling, CI, and docs are in place; the
> conversion surface (canonical schema, state ephemeris to an orbit path, ground track, the
> `convert` CLI) is landing for v0.1. See the [design decisions](docs/design/decisions.md) for the
> input contract.

## What this is

gmat-czml takes an already-computed trajectory — a state history in the canonical state-series
form — and turns it into a [CZML](https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Structure)
document a Cesium client can animate: an orbit path, a ground track, a billboard and label, on a
clock synthesized from the trajectory's own time span. The input is not GMAT-specific — any
producer that yields the canonical schema (a TLE propagation, a transfer, a read ephemeris) works
through one call.

It does not propagate, integrate, or solve orbits, and it does not render: the producer is the
source of geometric truth, and Cesium is the renderer. gmat-czml is the bridge between them.

## Quick start

```python
from gmat_czml import to_czml

czml = to_czml(ephemeris, style="sat-default")
czml.save("orbit.czml")        # → load in any Cesium viewer
# czml.to_json() / czml.to_dict()  # in-memory, no file needed
```

_(The conversion surface is under construction; the API above is the v0.1 target.)_

## What this is not

- **Not** a propagation or astrodynamics library — it converts a trajectory, never computes one.
- **Not** a CZML renderer — it produces CZML; [Cesium](https://cesium.com/) renders it.
- **Not** a format parser — reading trajectory files is delegated to the org's format-I/O library.
- **Not** a hosted service — the (later) bundled viewer is a local convenience, not a SaaS.

## Installation

```bash
pip install gmat-czml
```

gmat-czml requires Python 3.10, 3.11, or 3.12.

## Documentation

Full docs at **<https://astro-tools.github.io/gmat-czml/>**.

## Development

```bash
git clone https://github.com/astro-tools/gmat-czml.git
cd gmat-czml
uv sync --all-groups
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch / PR / test workflow.

## Licence

MIT. See [LICENSE](LICENSE).
