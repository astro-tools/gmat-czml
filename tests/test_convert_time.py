"""Tests for time-scale conversion and clock synthesis (``gmat_czml.convert.time``).

The scale conversion is delegated to orbit-formats (already tested there), so these pin the
gmat-czml layer: that the delegation is wired with the right scales, that UTC times are formatted
the way CZML and czml3 expect, that the synthesized clock spans the UTC union exactly with a
playback-derived multiplier, and that epoch-relative sample times round-trip.

Known offsets are asserted against a safely-past epoch (2024-06-01), where TAI-UTC=37 s,
TT-UTC=69.184 s and GPS-UTC=18 s are settled constants; TDB and UT1 (sub-ms periodic / sub-second
IERS) are checked with tolerances.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest
from czml3.types import TimeInterval

from gmat_czml.convert.time import (
    epoch_relative,
    format_iso,
    synthesize_clock,
    to_utc,
    utc_span,
)
from gmat_czml.schema import CanonicalInput, validate


def _input(
    *,
    time_scale: str = "UTC",
    start: str = "2024-06-01T00:00:00",
    periods: int = 3,
    object_name: str = "Sat",
) -> CanonicalInput:
    """A validated single-object input at the given time scale and span."""
    n = periods
    df = pd.DataFrame(
        {
            "Epoch": pd.date_range(start, periods=n, freq="600s"),
            "X": np.linspace(7000.0, 7001.0, n),
            "Y": np.linspace(0.0, 1.0, n),
            "Z": np.linspace(0.0, 2.0, n),
        }
    )
    df.attrs.update(
        {
            "object_name": object_name,
            "central_body": "Earth",
            "coordinate_system": "EME2000",
            "time_scale": time_scale,
        }
    )
    return validate(df)


def _clock_dict(clock: object) -> dict[str, object]:
    """The synthesized clock as parsed JSON."""
    parsed: dict[str, object] = json.loads(clock.dumps())  # type: ignore[attr-defined]
    return parsed


# --- to_utc -------------------------------------------------------------------------------


def test_to_utc_is_identity_for_utc() -> None:
    epochs = np.array(["2024-06-01T00:00:00", "2024-06-01T00:10:00"], dtype="datetime64[ns]")
    result = to_utc(epochs, "UTC")
    np.testing.assert_array_equal(result, epochs)
    assert result.dtype == np.dtype("datetime64[ns]")


def test_to_utc_known_constant_offsets() -> None:
    base = np.array(["2024-06-01T00:00:00"], dtype="datetime64[ns]")
    assert to_utc(base, "TAI")[0] == np.datetime64("2024-05-31T23:59:23", "ns")
    assert to_utc(base, "TT")[0] == np.datetime64("2024-05-31T23:58:50.816", "ns")
    assert to_utc(base, "GPS")[0] == np.datetime64("2024-05-31T23:59:42", "ns")


def test_to_utc_tdb_is_close_to_tt() -> None:
    base = np.array(["2024-06-01T00:00:00"], dtype="datetime64[ns]")
    delta_ms = abs((to_utc(base, "TDB")[0] - to_utc(base, "TT")[0]) / np.timedelta64(1, "ms"))
    assert delta_ms < 2.0  # TDB - TT is a sub-2 ms periodic term


def test_to_utc_ut1_is_within_a_second() -> None:
    base = np.array(["2024-06-01T00:00:00"], dtype="datetime64[ns]")
    delta_s = abs((to_utc(base, "UT1")[0] - base[0]) / np.timedelta64(1, "s"))
    assert delta_s < 1.0  # |UT1 - UTC| < 0.9 s by definition


def test_to_utc_preserves_array_shape() -> None:
    epochs = np.array(["2024-06-01T00:00:00", "2024-06-01T00:10:00"], dtype="datetime64[ns]")
    converted = to_utc(epochs, "TAI")
    assert converted.shape == epochs.shape


def test_to_utc_rejects_an_unknown_scale() -> None:
    base = np.array(["2024-06-01T00:00:00"], dtype="datetime64[ns]")
    with pytest.raises(ValueError):
        to_utc(base, "BOGUS")


# --- format_iso ---------------------------------------------------------------------------


def test_format_iso_is_microsecond_z() -> None:
    assert format_iso(np.datetime64("2024-06-01T00:00:00", "ns")) == "2024-06-01T00:00:00.000000Z"


def test_format_iso_matches_czml3_rendering() -> None:
    moment = np.datetime64("2024-06-01T12:34:56.789000", "ns")
    aware = pd.Timestamp(moment).to_pydatetime().replace(tzinfo=dt.timezone.utc)
    czml_start = TimeInterval(start=aware, end=aware).dumps().strip('"').split("/")[0]
    assert format_iso(moment) == czml_start


# --- synthesize_clock ---------------------------------------------------------------------


def test_clock_spans_the_utc_interval_exactly() -> None:
    clock = _clock_dict(synthesize_clock([_input(periods=3)]))  # 00:00 .. 00:20
    assert clock["interval"] == "2024-06-01T00:00:00.000000Z/2024-06-01T00:20:00.000000Z"
    assert clock["currentTime"] == "2024-06-01T00:00:00.000000Z"


def test_clock_unions_across_inputs_and_converts_non_utc() -> None:
    utc_in = _input(time_scale="UTC", start="2024-06-01T00:10:00", periods=2)  # 00:10..00:20 UTC
    tai_in = _input(time_scale="TAI", start="2024-06-01T00:00:37", periods=2)  # -> 00:00..00:10 UTC
    clock = _clock_dict(synthesize_clock([utc_in, tai_in]))
    assert clock["interval"] == "2024-06-01T00:00:00.000000Z/2024-06-01T00:20:00.000000Z"


def test_multiplier_tracks_playback_seconds() -> None:
    inputs = [_input(periods=3)]  # 1200 s span
    assert _clock_dict(synthesize_clock(inputs, playback_seconds=60))["multiplier"] == 20
    assert _clock_dict(synthesize_clock(inputs, playback_seconds=120))["multiplier"] == 10
    assert _clock_dict(synthesize_clock(inputs, playback_seconds=1200))["multiplier"] == 1


def test_single_instant_span_floors_multiplier_at_one() -> None:
    assert _clock_dict(synthesize_clock([_input(periods=1)]))["multiplier"] == 1


def test_rejects_non_positive_playback_seconds() -> None:
    inputs = [_input()]
    with pytest.raises(ValueError):
        synthesize_clock(inputs, playback_seconds=0)
    with pytest.raises(ValueError):
        synthesize_clock(inputs, playback_seconds=-5)


# --- utc_span -----------------------------------------------------------------------------


def test_utc_span_converts_the_bounds_to_utc() -> None:
    start, end = utc_span(_input(time_scale="TAI", start="2024-06-01T00:00:37", periods=2))
    assert start == dt.datetime(2024, 6, 1, 0, 0, tzinfo=dt.timezone.utc)
    assert end == dt.datetime(2024, 6, 1, 0, 10, tzinfo=dt.timezone.utc)


# --- epoch_relative -----------------------------------------------------------------------


def test_epoch_relative_reference_and_offsets() -> None:
    epochs = np.array(
        ["2024-06-01T00:00:00", "2024-06-01T00:10:00", "2024-06-01T00:20:00"],
        dtype="datetime64[ns]",
    )
    reference, offsets = epoch_relative(epochs)
    assert reference == "2024-06-01T00:00:00.000000Z"
    np.testing.assert_allclose(offsets, [0.0, 600.0, 1200.0])


def test_epoch_relative_round_trips_to_absolute_times() -> None:
    epochs = np.array(
        ["2024-06-01T00:00:00.250000", "2024-06-01T00:05:00", "2024-06-01T00:09:59.750000"],
        dtype="datetime64[ns]",
    )
    reference, offsets = epoch_relative(epochs)
    ref = np.datetime64(reference[:-1], "ns")  # drop the trailing 'Z'
    reconstructed = ref + (offsets * 1e9).round().astype("int64").astype("timedelta64[ns]")
    np.testing.assert_array_equal(reconstructed, epochs)
