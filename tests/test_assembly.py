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
from orbit_formats import Attitude, Maneuver
from orbit_formats.canonical.metadata import Metadata

from gmat_czml import Contact, CzmlDocument, GroundStation, Style, to_czml
from gmat_czml.errors import (
    AmbiguousAttitudeTargetError,
    AmbiguousManeuverTargetError,
    DuplicateObjectNameError,
    MissingFrameError,
    SchemaError,
    UnknownContactTargetError,
    UnsupportedCentralBodyError,
)
from gmat_czml.schema import validate


def _conforming_df(
    *,
    object_name: str | None = "Sat",
    start: str = "2026-01-01",
    periods: int = 3,
    time_scale: str = "UTC",
    frame: str = "EME2000",
    central_body: str | None = "Earth",
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
    df.attrs.update({"coordinate_system": frame, "time_scale": time_scale})
    if central_body is not None:
        df.attrs["central_body"] = central_body
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


def test_clock_and_availability_are_utc_for_a_non_utc_input() -> None:
    # A TAI trajectory at 00:00:37 / 00:10:37 / 00:20:37 maps to 00:00 / 00:10 / 00:20 UTC
    # (TAI - UTC = 37 s), so both the clock interval and the entity availability come out in UTC.
    packets = to_czml(
        _conforming_df(time_scale="TAI", start="2024-06-01T00:00:37", periods=3)
    ).to_dict()
    expected = "2024-06-01T00:00:00.000000Z/2024-06-01T00:20:00.000000Z"
    assert packets[0]["clock"]["interval"] == expected
    assert packets[1]["availability"] == expected


def test_playback_seconds_is_forwarded_to_the_clock() -> None:
    df = _conforming_df(start="2024-06-01T00:00:00", periods=3)  # 1200 s span
    assert to_czml(df).to_dict()[0]["clock"]["multiplier"] == 20  # default ~60 s playback
    assert to_czml(df, playback_seconds=120).to_dict()[0]["clock"]["multiplier"] == 10


# --- the per-object entity packets --------------------------------------------------------


def test_entity_carries_identity_and_availability() -> None:
    entity = to_czml(_conforming_df(object_name="Sat")).to_dict()[1]
    assert entity["id"] == "Sat"
    assert entity["name"] == "Sat"
    start_s, end_s = entity["availability"].split("/")
    assert _parse_czml_time(start_s) == dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert _parse_czml_time(end_s) == dt.datetime(2026, 1, 1, 0, 20, tzinfo=dt.timezone.utc)


def test_entity_carries_the_orbit_path_geometry() -> None:
    # The ephemeris converter fills the geometry seam: the entity now carries the position
    # property, path, point, and label alongside its identity and availability.
    entity = to_czml(_conforming_df()).to_dict()[1]
    assert "position" in entity
    assert "path" in entity
    assert "point" in entity
    assert "label" in entity
    assert entity["position"]["referenceFrame"] == "INERTIAL"


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


# --- packet-id uniqueness (declared name vs positional fallback) --------------------------


def test_declared_name_colliding_with_positional_fallback_is_rejected() -> None:
    # A declared name equal to another object's positional fallback ("object-1" vs the id an
    # unnamed object at index 1 takes) would emit two packets sharing an id — which a Cesium client
    # silently merges into one entity — so it is rejected rather than emitted as a malformed scene.
    named = _conforming_df(object_name="object-1")  # at index 0 -> id "object-1"
    unnamed = _conforming_df(object_name=None)  # at index 1 -> fallback "object-1"
    with pytest.raises(DuplicateObjectNameError) as exc:
        to_czml([named, unnamed])
    assert exc.value.name == "object-1"


def test_fallback_collision_is_rejected_regardless_of_order() -> None:
    # The collision is symmetric: an unnamed object at index 0 ("object-0") and a later object
    # declared "object-0" collide just the same.
    unnamed = _conforming_df(object_name=None)  # at index 0 -> fallback "object-0"
    named = _conforming_df(object_name="object-0")  # at index 1 -> id "object-0"
    with pytest.raises(DuplicateObjectNameError) as exc:
        to_czml([unnamed, named])
    assert exc.value.name == "object-0"


# --- the single-sample edge case ----------------------------------------------------------


def test_single_sample_trajectory_yields_a_valid_one_entity_document() -> None:
    # A degenerate single-state "trajectory" still assembles to a preamble + one entity carrying a
    # single position sample, with a zero-length availability / clock span (a static instant).
    packets = to_czml(_conforming_df(periods=1)).to_dict()
    assert len(packets) == 2
    cartesian = packets[1]["position"]["cartesian"]
    assert len(cartesian) == 4  # one sample: [t, x, y, z]
    assert cartesian[0] == 0.0  # the single offset is the reference epoch itself
    start, end = packets[1]["availability"].split("/")
    assert start == end  # a single instant
    clock_start, clock_end = packets[0]["clock"]["interval"].split("/")
    assert clock_start == clock_end


# --- parameters ---------------------------------------------------------------------------


def test_accepts_style_and_empty_decorations() -> None:
    # style is applied (a single default for now); empty contacts / maneuvers lists and a None
    # attitude are no-ops. All must be accepted without changing the output.
    plain = to_czml(_conforming_df()).to_dict()
    decorated = to_czml(
        _conforming_df(),
        style=Style(),
        contacts=[],
        maneuvers=[],
        attitude=None,
    ).to_dict()
    assert decorated == plain


# --- contacts -----------------------------------------------------------------------------


def test_contacts_append_observer_and_link_packets() -> None:
    # A contact adds two packets after the object: the observer entity and the per-window link,
    # the link referencing the observer's and the satellite's position properties.
    contact = Contact(
        observer=GroundStation(name="GS1", latitude=40.0, longitude=-75.0, height=0.1),
        target="Sat",
        windows=[
            (
                dt.datetime(2026, 1, 1, 0, 5, tzinfo=dt.timezone.utc),
                dt.datetime(2026, 1, 1, 0, 15, tzinfo=dt.timezone.utc),
            )
        ],
    )
    packets = to_czml(_conforming_df(object_name="Sat"), contacts=[contact]).to_dict()
    assert [p["id"] for p in packets] == ["document", "Sat", "GS1", "GS1-to-Sat"]
    link = packets[3]
    assert link["polyline"]["positions"]["references"] == ["GS1#position", "Sat#position"]
    assert link["availability"] == ["2026-01-01T00:05:00.000000Z/2026-01-01T00:15:00.000000Z"]


def test_contact_targeting_a_missing_object_raises() -> None:
    contact = Contact(
        observer=GroundStation(name="GS1", latitude=0.0, longitude=0.0),
        target="NotHere",
        windows=[],
    )
    with pytest.raises(UnknownContactTargetError) as exc:
        to_czml(_conforming_df(object_name="Sat"), contacts=[contact])
    assert exc.value.target == "NotHere"


# --- maneuvers ----------------------------------------------------------------------------


def _maneuver(at: str, *, duration: float = 0.0) -> Maneuver:
    """A maneuver at ``at`` (within the _conforming_df 00:00..00:20 span) with a small Δv."""
    return Maneuver(
        epoch_ignition=np.datetime64(at),
        ref_frame="RTN",
        duration=duration,
        delta_v=np.array([0.01, 0.0, 0.0]),
    )


def test_impulsive_maneuver_appends_one_marker_packet() -> None:
    # An impulsive burn adds a single marker packet after the object, keyed off the entity id.
    packets = to_czml(
        _conforming_df(object_name="Sat"), maneuvers=[_maneuver("2026-01-01T00:05:00")]
    ).to_dict()
    assert [p["id"] for p in packets] == ["document", "Sat", "Sat/maneuver/0"]
    assert packets[2]["position"]["referenceFrame"] == "INERTIAL"
    assert packets[2]["point"]["color"]["rgba"] == [255, 140, 0, 255]


def test_finite_maneuver_appends_an_arc_and_a_marker_packet() -> None:
    packets = to_czml(
        _conforming_df(object_name="Sat"),
        maneuvers=[_maneuver("2026-01-01T00:10:00", duration=60.0)],
    ).to_dict()
    assert [p["id"] for p in packets] == [
        "document",
        "Sat",
        "Sat/maneuver/0",
        "Sat/maneuver/0/marker",
    ]
    assert "polyline" in packets[2]
    assert "label" in packets[3]


def test_maneuvers_on_a_multi_object_document_are_rejected() -> None:
    # A maneuver names no target craft, so it is ambiguous which of several objects it acts on.
    inputs = [_conforming_df(object_name="A"), _conforming_df(object_name="B")]
    with pytest.raises(AmbiguousManeuverTargetError) as exc:
        to_czml(inputs, maneuvers=[_maneuver("2026-01-01T00:05:00")])
    assert exc.value.count == 2


# --- attitude -----------------------------------------------------------------------------


def _attitude(frame_a: str = "EME2000") -> Attitude:
    """A short quaternion history within the _conforming_df 00:00..00:20 span (EME2000 -> body)."""
    return Attitude(
        metadata=Metadata(object_name="Sat", time_scale="UTC"),
        attitude_type="QUATERNION",
        epochs=np.array(
            ["2026-01-01T00:00:00", "2026-01-01T00:10:00", "2026-01-01T00:20:00"],
            dtype="datetime64[ns]",
        ),
        records=np.array(
            [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.087156, 0.996195], [0.0, 0.0, 0.173648, 0.984808]]
        ),
        frame_a=frame_a,
        frame_b="SC_BODY",
    )


