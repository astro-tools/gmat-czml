# Design decisions

The running decision log for gmat-czml — the choices that shape the public surface and the
conversion internals, recorded with their rationale so the implementation has one contract to
build against. New decisions append to this file.

## The input contract

gmat-czml converts an already-computed trajectory into CZML; it does not propagate, integrate,
or solve orbits of its own. The unit of input is the **canonical state-series DataFrame** — the
same shape the org's format-I/O library (orbit-formats) emits from `Ephemeris.to_dataframe()`,
and the same shape a headless GMAT run already produces — so a trajectory flows in with zero
reshaping.

### Columns

| Column | Meaning | dtype | Required |
|--------|---------|-------|:--------:|
| `Epoch` | sample time | `datetime64[ns]` | yes |
| `X`, `Y`, `Z` | position components | `float64` | yes |
| `VX`, `VY`, `VZ` | velocity components | `float64` | no |

### `DataFrame.attrs`

| Key | Meaning | Used for |
|-----|---------|----------|
| `object_name` | object identity | label / billboard name |
| `central_body` | central body (e.g. `Earth`) | gates the ground track; frame interpretation |
| `coordinate_system` | reference frame | CZML reference-frame mapping |
| `time_scale` | one of `UTC TAI TT TDB GPS UT1` | conversion to UTC |
| `epoch_scales` | `{"Epoch": <time_scale>}` | per-column scale (read as a fallback for `time_scale`) |
| `units` | `{length, speed, angle, time}` (default `km, km/s, deg, s`) | conversion to metres |
| `interpolation` | interpolation algorithm name | CZML interpolation hint |
| `interpolation_degree` | interpolation degree | CZML interpolation hint |

Required: `Epoch, X, Y, Z`. Everything else is read with a sensible default; a missing or
malformed *required* element raises a typed gmat-czml error naming what is wrong, never a bare
`KeyError`.

Besides a DataFrame, `to_czml` also accepts an orbit-formats canonical object (`Ephemeris` /
`StateVector`) and any file orbit-formats can read (an OEM, a GMAT report, an SP3, an STK
ephemeris, …); each is normalised to the contract above before conversion.

---

## D1 — orbit-formats owns the schema; gmat-czml consumes it

