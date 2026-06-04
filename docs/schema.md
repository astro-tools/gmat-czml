# Canonical input schema

gmat-czml converts an already-computed trajectory; it never propagates one. The unit of input is
the **canonical state-series** — the same shape the org's format-I/O library
([orbit-formats](https://pypi.org/project/orbit-formats/)) emits from `Ephemeris.to_dataframe()`,
and the same shape a headless GMAT run produces — so a trajectory flows in with no reshaping.
gmat-czml adopts that schema verbatim and is a pure consumer of it.

## The DataFrame

A trajectory is a pandas `DataFrame` with one row per sample.

### Columns

| Column | Meaning | dtype | Required |
|--------|---------|-------|:--------:|
| `Epoch` | sample time | `datetime64[ns]` | yes |
| `X`, `Y`, `Z` | position components | `float64` | yes |
| `VX`, `VY`, `VZ` | velocity components | `float64` | no |

`Epoch, X, Y, Z` are always required. Velocity is optional — but it is all-or-nothing: declare all
three of `VX, VY, VZ` or none. A partial velocity declaration is rejected.

### Metadata (`DataFrame.attrs`)

| Key | Meaning | Used for |
|-----|---------|----------|
| `object_name` | object identity | the label / point name, and the packet id |
| `central_body` | central body (e.g. `Earth`) | gates the ground track |
| `coordinate_system` | reference frame | the CZML reference frame |
| `time_scale` | one of `UTC TAI TT TDB GPS UT1` | conversion to UTC |
| `epoch_scales` | `{"Epoch": <time_scale>}` | per-column scale (a fallback for `time_scale`) |
| `units` | `{length, speed, angle, time}` (default `km, km/s, deg, s`) | conversion to metres |
| `interpolation` | interpolation algorithm name | the CZML interpolation hint |
| `interpolation_degree` | interpolation degree | the CZML interpolation hint |

**The reference frame and the time scale are required, never guessed** — both are load-bearing for
the CZML reference frame and the UTC clock. Everything else is read with a sensible default. A
missing or malformed *required* element raises a [typed error](api.md#errors) naming what is wrong,
never a bare `KeyError`.

```python
import pandas as pd

frame = pd.DataFrame({"Epoch": epochs, "X": x, "Y": y, "Z": z, "VX": vx, "VY": vy, "VZ": vz})
frame.attrs.update(
    {
        "object_name": "MySat",
        "central_body": "Earth",
        "coordinate_system": "EME2000",
        "time_scale": "UTC",
        "units": {"length": "km", "speed": "km/s", "angle": "deg", "time": "s"},
        "interpolation": "LAGRANGE",
        "interpolation_degree": 5,
    }
)
```

## Recognised reference frames

A frame name is recognised case- and whitespace-insensitively, through orbit-formats' shared alias
table plus GMAT's own spellings:

| Class | Names |
|-------|-------|
| Inertial | `EME2000`, `J2000`, `GCRF`, `ICRF`, `TEME`, and GMAT's `EarthMJ2000Eq` |
| Earth-fixed | `ITRF`, and GMAT's `EarthFixed` |

Inertial frames map to the CZML `INERTIAL` frame, Earth-fixed to `FIXED`. `EME2000` differs from
Cesium's ICRF by a frame bias of tens of milliarcseconds and `TEME` by a small rotation — both far
below visualization tolerance, so they are used directly. An unrecognised frame raises rather than
being mapped to the wrong axes. Use [`recognised_frame`][gmat_czml.recognised_frame] to check a
name.

## Recognised time scales

`UTC`, `TAI`, `TT`, `TDB`, `GPS`, `UT1`. The scale is read from `attrs['time_scale']`, falling back
to `attrs['epoch_scales']['Epoch']`. Any non-UTC scale is converted to UTC (leap-second-correct)
for the CZML clock.

## Other accepted inputs

Besides a `DataFrame`, [`to_czml`][gmat_czml.to_czml] also accepts:

- an orbit-formats `Ephemeris` (already parsed and carrying the same metadata);
- **any file orbit-formats can read** (an OEM, a GMAT report, an SP3, an STK ephemeris, …) — pass
  it through `orbit_formats.read()` first, or hand the path to the [CLI](cli.md);
- an **iterable** of any of the above — one trajectory per object, for a multi-object document.
  Object identity comes from `attrs['object_name']`, which must be unique across the collection.

## Multiple objects

```python
from gmat_czml import to_czml

to_czml([sat_a, sat_b, sat_c], ground_track=True).save("constellation.czml")
```

Each input becomes its own CZML packet (plus its ground-track packets). Validation never mutates
the inputs you pass.