def test_attitude_appends_one_orientation_packet() -> None:
    # An attitude adds a single child packet after the object: it references the object's position
    # and carries a sampled orientation plus the schematic body box.
    packets = to_czml(_conforming_df(object_name="Sat"), attitude=_attitude()).to_dict()
    assert [p["id"] for p in packets] == ["document", "Sat", "Sat/attitude"]
    attitude_packet = packets[2]
    assert attitude_packet["position"] == {"reference": "Sat#position"}
    assert attitude_packet["orientation"]["interpolationAlgorithm"] == "LINEAR"
    assert "box" in attitude_packet


def test_attitude_on_a_multi_object_document_is_rejected() -> None:
    # An attitude orients one object, so with several objects it is ambiguous which craft it belongs
    # to.
    inputs = [_conforming_df(object_name="A"), _conforming_df(object_name="B")]
    with pytest.raises(AmbiguousAttitudeTargetError) as exc:
        to_czml(inputs, attitude=_attitude())
    assert exc.value.count == 2


# --- the opt-in ground track --------------------------------------------------------------


def test_ground_track_is_off_by_default() -> None:
    # No ground_track flag: the document is preamble + the single entity, no polyline packet.
    packets = to_czml(_conforming_df()).to_dict()
    assert len(packets) == 2
    assert all("polyline" not in packet for packet in packets)


