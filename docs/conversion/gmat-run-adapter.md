# gmat-run adapter

[gmat-run](https://pypi.org/project/gmat-run/) runs a GMAT mission headlessly and hands back a
`Results` whose ephemerides and contacts are already keyed `pandas.DataFrame` views over the run's
output. A GMAT ephemeris DataFrame **is** gmat-czml's canonical state series — the same
`Epoch, X, Y, Z[, VX, VY, VZ]` columns and the same `attrs` spine — so a trajectory flows straight
into [`to_czml`][gmat_czml.to_czml] with no reshaping. The adapter is the thin convenience that
bundles a whole `Results` into one document.

It lives in its own module, `gmat_czml.adapters.gmat_run`, because **gmat-run is an optional
dependency**: it is imported only inside the adapter functions, so importing gmat-czml never needs it.
Calling the adapter without gmat-run installed raises a clear `ImportError` naming the install.

```python
from gmat_czml.adapters.gmat_run import to_czml_from_results

document = to_czml_from_results(results, ground_track=True)
document.save("mission.czml")
```

`results` is the `Results` a gmat-run mission returns. Every `EphemerisFile` resource in it becomes
one object in the document; `style`, `playback_seconds`, and `ground_track` are forwarded to
[`to_czml`][gmat_czml.to_czml] unchanged.

## Selecting ephemerides

By default every ephemeris in the run renders, in insertion order. Pass `ephemerides` (a sequence of
resource names) to render a subset, in the order given:

```python
to_czml_from_results(results, ephemerides=["LeoSat", "GeoSat"], ground_track=True)
```

When a resource's source declared no `OBJECT_NAME`, the adapter names the object after the resource
key, so every object has a stable, unique id. [`results_to_trajectories`][gmat_czml.adapters.gmat_run.results_to_trajectories]
exposes the same step on its own — the canonical DataFrames, one per resource — if you want to
inspect or decorate them before converting.

## Adding contacts

A GMAT `ContactLocator` report names each observer and its access windows, but **not** the observer's
geodetic position — that lives on the `GroundStation` resource in the mission *script*, not in the run
output. So you supply each observer's placement through a `stations` mapping, and the adapter pairs it
with the windows it reads from the report:

```python
from gmat_czml import GroundStation
from gmat_czml.adapters.gmat_run import to_czml_from_results

stations = {
    "Canberra": GroundStation("Canberra", latitude=-35.40, longitude=148.98, height=0.69),
    "Madrid": GroundStation("Madrid", latitude=40.43, longitude=-4.25, height=0.72),
}
to_czml_from_results(results, stations=stations, ground_track=True).save("mission.czml")
```

Every observer named in a mapped report must have a placement in `stations`, or the call raises
[`MissingStationError`][gmat_czml.adapters.gmat_run.MissingStationError]. Without `stations` no
contacts are rendered; `contact_resources` selects a subset of the run's `ContactLocator` resources
and is an error without `stations`. As with the ephemerides,
[`results_to_contacts`][gmat_czml.adapters.gmat_run.results_to_contacts] runs the contact mapping on
its own.

The adapter reads each window from the report's `Start` / `Stop` columns, so it needs a
window-bearing `ContactLocator` format (Legacy, `ContactRangeReport`, or a SiteView variant). The
per-tick `AzimuthElevationRange` variants report one `Time` per sample rather than an interval, so
they carry no windows to map and raise
[`UnsupportedContactFormatError`][gmat_czml.adapters.gmat_run.UnsupportedContactFormatError].

## What does not map

A `Results` is the run's *output*, which bounds what the adapter can reach:

| Entity | From a `Results`? |
|--------|-------------------|
| Ephemerides | **Yes** — one object per `EphemerisFile` resource |
| Contacts | **Yes**, with a `stations` mapping for the observer placements |
| Maneuvers | **No** — a `Results` carries no maneuver output |
| Attitude | **No** — attitude lives on the mission, not the `Results` |

To annotate a document with [maneuvers](maneuvers.md) or [attitude](attitude.md), read the source
`.opm` / `.aem` through orbit-formats and pass the resulting `Maneuver` / `Attitude` to
[`to_czml`][gmat_czml.to_czml] directly — exactly as the standalone examples do.

## Errors

The adapter's own typed errors — `MissingStationError` and `UnsupportedContactFormatError` — descend
from [`GmatCzmlError`][gmat_czml.GmatCzmlError], so they are catchable with the rest of the family,
but live in the adapter module rather than the core error set: they are concepts only this optional
adapter raises. Errors from the conversion itself (an unknown contact target, a duplicate object name,
an empty `Results`) propagate from [`to_czml`][gmat_czml.to_czml] unchanged. The full surface is in
the [API reference](../api.md#gmat-run-adapter).
