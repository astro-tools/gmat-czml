"""A geostationary orbit, generated analytically — no input file.

Not every producer is a file reader. This script builds one sidereal-day circular equatorial
orbit at the geostationary radius directly as the canonical state-series ``DataFrame`` gmat-czml
consumes (epochs, position, velocity, and the metadata spine on ``attrs``), then converts it with
the same ``to_czml`` call every other producer uses. It is the smallest demonstration that the
canonical schema — not a GMAT file — is the real input contract.

Run it::

    python examples/geo.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from gmat_czml import to_czml

HERE = Path(__file__).parent
OUTPUT = HERE / "output" / "geo.czml"

# A two-body circular geostationary orbit in the EME2000 inertial frame.
_GM_EARTH_KM3_S2 = 398600.4418  # Earth's gravitational parameter, km^3/s^2
_GEO_RADIUS_KM = 42164.0  # circular geostationary orbit radius
_EPOCH = "2026-03-01T00:00:00"
_SAMPLE_STEP_S = 60.0


def geo_dataframe() -> pd.DataFrame:
    """One full geostationary revolution as the canonical state series (EME2000 / UTC, km)."""
    period_s = 2.0 * np.pi * np.sqrt(_GEO_RADIUS_KM**3 / _GM_EARTH_KM3_S2)
    angular_rate = 2.0 * np.pi / period_s  # rad/s
    speed_kms = _GEO_RADIUS_KM * angular_rate

    seconds = np.arange(0.0, period_s, _SAMPLE_STEP_S)
    angle = angular_rate * seconds

    frame = pd.DataFrame(
        {
            "Epoch": pd.Timestamp(_EPOCH) + pd.to_timedelta(seconds, unit="s"),
            "X": _GEO_RADIUS_KM * np.cos(angle),
            "Y": _GEO_RADIUS_KM * np.sin(angle),
            "Z": np.zeros_like(seconds),
            "VX": -speed_kms * np.sin(angle),
            "VY": speed_kms * np.cos(angle),
            "VZ": np.zeros_like(seconds),
        }
    )
    frame.attrs.update(
        {
            "object_name": "GEO-SAT",
            "central_body": "Earth",
            "coordinate_system": "EME2000",
            "time_scale": "UTC",
            "units": {"length": "km", "speed": "km/s", "angle": "deg", "time": "s"},
            "interpolation": "LAGRANGE",
            "interpolation_degree": 5,
        }
    )
    return frame


def main() -> None:
    document = to_czml(geo_dataframe())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
