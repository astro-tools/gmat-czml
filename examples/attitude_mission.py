"""Attitude: a spacecraft's body axes animated over the orbit.

Builds on the flagship GMAT LEO ephemeris and attaches an attitude history — here a slow, steady
roll about the body Z axis, one full turn over the orbit — so a Cesium client animates the body box
turning as the playhead moves. A real mission reads its attitude from a CCSDS AEM through
orbit-formats (``read("spacecraft.aem")``) and passes it the same way; this example synthesizes the
quaternion history directly so it stays self-contained and offline.

The gallery render captures this one as an animated GIF (the body axes turning over the pass).

Run it::

    python examples/attitude_mission.py

then load the written ``.czml`` in any Cesium client (see ``examples/viewer.html``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from orbit_formats import Attitude, Ephemeris, Metadata, read

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-leo.oem"
OUTPUT = HERE / "output" / "attitude.czml"


def _attitude(trajectory: Ephemeris) -> Attitude:
    """One full body-Z roll over the trajectory span, as a scalar-last quaternion per epoch."""
    epochs = np.asarray(trajectory.epochs, dtype="datetime64[ns]")
    seconds = (epochs - epochs[0]) / np.timedelta64(1, "s")
    angle = 2.0 * np.pi * seconds / seconds[-1]  # 0 -> 2pi over the span
    half = angle / 2.0
    zeros = np.zeros_like(half)
    # Scalar-last [Q1, Q2, Q3, QC] = [X, Y, Z, W]: a rotation by ``angle`` about the body Z axis.
    records = np.column_stack([zeros, zeros, np.sin(half), np.cos(half)])
    return Attitude(
        metadata=Metadata(
            object_name=trajectory.metadata.object_name,
            time_scale=trajectory.metadata.time_scale,
        ),
        attitude_type="QUATERNION",
        epochs=epochs,
        records=records,
        frame_a=trajectory.metadata.reference_frame,
        frame_b="SC_BODY",
    )


def main() -> None:
    trajectory = read(INPUT)
    document = to_czml(trajectory, attitude=_attitude(trajectory))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
