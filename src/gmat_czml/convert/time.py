"""Time-scale conversion and clock synthesis.

Converts a producer's time scale to UTC (CZML epochs are UTC ISO-8601), synthesizes the document
clock from the ephemeris span, and emits epoch-relative sample times for compactness.

The scale conversion is delegated to orbit-formats' ``convert_time_scale`` (astropy-backed and
leap-second-correct across UTC / TAI / TT / TDB / GPS / UT1); gmat-czml ships no leap-second table
of its own. A UTC trajectory never loads astropy — only a genuinely non-UTC conversion does, and
then lazily and without network access.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np
import pandas as pd
from czml3.properties import Clock
from czml3.types import TimeInterval
from numpy.typing import NDArray
from orbit_formats.convert import convert_time_scale

from gmat_czml.schema import CanonicalInput

__all__ = ["epoch_relative", "format_iso", "synthesize_clock", "to_utc", "utc_span"]

_UTC = "UTC"

# The clock multiplier (simulated seconds per real second) defaults so the whole trajectory
# plays back in roughly this many seconds of wall-clock time; callers override it via the
# ``playback_seconds`` argument.
_DEFAULT_PLAYBACK_SECONDS = 60.0


def to_utc(
    epochs: NDArray[np.datetime64] | np.datetime64, time_scale: str
) -> NDArray[np.datetime64]:
    """Convert ``epochs`` from ``time_scale`` to UTC, leap-second-correct.

    Delegates to orbit-formats' ``convert_time_scale`` (UTC / TAI / TT / TDB / GPS / UT1). A UTC
    input returns unchanged and never loads astropy; any other scale loads it lazily. The result
    is a ``datetime64[ns]`` array of the same shape as ``epochs``.
    """
    return convert_time_scale(epochs, time_scale, _UTC)


def format_iso(epoch: np.datetime64) -> str:
    """Format a UTC ``datetime64`` as a CZML ISO-8601 string (microsecond precision, ``Z``).

    Matches czml3's own datetime rendering, so a hand-built epoch string and a czml3-serialized
    time stay byte-compatible within one document.
    """
    moment = pd.Timestamp(epoch).to_pydatetime()
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def utc_span(item: CanonicalInput) -> tuple[dt.datetime, dt.datetime]:
    """One trajectory's earliest and latest epoch in UTC, as timezone-aware datetimes."""
    utc = to_utc(item.ephemeris.epochs, item.time_scale)
    return _as_datetime(utc.min()), _as_datetime(utc.max())


def synthesize_clock(
    inputs: Sequence[CanonicalInput], *, playback_seconds: float = _DEFAULT_PLAYBACK_SECONDS
) -> Clock:
    """Synthesize the document clock spanning the full trajectory, in UTC.

    The interval runs from the earliest to the latest epoch across every input — each converted
    from its own time scale to UTC — and the clock starts at the interval start. ``multiplier``
    (simulated seconds per real second) is chosen so the whole span plays back in roughly
    ``playback_seconds`` of wall-clock time, floored at ``1`` (a single-instant span yields ``1``).

    Raises :class:`ValueError` if ``playback_seconds`` is not positive.
    """
    if playback_seconds <= 0:
        raise ValueError(f"playback_seconds must be positive, got {playback_seconds!r}")
    spans = [utc_span(item) for item in inputs]
    start = min(lo for lo, _ in spans)
    end = max(hi for _, hi in spans)
    span_seconds = (end - start).total_seconds()
    multiplier = max(1, round(span_seconds / playback_seconds))
    return Clock(
        currentTime=start,
        multiplier=multiplier,
        interval=TimeInterval(start=start, end=end),
    )


def epoch_relative(utc_epochs: NDArray[np.datetime64]) -> tuple[str, NDArray[np.float64]]:
    """Express UTC epochs relative to a single reference epoch, for compact CZML sampling.

    Returns the reference epoch (the first sample) as a CZML ISO-8601 string and the per-sample
    offsets in seconds from it. A CZML sampled property pairs this ``epoch`` with the offsets, so
    the document carries one absolute timestamp instead of one per sample; ``reference + offset``
    recovers each absolute UTC epoch. ``utc_epochs`` must be non-empty (a validated trajectory is).
    """
    reference = utc_epochs[0]
    offsets = (utc_epochs - reference) / np.timedelta64(1, "s")
    return format_iso(reference), offsets.astype(np.float64)


def _as_datetime(epoch: np.datetime64) -> dt.datetime:
    """A ``datetime64`` epoch as a UTC-aware :class:`~datetime.datetime`."""
    return pd.Timestamp(epoch).to_pydatetime().replace(tzinfo=dt.timezone.utc)
