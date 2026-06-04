# Gallery

Three runnable examples, one per producer archetype. Each lives under
[`examples/`](https://github.com/astro-tools/gmat-czml/tree/main/examples) and writes a `.czml` you
can open in any Cesium client — see [viewing the output](getting-started.md#viewing-the-result).

Run them from the repository root with the package installed:

```bash
python examples/leo_ground_track.py
python examples/geo.py
python examples/skyfield_tle.py      # needs Skyfield: pip install skyfield
```

The images below are rendered with [Cesium ion](https://cesium.com/platform/cesium-ion/) world
imagery.

## LEO with ground track — from a GMAT ephemeris

The flagship interop case: a trajectory GMAT already computed, read from a CCSDS-OEM and converted
with the ground track enabled.

![A GMAT LEO ephemeris animated in Cesium with its ground track](assets/gallery/leo-ground-track.gif){ width="640" }

```python
from orbit_formats import read
from gmat_czml import to_czml

trajectory = read("examples/data/gmat-leo.oem")
to_czml(trajectory, ground_track=True).save("leo-ground-track.czml")
```

Source: [`examples/leo_ground_track.py`](https://github.com/astro-tools/gmat-czml/blob/main/examples/leo_ground_track.py).

## A geostationary orbit — built in code

Not every producer is a file reader. This one builds a circular geostationary orbit directly as the
[canonical schema](schema.md), proving the schema — not a GMAT file — is the real input contract.

![A geostationary orbit rendered in Cesium](assets/gallery/geo.png){ width="520" }

Source: [`examples/geo.py`](https://github.com/astro-tools/gmat-czml/blob/main/examples/geo.py).

## A non-GMAT producer — an ISS TLE via Skyfield

A TLE propagated by [Skyfield](https://rhodesmill.org/skyfield/) — no GMAT anywhere — through the
same one call, ground track included.

![An ISS orbit and ground track in Cesium](assets/gallery/skyfield-iss.png){ width="520" }

Source: [`examples/skyfield_tle.py`](https://github.com/astro-tools/gmat-czml/blob/main/examples/skyfield_tle.py).

## Rendering these images

The screenshots and GIF here are produced headlessly by
[`scripts/render_gallery.py`](https://github.com/astro-tools/gmat-czml/blob/main/scripts/render_gallery.py),
which runs the examples, loads each output in the bundled viewer, and captures the frames. The
committed images are what this site embeds, so building the docs never needs a browser.
