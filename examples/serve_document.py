"""Serve a trajectory live in the browser with the optional ``[server]`` extra.

The one-click local-sharing path: read a trajectory GMAT already computed (the committed CCSDS-OEM
fixture), assemble the CZML in memory, and host it over http behind an embedded CesiumJS viewer with
a single :meth:`~gmat_czml.CzmlDocument.serve` call — no file is written. Because the page is served
over http (not ``file://``), CesiumJS's Web Workers and imagery load, so the globe renders.

This needs the optional server extra::

    pip install gmat-czml[server]      # fastapi + uvicorn

Run it::

    python examples/serve_document.py

then open the printed URL (``.serve()`` opens a browser tab for you). Ctrl-C stops the server.
``gmat-czml serve examples/data/gmat-leo.oem --ground-track`` is the equivalent from the CLI.
"""

from __future__ import annotations

from pathlib import Path

from orbit_formats import read

from gmat_czml import to_czml

HERE = Path(__file__).parent
INPUT = HERE / "data" / "gmat-leo.oem"


def main() -> None:
    trajectory = read(INPUT)
    document = to_czml(trajectory, ground_track=True)
    # Blocks until Ctrl-C; opens http://127.0.0.1:8080/ in a browser by default.
    document.serve(port=8080)


if __name__ == "__main__":
    main()
