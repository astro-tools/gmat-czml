"""State ephemeris to a CZML orbit path.

Emits the position as a sampled cartesian property (kilometres converted to metres), a path with
lead / trail, a billboard / point, and a label, carrying the source's interpolation algorithm and
degree onto the CZML. Handles multiple objects and multi-segment ephemerides.
"""

from __future__ import annotations
