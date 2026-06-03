"""gmat-czml — convert canonical trajectories to CZML for browser-based Cesium visualization.

gmat-czml takes an already-computed trajectory in the canonical state-series form (the schema
the org's format-I/O library emits, and the schema a headless GMAT run produces) and turns it
into a CZML document a Cesium client can animate. It does not propagate or compute orbits — the
producer is the source of geometric truth.

This module is the public surface. The conversion internals live under
:mod:`gmat_czml.convert`. The input contract and the design decisions are recorded in
``docs/design/decisions.md``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