gmat-czml depends on **orbit-formats (the org's format-I/O library)** and adopts its canonical
state-series schema verbatim, rather than defining and validating a parallel one.

- The public input is the canonical DataFrame above — the universal entry point, so a trajectory
  from any producer (a TLE propagation via Skyfield, a transfer from hapsira, a GMAT run) works
  through one call.
- Parsing and validation are delegated to orbit-formats' canonical layer
  (`Ephemeris.from_dataframe()` / `parse_state_frame_arrays` / `metadata_from_attrs`); `schema.py`
  is a thin boundary that adds gmat-czml-specific guards (a recognised frame; `Earth` required for
  a ground track) and wraps upstream errors as typed gmat-czml errors.

**Rationale.** The charter scoped gmat-czml to *define* the schema now and *converge* with the
format-I/O library later. With that library available as a dependency, convergence is complete
today: there is one schema, owned upstream, and gmat-czml is a pure consumer. This removes a whole
class of drift between the two and means anything that reads into the canonical form renders
without reshaping.

## D2 — units: read the declared unit, convert to metres

CZML cartesian positions are in metres; the canonical default is kilometres. gmat-czml reads the
declared `units` (via orbit-formats' `UnitSpec` / `units_from_attrs`) and converts position by the
`length` unit and velocity by the `speed` unit. The declared unit is authoritative — there is no
unit guessing — and a meta-test guards against a converter accidentally emitting kilometres.

## D3 — interpolation passthrough

The source's `interpolation` and `interpolation_degree` attributes are carried onto the CZML
position property as `interpolationAlgorithm` and `interpolationDegree`, so the client reproduces
the curve between sparse samples rather than chording straight lines. Source names map to the CZML
enum (`LAGRANGE`, `HERMITE`, `LINEAR`). When the source declares no interpolation, the default for
an orbit path is `LAGRANGE` degree 5 (revisitable when the ephemeris converter lands).

## D4 — reference-frame mapping

Frame names are recognised through orbit-formats' `normalize_frame` (the single, shared alias
table — case- and whitespace-insensitive), so the two libraries agree on what each name means.
The normalised id maps to a CZML reference frame:

- **Inertial** — `EME2000` / `J2000`, `GCRF`, `ICRF`, `TEME` (and GMAT's `EarthMJ2000Eq`) → CZML
  `INERTIAL`. Cesium's inertial frame is ICRF; `EME2000` differs from ICRF by a frame bias of tens
  of milliarcseconds and `TEME` by a small rotation — both far below visualization tolerance, so
  they are **documented, not corrected**.
- **Earth-fixed** — `ITRF` (and GMAT's `EarthFixed`) → CZML `FIXED`.
- An unrecognised frame raises a typed error naming the recognised set, rather than guessing.

## D5 — ground-track rotation delegates to orbit-formats

The sub-satellite ground track needs an inertial → Earth-fixed → geodetic path at each epoch.
gmat-czml delegates this to orbit-formats: `rotate_state(… to ITRF)` (precession / nutation /
Earth-orientation via the upstream's astropy-backed rotation) followed by its
`cartesian_to_geodetic` (WGS84) helper. gmat-czml does **not** carry its own rotation.

**Rationale.** This resolves the charter's open "in-house GMST/IAU vs astropy" question by using
the shipped upstream capability: the accuracy is rigorous for free, and there is no second rotation
implementation to test or keep in sync. The ground track is the only path that needs
Earth-orientation machinery, and the upstream already does it hermetically (no network).

## D6 — dependencies and pins

Core runtime dependencies:

| Dependency | Constraint | Role |
|-----------|-----------|------|
| `czml3` | `>=3.3,<4` | CZML serialization backend (pydantic-2) |
| `orbit-formats` | `>=0.5` | canonical schema, frame rotation, geodetic projection, file readers |
| `pandas` | `>=2.0` | the canonical DataFrame |
| `numpy` | `>=1.24` | sampling / decimation / frame arrays |

The exact versions are locked in `uv.lock`; the golden-output regression suite is the drift
detector for a `czml3` bump (goldens are regenerated deliberately, never silently).

The `orbit-formats` floor is `>=0.5` — the line where the ECEF↔geodetic helper the ground track
delegates to first appears. It was held at `>=0.4` while 0.5 was unreleased (a published library
cannot depend on an unreleased version, nor on a git URL); once 0.5.0 shipped to PyPI the floor
moved to `>=0.5`, ahead of the ground-track work that consumes the helper rather than waiting on
it.

**Install-weight tradeoff (accepted).** Depending on orbit-formats pulls its own dependencies
(including astropy) into the tree, so the base install is heavier than the charter's
"dependency-light" aspiration. This is a deliberate trade for a single shared schema and a single
rigorous frame/geodetic implementation. The cost is contained: orbit-formats imports astropy
**lazily**, only inside the rotation, so the core ephemeris → CZML path imports no astropy and the
in-memory / attachment path's cold-import latency is unaffected — only a ground-track render loads
it.

## D7 — extras, deferred reads, decimation, and file input

- **No optional extras in v0.1.** The bundled FastAPI server is a later release. There is **no
  astropy extra** — astropy arrives transitively via orbit-formats, never as a direct gmat-czml
  dependency.
- **Ground-station coordinate reads are deferred** to the release that adds contact intervals;
  v0.1 reads nothing but the canonical trajectory.
- **Decimation is tolerance-bounded and configurable, on by default**, keeping the document small
  enough to load quickly and to fit an attachment. The provisional ~1 km cross-track geometric
  tolerance and ~5 MB soft payload budget are finalised in D9, where the sampling module lands.
- **`to_czml` and the CLI accept any file orbit-formats can read** (via its `read()`), so file
  input comes for free and gmat-czml ships no format readers of its own.

## D8 — the validation boundary: `validate` / `CanonicalInput` / `normalize_inputs`

`schema.py` is a thin boundary over the upstream `Ephemeris.from_dataframe`; it parses nothing
itself, delegating the state arrays and the `attrs` spine to that one entry point (and never
reaching into the semi-private `canonical.base` helpers behind it). On top of that delegation it
adds the guards the renderer needs and the upstream does not enforce, and turns every failure into
a typed `SchemaError`. The contract this settles for the converters:

- **The validated unit of work is `CanonicalInput`** — the parsed upstream `Ephemeris` plus the
  recognised frame id and a `has_velocity` flag. It is what every converter consumes.
- **Velocity is optional.** A position-only frame (no `VX, VY, VZ`) validates; the velocity is
  padded with `NaN` so the upstream parse — which requires all six state columns — runs, and
  `has_velocity` records that none was supplied. A *partial* velocity declaration (some of the
  three but not all) is malformed and rejected.
- **Frame recognition is a gmat-czml-owned superset.** `recognised_frame` defers to orbit-formats'
  shared alias table (`normalize_frame`) and supplements it with GMAT's own `EarthMJ2000Eq` /
  `EarthFixed` spellings — the frames a headless GMAT run tags its states with, which the upstream
  table does not carry. Only those two equatorial frames are added; GMAT's ecliptic / epoch-of-date
  systems are left unrecognised rather than silently mapped to the wrong axes. The downstream frame
  mapping classifies the recognised id as INERTIAL / FIXED.
- **Frame and time scale are required, never guessed.** An absent `coordinate_system` or time scale
  raises (the time scale is read from `time_scale`, falling back to `epoch_scales['Epoch']`),
  consistent with D4's no-guessing rule — both are load-bearing for the CZML reference frame and the
  UTC clock. Unit metadata, when present, is shape-validated; whether a well-formed unit *string* is
  convertible is the ephemeris converter's concern, not the schema's.
- **Multiple objects are an iterable, one trajectory per object.** `normalize_inputs` accepts a
  single canonical `DataFrame`/`Ephemeris` or an iterable of them and returns one `CanonicalInput`
  per object; object identity comes from `attrs['object_name']`, which must be unique across the
  collection (a mapping is not the contract — it is rejected with a pointer to this form).
- **Validation never mutates the caller.** The padded velocity and the resolved time scale live on a
  shallow copy; the producer's DataFrame is left untouched.

## D9 — decimation: cross-track Douglas–Peucker, tolerance hard / budget soft

`sampling.py` decimates a sampled path with an iterative 3D **Douglas–Peucker** pass on the
**cross-track** (perpendicular-to-chord) distance, so every dropped sample stays within a stated
geometric bound of the kept polyline. This finalises D7's provisional knobs:

- **Tolerance is the hard bound** — `DEFAULT_TOLERANCE_KM = 1.0` km, the cross-track distance a
  dropped sample may sit from the kept polyline (≈ visualization tolerance). A sample whose deviation
  would exceed it is never dropped.
- **The payload budget is a soft target** — `DEFAULT_PAYLOAD_BUDGET_BYTES = 5_000_000` (5 MB). At the
  tolerance the result is already the fewest samples within the bound, so the budget cannot be met
  by dropping more without breaking the bound; it is reported on the result (`within_budget`), never
  traded against the tolerance.
- **Interpolation hints are respected** — a `min_samples` floor (the converter sets it to
  `interpolation_degree + 1`) keeps enough support for the declared Lagrange / Hermite curve, whose
  algorithm and degree are carried onto the CZML unchanged (D3). The spatial cross-track bound is
  conservative for that higher-order interpolation, which passes through every kept sample.

The pass is pure geometry on an `(N, 3)` array — positions and tolerance share a unit (the converter
passes canonical km) — so it carries no schema or unit logic of its own.

## D10 — the validation harness: official schema, golden corpus, real producer fixtures

Correctness is two-headed — *is the CZML well-formed and renderable* and *is the geometry it
encodes right* — so the harness has three independent layers, each catching what the others miss:

- **Official-schema validation.** Every emitted document validates against the **official CZML
  JSON schema** (the CesiumGS/czml-writer `Schema/` tree, draft-07), vendored verbatim and
  dev/CI-only at a pinned upstream commit. This is deliberately *not* a re-parse through czml3:
  czml3 emits the document, so validating with it would be circular. A `referencing` registry keys
  every vendored file by its own `$id` so the cross-file `$ref`s resolve, and validation runs
  against `Document.json`. A negative control (a deliberately malformed clock) guards the harness
  itself against silently degrading into a no-op.
- **Headless-CesiumJS parse.** The runtime check that the output is not just valid JSON but a
  renderable, animated scene — a real browser loads the document through `CzmlDataSource.load` and
  the satellite's position is sampled across the clock span to assert a *correct orbit path*: the
  radius stays in the expected band, is near-constant (a LEO is near-circular), and varies over
  time. Positions are read in the document's inertial frame, so no Earth-orientation data is needed
  and the check stays hermetic. This catches valid-but-unrenderable output the schema check passes.
- **Golden-output regression.** Fixed inputs reproduce reference documents committed under
  `tests/data/golden/`. The comparison is **byte-exact first**; only on a mismatch does it fall back
  to a structural compare that forgives a sub-ULP floating-point difference. The reason is the
  ground track: the inertial → fixed rotation and the geodetic projection use transcendentals
  (`arctan2` / `sin` / `cos`) that are not correctly-rounded and select CPU-dependent code paths, so
  a ground-track longitude can differ by ~1 ULP — sub-nanometre on the ground — between CI runner
  microarchitectures, which a byte comparison alone would flag as a failure. The fallback forgives
  only that last-ULP noise (relative `1e-12`, absolute `1e-9`); any structural change, or a numeric
  change beyond a few ULP, still fails. The orbit-path goldens use only correctly-rounded operations
  (scaling, `sqrt`-based decimation) and stay byte-exact on every platform. The goldens remain the
  drift detector for the serialization-backend and producer pins — regenerated **deliberately**
  (gated behind an environment flag), never silently — and carry `-text` so the comparison survives
  line-ending normalisation on every platform.

**Producer fixtures.** Both correctness heads run end-to-end on two real producers, not synthetic
toys: a **real GMAT LEO CCSDS-OEM ephemeris** (committed as bytes and read through orbit-formats —
GMAT is neither a runtime nor a CI dependency; the generating mission script is committed alongside
so the fixture can be regenerated) and an **offline TLE propagation** from a non-GMAT producer
(dev-only, no network — it proves the canonical input contract is genuinely producer-agnostic). The
golden corpus spans both producers across the orbit-path, ground-track (multi-segment), and
multi-object paths.

## D11 — attitude: orientation is composed into Cesium's body→ECEF frame, never shipped raw

The attitude converter consumes orbit-formats' canonical `Attitude` (a CCSDS-AEM quaternion history)
and emits a sampled CZML `orientation`. The load-bearing decision is the **frame**, because
orientation does not behave like position:

- A CZML `position` carries a `referenceFrame`, and Cesium converts `INERTIAL` ↔ `FIXED` itself, so
  an inertial ephemeris is shipped untouched (D4). A CZML `orientation` carries **no** reference
  frame: Cesium always interprets the quaternion as the rotation from the object's **body** axes to
  the **Earth-fixed (ECEF)** axes. An AEM attitude is almost always expressed against an *inertial*
  reference (e.g. `EME2000 → SC_BODY`), so shipping its quaternion raw would render the orientation
  wrong by the Earth-rotation angle — tens of degrees over a single pass, far above visualization
  tolerance (unlike the EME2000-vs-ICRF bias D4 documents away).

So gmat-czml performs the **full composition**, per epoch:

1. **Identify the frames.** Exactly one of the AEM's two frames must resolve through
   `recognised_frame` (the external reference); the other is the body frame (`SC_BODY`, unrecognised).
   Neither/both resolving is a typed `AttitudeFrameError`.
2. **Form body → reference** from the stored quaternion, taking the rotation *direction* from the AEM
   `ATTITUDE_DIR` (`A2B` / `B2A`) — which orbit-formats parks on the `source_native` fidelity model,
   not the canonical schema — defaulting to the near-universal `A2B` when absent.
3. **Compose with reference → ECEF**, obtained per epoch from orbit-formats' `rotate_state` (the same
   Earth-orientation rotation the ground track delegates to under D5). An already-fixed reference
   short-circuits to the identity and loads no astropy; only an inertial reference loads it, lazily —
   so the attitude path's import weight matches the ground track's (D6), not the core path's.

The CCSDS quaternion is stored scalar-last (`Q1 Q2 Q3 QC`), which is exactly CZML's `[X, Y, Z, W]`
order, so there is no component reshuffle — only the frame composition. The quaternion is read in the
CCSDS coordinate-transformation convention (504.0-B); `_quaternion_to_matrix` matches Cesium's
`Matrix3.fromQuaternion` (the standard active rotation), verified against a +90° turn about +Z mapping
body +X to +Y, so the emitted quaternion is exactly what a client applies. A consequence worth noting:
an **already-Earth-fixed** source is a pure passthrough (`q_czml == q_source`), which is the cleanest
convention anchor in the test suite.

The orientation is emitted as an **epoch-relative sampled unit quaternion** with a `LINEAR`
interpolation hint (normalised linear interpolation is the robust default for orientation; a
higher-order scheme on raw quaternion components is not meaningful) and **hemisphere-continuous signs**
(`q` and `-q` are the same rotation, but a sign flip between samples makes a client interpolate the
long way). Because the orientation must attach to one object's position, it rides a child packet
`<entity_id>/attitude` that references the object's position and carries a schematic **box** (three
distinct, exaggerated dimensions) as the minimal model hook that makes the orientation visible — a
glTF-model hook waits on the asset pipeline. Like maneuvers, attitude attaches to the single rendered
object; a multi-object document raises `AmbiguousAttitudeTargetError`. Only the quaternion
representation is rendered; Euler-angle and spin attitudes raise `UnsupportedAttitudeTypeError` rather
than being guessed at.

**Note on the charter.** The charter's frame discussion was position-centric and scoped the
inertial→fixed rotation as "EOP machinery beyond what a ground track needs," assuming the ground track
was its sole consumer. Attitude is a second consumer of that same rotation. This decision corrects
that under-count: it reuses the existing ground-track-grade rotation at the same visualization
tolerance, so the charter's EOP non-goal stands intact (recorded as a charter erratum).

## D12 — imagery underlay is viewer-side configuration, not a CZML hint

The optional ground-track tile underlay (OpenStreetMap / Mapbox / Cesium ion) is **viewer
configuration**, not part of the emitted document. `to_czml`'s output is unchanged: a `.czml` carries
no base imagery, and the underlay is selected in the Cesium client.

- The bundled `examples/viewer.html` gains a **Base imagery** selector (offline / OSM / ion / Mapbox)
  and a **Clamp ground track to surface** toggle; both are wired into the headless `boot()` seam and a
  `?imagery=` query parameter. No converter, schema, or golden-output change.
- The ground-track converter keeps floating the polyline at the satellite's own geodetic height; a
  client that wants the track to hug imagery drapes it with `clampToGround` (the viewer's checkbox), so
  legibility over an underlay is a render-time choice rather than a second emitted geometry.

**Rationale.** CZML has no portable field for base imagery, so a `to_czml` "imagery hint" would be a
non-standard extension only this project's viewer could honour — every other Cesium client would
ignore it, while it coupled the portable document to one renderer's configuration. Keeping imagery
purely viewer-side leaves the document portable and the underlay a property of wherever it is rendered.

---

## Forward notes (not v0.1 decisions)

- **Maneuvers** (a later release) consume orbit-formats' canonical maneuver record rather than
  inventing a parallel one — the same convergence as the state schema.

## Cross-project dependency note

gmat-czml's ground track depends on orbit-formats' ECEF↔geodetic helper, which ships in the
upstream's 0.5 line. That release is now on PyPI, so gmat-czml floors at `orbit-formats>=0.5` and
the ground-track work is no longer gated on the upstream.
