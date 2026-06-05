"""Maneuvers: impulsive and finite burns as markers on the orbit.

Builds on the flagship GMAT LEO ephemeris and annotates it with two burns — an impulsive maneuver
pinned where it happens, and a finite maneuver drawn as a highlighted arc over the span it fires.
The burns here are illustrative ``Maneuver`` records; a real mission reads them from a CCSDS OPM /
OCM through orbit-formats (``read("burns.opm")``) and passes them the same way.

Run it::

    python examples/maneuver_mission.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from orbit_formats import Maneuver, read

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-leo.oem"
OUTPUT = HERE / "output" / "maneuvers.czml"


def _maneuvers() -> list[Maneuver]:
    """One impulsive and one finite burn, both inside the ephemeris span (UTC, RTN, km/s)."""
    impulsive = Maneuver(
        epoch_ignition=np.datetime64("2026-03-01T00:20:00"),
        ref_frame="RTN",
        duration=0.0,
        delta_v=np.array([0.012, 0.0, 0.0]),
    )
    finite = Maneuver(
        epoch_ignition=np.datetime64("2026-03-01T00:50:00"),
        ref_frame="RTN",
        duration=180.0,
        delta_v=np.array([0.0, 0.006, 0.0]),
    )
    return [impulsive, finite]


def main() -> None:
    trajectory = read(INPUT)
    document = to_czml(trajectory, maneuvers=_maneuvers())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
