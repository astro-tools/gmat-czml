"""A lunar transfer, from a real GMAT CCSDS-OEM ephemeris.

The deep-space interop case: GMAT targets a translunar trajectory — a low-perigee departure, a
trans-lunar injection, a powered swing past the Moon, and capture into lunar orbit — and writes it
as a CCSDS-OEM in Earth-centered EME2000 (committed here as a byte fixture). orbit-formats reads the
four-segment ephemeris as one continuous state series, and ``to_czml`` turns the whole eight-day
journey into a single Cesium scene that reaches past lunar distance — the same one call the
near-Earth examples use, no special handling for the scale.

The trajectory is Earth-centered, so the Moon's gravity shows as a bend in the path rather than a
body Cesium places: gmat-czml converts the geometry the producer computed, it does not model the
third body. The ground track is left off — it is an Earth-surface projection, meaningless out at
lunar distance.

Run it::

    python examples/lunar_transfer.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``). The scene spans
~400,000 km, so zoom out to frame the whole transfer.
"""

from __future__ import annotations

from pathlib import Path

from orbit_formats import read

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-lunar-transfer.oem"
OUTPUT = HERE / "output" / "lunar-transfer.czml"

# The journey is eight days; play it back over a minute and a half so the transfer arc is watchable.
_PLAYBACK_SECONDS = 90.0


def main() -> None:
    trajectory = read(INPUT)
    document = to_czml(trajectory, playback_seconds=_PLAYBACK_SECONDS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
