"""Ground track as a geodetic polyline.

Projects the orbit to the sub-satellite point at each epoch (via the rotation in
:mod:`gmat_czml.convert.frames`) and emits it as a geodetic longitude / latitude / height
polyline, handling the antimeridian wrap.
"""

from __future__ import annotations
