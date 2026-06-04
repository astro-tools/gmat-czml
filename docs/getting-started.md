# Getting started

## Install

```bash
pip install gmat-czml
```

gmat-czml requires Python 3.10–3.12. It pulls in [czml3](https://pypi.org/project/czml3/) for CZML
serialization and [orbit-formats](https://pypi.org/project/orbit-formats/) for the canonical schema,
the frame rotation, and the file readers.

## The one call

Everything goes through [`to_czml`][gmat_czml.to_czml]. Hand it a trajectory and it returns a
[`CzmlDocument`][gmat_czml.CzmlDocument]:

```python
from gmat_czml import to_czml

czml = to_czml(trajectory)
czml.save("orbit.czml")
```

`trajectory` is whatever carries the [canonical state series](schema.md): a pandas `DataFrame`, an
orbit-formats `Ephemeris`, **a file orbit-formats can read** (an OEM, a GMAT report, an SP3, an STK
ephemeris, …), or an iterable of any of these for a multi-object scene.

### From a GMAT (or any) ephemeris file

Reading is delegated to orbit-formats, so any format it understands works without extra code:

```python
from orbit_formats import read
from gmat_czml import to_czml

trajectory = read("mission.oem")
to_czml(trajectory, ground_track=True).save("mission.czml")
```

### From a DataFrame you build yourself

Any producer that yields the canonical columns and metadata feeds the same call — see the
[schema reference](schema.md) for the full contract:

```python
import pandas as pd
from gmat_czml import to_czml

frame = pd.DataFrame({"Epoch": epochs, "X": x, "Y": y, "Z": z, "VX": vx, "VY": vy, "VZ": vz})
frame.attrs.update(
    {
        "object_name": "MySat",
        "central_body": "Earth",
        "coordinate_system": "EME2000",
        "time_scale": "UTC",
    }
)
to_czml(frame).save("mysat.czml")
```

## Options

```python
to_czml(
    trajectory,
    ground_track=True,      # also emit the sub-satellite ground track (Earth-only)
    playback_seconds=60.0,  # the whole span plays back in ~this many wall-clock seconds
)
```

- **`ground_track`** is **off by default**. Turning it on is the only path that loads the
  Earth-orientation rotation (and astropy, transitively), so the core orbit-path conversion stays
  light unless you ask for a ground track. See [Ground track](conversion/ground-track.md).
- **`playback_seconds`** sets the document clock's default speed: the trajectory plays back in
  roughly that many seconds of real time (floored at 1×).

A malformed input raises a [typed error](api.md#errors) naming exactly what is wrong — a missing
column, an unrecognised frame, an absent time scale — rather than a bare `KeyError`.

## Getting the output

A [`CzmlDocument`][gmat_czml.CzmlDocument] is in-memory first; nothing touches disk unless you ask:

```python
czml = to_czml(trajectory)

czml.save("orbit.czml")   # write a .czml file (returns the Path)
text = czml.to_json()     # the document as a CZML JSON string
packets = czml.to_dict()  # the document as a list of packet dicts
```

`save` writes exactly what `to_json` returns, byte-for-byte.

## Viewing the result

CZML is rendered by a Cesium client, not by gmat-czml. The quickest ways to see a document:

- **[Cesium Sandcastle](https://sandcastle.cesium.com/)** — paste a `Cesium.CzmlDataSource.load()`
  snippet, or drag your `.czml` onto the page. Nothing to install.
- **The bundled viewer** — open [`examples/viewer.html`](https://github.com/astro-tools/gmat-czml/blob/main/examples/viewer.html)
  in a desktop browser and drag a `.czml` onto it. It uses CesiumJS's offline imagery by default;
  paste a Cesium ion token for ion world imagery.
- **Your own app** — load the document with `Cesium.CzmlDataSource.load()` in CesiumJS, Cesium ion,
  or [Resium](https://resium.reearth.io/) (React). See the [client matrix](https://github.com/astro-tools/gmat-czml#supported-cesium-clients).

See the [Gallery](gallery.md) for complete, runnable examples.