def test_ground_track_opt_in_appends_a_polyline_packet() -> None:
    # ground_track=True adds the sub-satellite polyline as its own packet keyed off the entity id.
    # A fixed (ITRF) source keeps the rotation an identity, so the track is the short non-crossing
    # segment of this near-straight arc — one packet.
    packets = to_czml(_conforming_df(frame="ITRF"), ground_track=True).to_dict()
    assert len(packets) == 3
    track = packets[2]
    assert track["id"] == "Sat/groundtrack"
    assert "polyline" in track
    assert track["polyline"]["positions"]["cartographicDegrees"]


def test_antimeridian_track_becomes_numbered_segment_packets() -> None:
    # A fixed equatorial track that wraps across +180 splits into two polyline packets, numbered
    # off the entity id so each segment is addressable.
    radius = 6378.137 + 500.0
    radians = np.deg2rad([170.0, 175.0, -175.0, -170.0])
    df = pd.DataFrame(
        {
            "Epoch": pd.date_range("2024-06-01", periods=4, freq="600s"),
            "X": radius * np.cos(radians),
            "Y": radius * np.sin(radians),
            "Z": np.zeros(4),
        }
    )
    df.attrs.update(
        {
            "object_name": "Sat",
            "central_body": "Earth",
            "coordinate_system": "ITRF",
            "time_scale": "UTC",
        }
    )
    packets = to_czml(df, ground_track=True).to_dict()
    track_packets = [p for p in packets if "polyline" in p]
    assert [p["id"] for p in track_packets] == ["Sat/groundtrack/0", "Sat/groundtrack/1"]


def test_ground_track_for_a_non_earth_body_raises() -> None:
    with pytest.raises(UnsupportedCentralBodyError):
        to_czml(_conforming_df(frame="ITRF", central_body="Moon"), ground_track=True)


# --- error propagation --------------------------------------------------------------------


def test_propagates_typed_schema_errors() -> None:
    df = _conforming_df()
    del df.attrs["coordinate_system"]
    with pytest.raises(MissingFrameError):
        to_czml(df)
    with pytest.raises(SchemaError):  # the typed family is catchable as one
        to_czml(df)
