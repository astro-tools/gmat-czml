"""Time-scale conversion and clock synthesis.

Converts a producer's time scale to UTC (CZML epochs are UTC ISO-8601), synthesizes the document
clock from the ephemeris span, and emits epoch-relative sample times for compactness.
"""

from __future__ import annotations
