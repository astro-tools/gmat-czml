"""LEO orbit with a ground track, from a real GMAT CCSDS-OEM ephemeris.

The flagship interop example: a trajectory GMAT already computed (committed here as a CCSDS-OEM
byte fixture) becomes an animated Cesium scene through one call. orbit-formats reads the OEM —
gmat-czml ships no readers of its own — and ``to_czml(..., ground_track=True)`` emits the orbit
path plus the sub-satellite ground track.

Run it::

    python examples/leo_ground_track.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from pathlib import Path

from orbit_formats import read

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-leo.oem"
OUTPUT = HERE / "output" / "leo-ground-track.czml"


def main() -> None:
    trajectory = read(INPUT)
    document = to_czml(trajectory, ground_track=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
