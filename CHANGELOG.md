# Changelog

All notable changes to gmat-czml are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are aggregated at release-cut
time, not per pull request.

## [Unreleased]

## [0.3.0] - 2026-06-05

The sharing release. v0.1 produced the document and v0.2 annotated it; v0.3 takes that document the
last step — to a browser or to the cloud — through two optional, dependency-isolated extras, and
catches the docs and gallery up to the full surface. The conversion contract is untouched: both
extras are leaf modules imported only on demand, so a plain `pip install gmat-czml` pulls neither,
and `to_czml`'s output is unchanged.

### Added

- **Server mode** (the `[server]` extra). `CzmlDocument.serve()` and a `gmat-czml serve` subcommand
  host a document over http behind an embedded CesiumJS viewer and open it — the one-click local
  look, no file written. server.py is a leaf module imported only on demand, so a base install pulls
  neither fastapi nor uvicorn, and `.serve()` without the extra raises an `ImportError` with an
  actionable install hint. The packaged viewer loads CesiumJS from a CDN, defaults to token-less
  offline imagery, and parses in two stages so the headless check needs no WebGL.
- **Cesium ion upload** (the `[ion]` extra). `CzmlDocument.upload_to_ion(token, name=...)` and a
  `gmat-czml upload` subcommand push a document to Cesium ion as a hosted asset a client loads by id.
  The token is forwarded as a bearer credential and nothing more; the four-step REST upload (create,
  S3 put, complete, poll) needs boto3 only for the signed put, so boto3 is the single dependency
  behind the extra. An ion-side failure — a bad token, an errored asset, a timed-out wait — raises a
  typed `IonUploadError`; a missing token fails fast before any network call.
- **Documentation.** New server-mode and ion-upload guide pages (the extras, the `serve()` /
  `upload_to_ion()` calls, the CLI verbs and options), the CLI page covering all three subcommands,
  the `IonAsset` return type in the API reference, and a refreshed supported-Cesium-client matrix. A
  lunar-transfer gallery example — a GMAT-targeted four-segment translunar CCSDS-OEM converted through
  the same one call, with an animated GIF of the eight-day voyage — exercises the ~400,000 km scale.

## [0.2.0] - 2026-06-04

The annotation release. v0.1 turned a trajectory into an orbit path, a ground track, and a clock;
v0.2 layers on the things that make it read as a mission — ground-station contacts, maneuvers, and
an animated attitude — each restyleable through a small preset + customization API, plus an
optional viewer-side imagery underlay and a one-hop gmat-run adapter. The conversion contract is
unchanged: the producer stays the source of geometric truth and Cesium the renderer, the canonical
input boundary is the same, and an unflagged `to_czml(trajectory)` emits byte-for-byte the v0.1
document.

### Added

- **Ground-station contacts** (`contacts=`). A producer's access windows become an observer entity
  per ground station at its geodetic position and a per-window line of sight — a polyline that
  references the observer's and target's `position` properties and is visible only during each
  access window. gmat-czml owns the `Contact` / `GroundStation` records (orbit-formats has no
  canonical access type yet); collisions and dangling targets raise `UnknownContactTargetError` /
  `ContactEntityCollisionError`.
- **Maneuvers** (`maneuvers=`). An orbit-formats `Maneuver` becomes a marker on the orbit —
  an impulsive burn a point + label pinned at the burn epoch, a finite burn an arc over the burn
  span plus a companion marker. The position is interpolated from the trajectory itself, in metres
  and tagged with the orbit's frame, so it lands on the rendered path. Burns attach to the single
  rendered object: `AmbiguousManeuverTargetError` / `ManeuverOutsideTrajectoryError` guard the rest.
- **Attitude** (`attitude=`). A CCSDS-AEM quaternion history becomes a sampled CZML `orientation`
  on a child packet carrying a schematic body box, so the object's axes animate over the pass. A
  CZML `orientation` is always read body→Earth-fixed, so an inertial-referenced attitude is composed
  through a per-epoch reference→ECEF rotation (delegated to orbit-formats); a fixed-frame source is a
  pure quaternion passthrough. `AmbiguousAttitudeTargetError` / `UnsupportedAttitudeTypeError` /
  `AttitudeFrameError` guard the inputs.
- **Style presets + customization API.** The placeholder `Style` grows into a typed model —
  `PointStyle` / `ImageBillboard`, `LabelStyle`, `PathStyle`, `TrackStyle`, and per-layer
  `ManeuverStyle` / `ContactStyle` / `AttitudeStyle` / `LineStyle` — resolved by name through
  `preset()` (`sat-default` plus a `sat-red` / `sat-green` / `sat-magenta` palette; an unknown name
  raises `UnknownStyleError`). The satellite marker can be an image billboard, and the CLI `--style`
  offers the preset set. Every default is byte-for-byte the v0.1 baked-in look.
- **Ground-track tile underlay** (viewer-side, opt-in). The bundled example viewer gains a base-
  imagery selector (offline / OpenStreetMap / Cesium ion / Mapbox, with a token-less fallback) and a
  clamp-to-ground option that drapes the ground-track polylines onto the globe. CZML carries no base
  imagery, so this is viewer configuration only — `to_czml`'s output is unchanged.
- **gmat-run adapter** (`gmat_czml.adapters.gmat_run`). A lazily-imported bridge that turns a
  gmat-run `Results` into a CZML document in one hop — `results_to_trajectories`,
  `results_to_contacts`, and `to_czml_from_results` — without making gmat-run a runtime dependency
  (it stays in the dev group). Adapter-specific failures raise `MissingStationError` /
  `UnsupportedContactFormatError`.
- **Documentation.** New per-entity conversion pages for contacts and the gmat-run adapter, a
  rewritten styling guide covering the satellite and annotation layers, and an example gallery
  extended with computed overhead passes, impulsive + finite maneuvers, and an animated attitude
  GIF.

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
