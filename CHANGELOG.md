# Changelog

All notable changes to gmat-czml are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are aggregated at release-cut
time, not per pull request.

## [Unreleased]

## [0.1.0] - 2026-06-04

First release. gmat-czml takes an already-computed trajectory — a state history in the canonical
state-series form produced by a headless GMAT run or read by the org's format-I/O library — and
turns it into a CZML document a Cesium client can animate. It does not propagate, integrate, or
render: the producer is the source of geometric truth, and Cesium is the renderer.

### Added

- **`to_czml`, the single entry point**, and the `CzmlDocument` it returns. The call accepts a
  canonical state-series `DataFrame`, an orbit-formats `Ephemeris`, a file orbit-formats can read
  (OEM, GMAT report, SP3, STK ephemeris, …), or an iterable of any of these for a multi-object
  scene. The document saves to a `.czml` file (`save`) or comes back in memory (`to_json` /
  `to_dict`) — no file needed.
- **The canonical input boundary.** One row per sample (`Epoch`, `X` `Y` `Z` required;
  `VX` `VY` `VZ` optional) plus `DataFrame.attrs` metadata, with the reference frame and time
  scale required and never guessed. A malformed input raises a typed `GmatCzmlError` subclass that
  names exactly what is wrong, rather than failing deep in assembly.
- **Orbit path.** Each object becomes a Cesium entity carrying four properties — a sampled
  `position` in metres, a `path`, a `point`, and a `label`. The source's interpolation method and
  degree pass through to the CZML `interpolationAlgorithm` / `interpolationDegree`
  (`LAGRANGE` / `HERMITE` / `LINEAR`, defaulting to Lagrange degree 5), and the recognised frame
  maps to CZML `INERTIAL` or `FIXED`.
- **Tolerance-bounded decimation.** A cross-track Douglas–Peucker pass drops samples that stay
  within tolerance of the kept polyline — a `degree + 1` support floor preserves the interpolation
  curve — so a dense, high-rate ephemeris ships a compact document without visible path error.
  Epochs travel as one reference epoch plus per-sample second offsets.
- **Ground track** (opt-in via `ground_track=True`). The sub-satellite point becomes a geodetic
  polyline that floats at the satellite's own height over the correct ground position, with
  antimeridian crossings split at an interpolated seam on the dateline. The inertial → Earth-fixed
  rotation and the WGS84 geodetic projection are delegated to orbit-formats — Earth-only, and a
  trajectory declared about another central body is rejected rather than mis-projected.
- **Clock synthesis.** A document clock is synthesized from the trajectory's own epoch span, with
  the declared time scale converted to the UTC Cesium expects.
- **Multi-object / multi-segment scenes.** An iterable of trajectories becomes one document, one
  entity per object, on a single shared clock.
- **Styling.** A single baked-in `sat-default` style covers every object's point, label, path, and
  ground track; the `Style` handle is the stable seam later customization plugs into.
- **`gmat-czml convert` CLI.** A thin driver over `to_czml` — `convert INPUT -o OUTPUT` with
  `--ground-track`, `--playback-seconds`, and `--style` — whose output is byte-for-byte the
  document the API produces.
- **Documentation.** A published docs site — getting started, the schema reference, per-entity
  conversion, styling, the CLI, an example gallery with rendered output, and the API reference —
  with the design rationale recorded under `docs/design/`.
