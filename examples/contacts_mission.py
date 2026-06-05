"""Ground-station contacts: observer placement and a windowed line of sight.

Builds on the flagship GMAT LEO ephemeris, adds two ground stations, and renders the access
(contact) windows between each station and the satellite — an observer entity on the globe and a
line of sight drawn only while the station can see the spacecraft.

Real access windows come from an access tool (a GMAT ``ContactLocator``, say). To keep this example
self-contained and offline, it synthesizes a plausible pair: it projects the orbit to its
sub-satellite track — with the same orbit-formats rotation the ground track uses — and places each
station directly beneath the satellite at a chosen instant, with a window bracketing the pass.

Run it::

    python examples/contacts_mission.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from orbit_formats import Ephemeris, read
from orbit_formats.convert.frames import rotate_state
from orbit_formats.convert.geodetic import cartesian_to_geodetic

from gmat_czml import Contact, GroundStation, to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-leo.oem"
OUTPUT = HERE / "output" / "contacts.czml"

# Minutes into the pass at which each station sits beneath the satellite, and the half-width of the
# window bracketing that overhead instant (a realistic few-minute LEO pass).
_OVERHEAD_MINUTES = (30.0, 60.0)
_HALF_WINDOW = timedelta(minutes=4.0)


def _subsatellite(trajectory: Ephemeris) -> tuple[np.ndarray, np.ndarray]:
    """The sub-satellite longitude / latitude (degrees) per epoch, via the public frame rotation."""
    positions_km = np.asarray(trajectory.positions, dtype=np.float64)
    epochs = np.asarray(trajectory.epochs, dtype="datetime64[ns]")
    ecef, _ = rotate_state(
        positions_km,
        np.zeros_like(positions_km),
        epochs,
        time_scale=trajectory.metadata.time_scale,
        from_frame=trajectory.metadata.reference_frame,
        to_frame="ITRF",
    )
    lon, lat, _height = cartesian_to_geodetic(ecef)
    return lon, lat


def _contact(
    trajectory: Ephemeris,
    lon: np.ndarray,
    lat: np.ndarray,
    minutes: float,
    *,
    name: str,
    target: str,
) -> Contact:
    """A station beneath the satellite at ``minutes`` into the pass, plus its access window."""
    epochs = np.asarray(trajectory.epochs, dtype="datetime64[ns]")
    overhead = epochs[0] + np.timedelta64(round(minutes * 60_000), "ms")
    index = int(np.argmin(np.abs(epochs - overhead)))
    moment = np.asarray(epochs[index]).astype("datetime64[us]").astype(datetime)
    station = GroundStation(name=name, latitude=float(lat[index]), longitude=float(lon[index]))
    window = (moment - _HALF_WINDOW, moment + _HALF_WINDOW)
    return Contact(observer=station, target=target, windows=[window])


def main() -> None:
    trajectory = read(INPUT)
    target = trajectory.metadata.object_name
    lon, lat = _subsatellite(trajectory)
    contacts = [
        _contact(trajectory, lon, lat, _OVERHEAD_MINUTES[0], name="Station-A", target=target),
        _contact(trajectory, lon, lat, _OVERHEAD_MINUTES[1], name="Station-B", target=target),
    ]
    document = to_czml(trajectory, contacts=contacts, ground_track=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
