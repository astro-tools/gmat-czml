"""Tolerance-bounded decimation.

Drops samples a client can interpolate back within a stated geometric error bound, keeping the
document small enough to load quickly and to fit an attachment. Configurable tolerance and payload
budget, on by default.
"""

from __future__ import annotations
