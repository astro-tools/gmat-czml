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
  enough to load quickly and to fit an attachment. Provisional defaults — a ~1 km cross-track
  geometric tolerance and a ~5 MB soft payload budget — are finalised when the sampling module
  lands.
- **`to_czml` and the CLI accept any file orbit-formats can read** (via its `read()`), so file
  input comes for free and gmat-czml ships no format readers of its own.

---

## Forward notes (not v0.1 decisions)

- **Maneuvers** (a later release) consume orbit-formats' canonical maneuver record rather than
  inventing a parallel one — the same convergence as the state schema.
- **Attitude** (a later release) consumes orbit-formats' attitude canonical type (read from a CCSDS
  attitude message) for the sampled orientation.

## Cross-project dependency note

gmat-czml's ground track depends on orbit-formats' ECEF↔geodetic helper, which ships in the
upstream's 0.5 line. gmat-czml's `orbit-formats>=0.5` floor reflects that; the ground-track work is
gated on that upstream release being available.
