"""The canonical input boundary.

gmat-czml consumes the canonical state-series schema owned by the org's format-I/O library:
columns ``Epoch, X, Y, Z`` (with optional ``VX, VY, VZ``) and a metadata spine on
``DataFrame.attrs`` (``coordinate_system`` / ``central_body`` / ``time_scale`` / ``units`` /
``interpolation`` / ``interpolation_degree`` / ``object_name``). This module is the thin boundary
that validates a DataFrame (or an upstream canonical object, or a readable file) against that
contract and raises typed errors naming what is wrong.

The contract is specified in ``docs/design/decisions.md``. Implementation lands with the schema
work.
"""

from __future__ import annotations
