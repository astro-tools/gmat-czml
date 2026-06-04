"""A non-GMAT producer: an ISS TLE propagated with Skyfield.

gmat-czml is not GMAT-specific. Here the trajectory comes from a TLE propagated by Skyfield —
no GMAT anywhere — assembled into the same canonical state series and converted with the same
``to_czml`` call, ground track included. If a producer yields the canonical schema, it renders.

The propagation is fully offline: Skyfield's bundled timescale (``builtin=True``) needs no
download, and an Earth-satellite position needs no JPL ephemeris.

Skyfield is not a gmat-czml runtime dependency — install it to run this example::

    pip install skyfield
    python examples/skyfield_tle.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "iss.tle"
OUTPUT = HERE / "output" / "skyfield-iss.czml"


def iss_dataframe() -> pd.DataFrame:
    """The committed ISS TLE propagated ~one orbit with Skyfield, as the canonical state series.

    Positions land in GCRS (tagged ``GCRF``), the inertial frame gmat-czml recognises.
    """
    name, line1, line2 = INPUT.read_text(encoding="utf-8").splitlines()[:3]
    timescale = load.timescale(builtin=True)
    satellite = EarthSatellite(line1, line2, name.strip(), timescale)

    minutes = np.arange(0.0, 93.0, 3.0)  # ~one ISS revolution, a sample every 3 minutes
    times = timescale.utc(2024, 1, 9, 12, minutes)
    geocentric = satellite.at(times)
    position_km = np.asarray(geocentric.position.km, dtype=np.float64)
    velocity_kms = np.asarray(geocentric.velocity.km_per_s, dtype=np.float64)

    frame = pd.DataFrame(
        {
            "Epoch": pd.to_datetime(times.utc_datetime()).tz_localize(None),
            "X": position_km[0],
            "Y": position_km[1],
            "Z": position_km[2],
            "VX": velocity_kms[0],
            "VY": velocity_kms[1],
            "VZ": velocity_kms[2],
        }
    )
    frame.attrs.update(
        {
            "object_name": "ISS (ZARYA)",
            "central_body": "Earth",
            "coordinate_system": "GCRF",
            "time_scale": "UTC",
            "units": {"length": "km", "speed": "km/s", "angle": "deg", "time": "s"},
            "interpolation": "LAGRANGE",
            "interpolation_degree": 5,
        }
    )
    return frame


def main() -> None:
    document = to_czml(iss_dataframe(), ground_track=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
