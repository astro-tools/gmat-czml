# Examples

Runnable scripts that turn a trajectory into a CZML document. Each writes its `.czml` to
`examples/output/` (git-ignored — regenerate any time).

**Producer archetypes** — one trajectory, one call:

| Script | Producer | Shows |
|--------|----------|-------|
| [`leo_ground_track.py`](leo_ground_track.py) | a real GMAT CCSDS-OEM ([`data/gmat-leo.oem`](data/gmat-leo.oem)) | LEO orbit path **and** ground track |
| [`geo.py`](geo.py) | analytic, in-script (no file) | a geostationary orbit, built straight as the canonical schema |
| [`skyfield_tle.py`](skyfield_tle.py) | an ISS TLE ([`data/iss.tle`](data/iss.tle)) propagated with Skyfield | a non-GMAT producer through the same one call |

**v0.2 entities** — the same GMAT LEO, annotated:

| Script | Shows |
|--------|-------|
| [`contacts_mission.py`](contacts_mission.py) | ground stations and a line of sight shown only during each access window |
| [`maneuver_mission.py`](maneuver_mission.py) | an impulsive burn pinned on the orbit and a finite burn as a highlighted arc |
| [`attitude_mission.py`](attitude_mission.py) | the spacecraft's body axes animated over the orbit (the gallery GIF) |

## Running

From the repository root, with the package installed (`uv sync` or `pip install -e .`):

```bash
python examples/leo_ground_track.py
python examples/geo.py
python examples/skyfield_tle.py      # needs Skyfield: pip install skyfield
python examples/contacts_mission.py
python examples/maneuver_mission.py
python examples/attitude_mission.py
```

`skyfield_tle.py` is the only one with an extra dependency — Skyfield is a non-GMAT producer, not
a gmat-czml runtime dependency.

**Live serving** — host a document over http behind an embedded viewer, no file written:

| Script | Shows |
|--------|-------|
| [`serve_document.py`](serve_document.py) | `to_czml(...).serve()` — the one-click local-sharing path (needs `pip install gmat-czml[server]`) |

```bash
pip install gmat-czml[server]    # fastapi + uvicorn
python examples/serve_document.py    # opens http://127.0.0.1:8080/; Ctrl-C to stop
```

`gmat-czml serve examples/data/gmat-leo.oem --ground-track` is the CLI equivalent.

## Viewing the output

[`viewer.html`](viewer.html) must be loaded over **http**, not opened as a `file://` — CesiumJS
needs Web Workers, which browsers refuse to create on a `file://` (null-origin) page, so the globe
won't render there. The simplest way:

```bash
python examples/serve.py        # serves this folder and opens the viewer
```

Then **drag a `.czml` file from `examples/output/` onto the page** (or use *Choose file*). The
**Base imagery** dropdown picks the globe underlay — offline (the default, bundled in CesiumJS),
OpenStreetMap, Cesium ion, or Mapbox; paste a Cesium ion or Mapbox token in the box for the two that
need one (stored in your browser only, never committed). A **Clamp ground track to surface** checkbox
drapes the ground track onto the globe so it hugs the imagery. See
[Imagery underlay](../docs/getting-started.md#imagery-underlay-osm-mapbox) for the recipe.

(Equivalently, run `python -m http.server` in this folder and open
`http://localhost:8000/viewer.html`.)

You can also drop any `.czml` into the [Cesium Sandcastle](https://sandcastle.cesium.com/) or load
it with `Cesium.CzmlDataSource.load()` in your own CesiumJS / Resium app.

## Regenerating the documentation visuals

The screenshots and GIF in the docs gallery are produced headlessly by
[`../scripts/render_gallery.py`](../scripts/render_gallery.py), which runs these scripts, loads
each output in `viewer.html`, and captures the frames. It reads the ion token from the
`CESIUM_ION_TOKEN` environment variable (falling back to offline imagery if unset). See that
script's header for details.
