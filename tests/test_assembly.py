"""Tests for the public assembly entry point (``gmat_czml.to_czml``).

These pin the skeleton's contract: a validated input becomes a complete, schema-valid document —
a ``document`` preamble carrying a clock that spans the trajectory, plus one identity packet per
object — produced in memory. Geometry (position / path / billboard / label) belongs to the
ephemeris converter and is deliberately absent here; the test that no packet carries a position
guards that seam.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from gmat_czml import CzmlDocument, Style, to_czml
from gmat_czml.errors import MissingFrameError, SchemaError
from gmat_czml.schema import validate


def _conforming_df(
    *,
    object_name: str | None = "Sat",
    start: str = "2026-01-01",
    periods: int = 3,
) -> pd.DataFrame:
    """A conforming single-object canonical DataFrame; tweak per test via the keyword args."""
    n = periods
    data: dict[str, object] = {
        "Epoch": pd.date_range(start, periods=n, freq="600s"),
        "X": np.linspace(7000.0, 7001.0, n),
        "Y": np.linspace(0.0, 1.0, n),
        "Z": np.linspace(0.0, 2.0, n),
    }
    df = pd.DataFrame(data)
    df.attrs.update(
        {
            "central_body": "Earth",
            "coordinate_system": "EME2000",
            "time_scale": "UTC",
        }
    )
    if object_name is not None:
        df.attrs["object_name"] = object_name
    return df


def _parse_czml_time(value: str) -> dt.datetime:
    """Parse a CZML ISO-8601 ``...Z`` timestamp into a UTC-aware datetime (py3.10-compatible)."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- the wrapper / overall shape ----------------------------------------------------------


def test_returns_a_czml_document() -> None:
    assert isinstance(to_czml(_conforming_df()), CzmlDocument)


def test_document_is_a_schema_valid_array_with_one_packet_per_object() -> None:
    packets = to_czml(_conforming_df()).to_dict()
    assert isinstance(packets, list)
    assert len(packets) == 2  # preamble + one object
    assert packets[0]["id"] == "document"
    assert packets[0]["version"] == "1.0"


# --- the synthesized clock ----------------------------------------------------------------


def test_preamble_carries_a_clock_spanning_the_trajectory() -> None:
    clock = to_czml(_conforming_df()).to_dict()[0]["clock"]
    start_s, end_s = clock["interval"].split("/")
    assert _parse_czml_time(start_s) == dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert _parse_czml_time(end_s) == dt.datetime(2026, 1, 1, 0, 20, tzinfo=dt.timezone.utc)
    assert _parse_czml_time(clock["currentTime"]) == _parse_czml_time(start_s)


def test_clock_spans_the_union_across_multiple_objects() -> None:
    first = _conforming_df(object_name="A", start="2026-01-01 00:00", periods=3)  # 00:00-00:20
    second = _conforming_df(object_name="B", start="2026-01-01 00:10", periods=4)  # 00:10-00:40
    clock = to_czml([first, second]).to_dict()[0]["clock"]
    start_s, end_s = clock["interval"].split("/")
    assert _parse_czml_time(start_s) == dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
    assert _parse_czml_time(end_s) == dt.datetime(2026, 1, 1, 0, 40, tzinfo=dt.timezone.utc)


# --- the per-object entity packets --------------------------------------------------------


def test_entity_carries_identity_and_availability() -> None:
    entity = to_czml(_conforming_df(object_name="Sat")).to_dict()[1]
    assert entity["id"] == "Sat"
    assert entity["name"] == "Sat"
    start_s, end_s = entity["availability"].split("/")
    assert _parse_czml_time(start_s) == dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert _parse_czml_time(end_s) == dt.datetime(2026, 1, 1, 0, 20, tzinfo=dt.timezone.utc)


def test_entity_carries_no_geometry_yet() -> None:
    # The position property and the rest of the geometry belong to the ephemeris converter; the
    # skeleton emits identity only. Guard that seam so geometry does not leak in here.
    entity = to_czml(_conforming_df()).to_dict()[1]
    assert "position" not in entity
    assert "path" not in entity
    assert "billboard" not in entity
    assert "point" not in entity
    assert "label" not in entity


def test_unnamed_object_gets_a_positional_id_and_no_name() -> None:
    entity = to_czml(_conforming_df(object_name=None)).to_dict()[1]
    assert entity["id"] == "object-0"
    assert "name" not in entity


def test_multiple_objects_get_distinct_packets() -> None:
    packets = to_czml([_conforming_df(object_name="A"), _conforming_df(object_name="B")]).to_dict()
    assert len(packets) == 3
    assert [p["id"] for p in packets[1:]] == ["A", "B"]


def test_accepts_an_orbit_formats_ephemeris() -> None:
    ephemeris = validate(_conforming_df(object_name="FromEph")).ephemeris
    packets = to_czml(ephemeris).to_dict()
    assert len(packets) == 2
    assert packets[1]["id"] == "FromEph"


# --- parameters ---------------------------------------------------------------------------


def test_accepts_style_and_the_deferred_parameters() -> None:
    # style is a real v0.1 parameter; contacts / maneuvers / attitude are accepted-but-deferred.
    # All four must be accepted without changing the (geometry-free) skeleton output.
    plain = to_czml(_conforming_df()).to_dict()
    decorated = to_czml(
        _conforming_df(),
        style=Style(),
        contacts=[],
        maneuvers=[],
        attitude=[],
    ).to_dict()
    assert decorated == plain


# --- error propagation --------------------------------------------------------------------


def test_propagates_typed_schema_errors() -> None:
    df = _conforming_df()
    del df.attrs["coordinate_system"]
    with pytest.raises(MissingFrameError):
        to_czml(df)
    with pytest.raises(SchemaError):  # the typed family is catchable as one
        to_czml(df)
