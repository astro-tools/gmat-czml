# gmat-czml

[![CI](https://github.com/astro-tools/gmat-czml/actions/workflows/ci.yml/badge.svg)](https://github.com/astro-tools/gmat-czml/actions/workflows/ci.yml)
[![Docs](https://github.com/astro-tools/gmat-czml/actions/workflows/docs.yml/badge.svg)](https://astro-tools.github.io/gmat-czml/)
[![PyPI](https://img.shields.io/pypi/v/gmat-czml.svg)](https://pypi.org/project/gmat-czml/)
[![Python versions](https://img.shields.io/pypi/pyversions/gmat-czml.svg)](https://pypi.org/project/gmat-czml/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Convert GMAT (and any canonical-schema) trajectories to CZML for browser-based 3D Cesium
visualization.

## What this is

gmat-czml takes an already-computed trajectory — a state history in the canonical state-series
form — and turns it into a [CZML](https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Structure)
document a Cesium client can animate: an orbit path, a ground track, a point and a label, on a
clock synthesized from the trajectory's own time span. Optional layers add **ground-station
contacts** (an observer and a line of sight shown only during each access window), **maneuvers**
(impulsive and finite burns marked on the orbit), and an animated **attitude** (the body axes
turning over the pass) — each restyleable through a small preset + customization API. The input is
not GMAT-specific — any producer that yields the canonical schema (a TLE propagation, a transfer, a
read ephemeris) works through one call.

It does not propagate, integrate, or solve orbits, and it does not render: the producer is the
source of geometric truth, and Cesium is the renderer. gmat-czml is the bridge between them.

## Quick start

```python
from gmat_czml import to_czml

czml = to_czml(trajectory, ground_track=True)
czml.save("orbit.czml")          # load in any Cesium viewer
# czml.to_json() / czml.to_dict()  # in-memory, no file needed
```

`trajectory` is a canonical state-series `DataFrame`, an orbit-formats `Ephemeris`, a file
orbit-formats can read (OEM, GMAT report, SP3, STK ephemeris, …), or an iterable of these for a
multi-object scene. See the [gallery](https://astro-tools.github.io/gmat-czml/gallery/) for
runnable examples.

## Annotations and styling

The same call layers on the optional v0.2 entities and a visual style:

```python
from gmat_czml import to_czml, preset

to_czml(
    trajectory,
    ground_track=True,        # the sub-satellite ground track (Earth-only)
    contacts=contacts,        # ground stations + a line of sight per access window
    maneuvers=maneuvers,      # impulsive / finite burns marked on the orbit
    attitude=attitude,        # an animated body-axes orientation
    style=preset("sat-red"),  # a named preset, or a full Style(...) of colours / widths / glyphs
    playback_seconds=120.0,   # the whole span plays back in ~this many wall-clock seconds
).save("mission.czml")
```

`contacts` are gmat-czml [`Contact`](https://astro-tools.github.io/gmat-czml/conversion/contacts/) /
`GroundStation` records; `maneuvers` and `attitude` are the orbit-formats `Maneuver` / `Attitude`
records a CCSDS OPM / OCM / AEM reads. `style` is a named [preset](https://astro-tools.github.io/gmat-czml/styling/)
or a `Style` of colour / width / glyph overrides. A gmat-run mission converts in one hop through the
[`gmat_czml.adapters.gmat_run`](https://astro-tools.github.io/gmat-czml/conversion/gmat-run-adapter/)
adapter.

## The canonical input

A trajectory is one row per sample with the columns and `DataFrame.attrs` metadata below — the
shape orbit-formats emits and a headless GMAT run produces, so it flows in with no reshaping.

| Columns | `Epoch` (datetime), `X` `Y` `Z` (required); `VX` `VY` `VZ` (optional) |
|---------|----------------------------------------------------------------------|
| Metadata | `object_name`, `central_body`, `coordinate_system`, `time_scale` (required), `units`, `interpolation`, `interpolation_degree` |

The reference frame and time scale are required, never guessed; everything else has a sensible
default. A malformed input raises a typed error naming exactly what is wrong. Full contract: the
[schema reference](https://astro-tools.github.io/gmat-czml/schema/).

## Supported Cesium clients

The output is a standard CZML document — any Cesium client renders it:

| Client | How |
|--------|-----|
| [CesiumJS](https://cesium.com/platform/cesiumjs/) | `Cesium.CzmlDataSource.load(czml)` in the core library |
| [Cesium ion](https://cesium.com/platform/cesium-ion/) | stream/host assets and imagery; `upload_to_ion()` pushes a document as a hosted asset (the `[ion]` extra) |
| [Resium](https://resium.reearth.io/) | the CesiumJS components for React |
| Bundled viewer | `gmat-czml serve` / `to_czml(...).serve()` hosts a document behind an embedded CesiumJS viewer (the `[server]` extra) |

No setup beyond a Cesium viewer is needed; for a zero-install look, drop a `.czml` onto
[Cesium Sandcastle](https://sandcastle.cesium.com/).

## Serving and sharing

Two optional extras take a document the last step — to a browser, or to the cloud.

**Server mode** (`pip install gmat-czml[server]`) hosts a document over http behind an embedded
CesiumJS viewer and opens it for you — the one-click local look, no file written:

```python
to_czml(trajectory, ground_track=True).serve()      # opens http://127.0.0.1:8080/
```

`gmat-czml serve mission.oem` is the CLI equivalent. Full detail in the
[server-mode docs](https://astro-tools.github.io/gmat-czml/server/).

**Cesium ion upload** (`pip install gmat-czml[ion]`) pushes a document to
[Cesium ion](https://cesium.com/platform/cesium-ion/) as a hosted asset a client loads by id — token
passthrough, so you supply the ion access token and gmat-czml forwards it and nothing more:

```python
asset = to_czml(trajectory).upload_to_ion(token, name="Mission LEO")
print(asset.dashboard_url)
```

`gmat-czml upload mission.oem --name "Mission LEO"` is the CLI equivalent. Full detail in the
[ion-upload docs](https://astro-tools.github.io/gmat-czml/ion/).

## What this is not

- **Not** a propagation or astrodynamics library — it converts a trajectory, never computes one.
- **Not** a CZML renderer — it produces CZML; [Cesium](https://cesium.com/) renders it.
- **Not** a format parser — reading trajectory files is delegated to the org's format-I/O library.
- **Not** a hosted service — viewing happens in your own Cesium client.

## Installation

```bash
pip install gmat-czml
```

gmat-czml requires Python 3.10, 3.11, or 3.12.

## Documentation

Full docs — getting started, the schema, per-entity conversion, the CLI, server mode, ion upload,
the gallery, and the API reference — at **<https://astro-tools.github.io/gmat-czml/>**. The design
rationale lives in the [design decisions](docs/design/decisions.md).

## Development

```bash
git clone https://github.com/astro-tools/gmat-czml.git
cd gmat-czml
uv sync --all-groups
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch / PR / test workflow.

## Licence

MIT. See [LICENSE](LICENSE).
