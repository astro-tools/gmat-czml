"""Reference-frame mapping and the ground-track rotation.

Maps a source reference frame onto a CZML reference frame (inertial frames to ``INERTIAL``,
Earth-fixed to ``FIXED``), reusing the upstream frame-alias table. The inertial to Earth-fixed to
geodetic rotation the ground track needs is delegated to the format-I/O library's astropy-backed
rotation and its WGS84 geodetic helper, at visualization tolerance.
"""

from __future__ import annotations
