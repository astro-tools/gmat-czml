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
- **The bundled viewer** — run `python examples/serve.py` (CesiumJS needs Web Workers, which
  browsers block on a `file://` page, so it must be served over http) and drag a `.czml` onto the
  page. Its **Base imagery** dropdown picks the globe underlay — offline (the default), OpenStreetMap,
  Cesium ion, or Mapbox — see [Imagery underlay](#imagery-underlay-osm-mapbox) below.
- **Your own app** — load the document with `Cesium.CzmlDataSource.load()` in CesiumJS, Cesium ion,
  or [Resium](https://resium.reearth.io/) (React). See the [client matrix](https://github.com/astro-tools/gmat-czml#supported-cesium-clients).

See the [Gallery](gallery.md) for complete, runnable examples.

## Imagery underlay (OSM / Mapbox)

CZML carries no base imagery — the underlay is a property of the Cesium client, not the document — so
the same `.czml` renders over whatever globe imagery the viewer is configured for. The bundled viewer
offers four base layers in its **Base imagery** dropdown:

| Option | Imagery | Token |
|--------|---------|-------|
| Offline (bundled) | Natural Earth II shipped with CesiumJS | none (no network) |
| OpenStreetMap | OSM street tiles | none |
| Cesium ion world imagery | ion's high-resolution imagery | a Cesium ion token |
| Mapbox | Mapbox `satellite-streets` | a Mapbox access token |

Paste a token for ion or Mapbox (stored in your browser only); a token-requiring option falls back to
the offline imagery when no token is supplied, so the globe is never blank. A `?imagery=osm` (or
`ion` / `mapbox` / `offline`) query parameter selects the underlay for a shareable link.

### In your own app

The underlay is a few lines of CesiumJS. For an OpenStreetMap base layer (no token):

```js
const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: Cesium.ImageryLayer.fromProviderAsync(
    Promise.resolve(
      new Cesium.UrlTemplateImageryProvider({
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        credit: "© OpenStreetMap contributors",
        maximumLevel: 19,
      })
    )
  ),
});
const dataSource = await Cesium.CzmlDataSource.load("orbit.czml");
viewer.dataSources.add(dataSource);
```

For Mapbox, swap the base layer for a `MapboxStyleImageryProvider` carrying your access token:

```js
baseLayer: Cesium.ImageryLayer.fromProviderAsync(
  Promise.resolve(
    new Cesium.MapboxStyleImageryProvider({ styleId: "satellite-streets-v12", accessToken: MAPBOX_TOKEN })
  )
),
```

The public OSM tile server is fine for a quick look but is governed by the
[OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/) — use a dedicated tile
host (or Mapbox / ion) for anything beyond casual use.

### Clamping the ground track

The ground track floats at the satellite's own geodetic height (see
[Ground track](conversion/ground-track.md)), which lines up with the underlay seen from straight
overhead but rides above it in a tilted view. To make the track hug the imagery, drape its polylines
onto the globe with `clampToGround` — the bundled viewer's **Clamp ground track to surface** checkbox
does exactly this:

```js
for (const entity of dataSource.entities.values) {
  if (entity.polyline && /(^|\/)groundtrack(\/|$)/.test(entity.id)) {
    entity.polyline.clampToGround = true;
  }
}
```
