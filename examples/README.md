# Examples

Runnable scripts that turn a trajectory into a CZML document, one per producer archetype. Each
writes its `.czml` to `examples/output/` (git-ignored — regenerate any time).

| Script | Producer | Shows |
|--------|----------|-------|
| [`leo_ground_track.py`](leo_ground_track.py) | a real GMAT CCSDS-OEM ([`data/gmat-leo.oem`](data/gmat-leo.oem)) | LEO orbit path **and** ground track |
| [`geo.py`](geo.py) | analytic, in-script (no file) | a geostationary orbit, built straight as the canonical schema |
| [`skyfield_tle.py`](skyfield_tle.py) | an ISS TLE ([`data/iss.tle`](data/iss.tle)) propagated with Skyfield | a non-GMAT producer through the same one call |

## Running

From the repository root, with the package installed (`uv sync` or `pip install -e .`):

```bash
python examples/leo_ground_track.py
python examples/geo.py
python examples/skyfield_tle.py      # needs Skyfield: pip install skyfield
```

`skyfield_tle.py` is the only one with an extra dependency — Skyfield is a non-GMAT producer, not
a gmat-czml runtime dependency.

## Viewing the output

[`viewer.html`](viewer.html) must be loaded over **http**, not opened as a `file://` — CesiumJS
needs Web Workers, which browsers refuse to create on a `file://` (null-origin) page, so the globe
won't render there. The simplest way:

```bash
python examples/serve.py        # serves this folder and opens the viewer
```

Then **drag a `.czml` file from `examples/output/` onto the page** (or use *Choose file*). It
renders with the offline imagery bundled in CesiumJS; paste a Cesium ion access token in the box for
ion world imagery — the token is stored in your browser only and is never committed.

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
