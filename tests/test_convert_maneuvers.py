"""Tests for the maneuver converter (``gmat_czml.convert.maneuvers``).

These pin the layer this module owns: a producer's maneuvers become markers on the orbit. An
impulsive burn is a point + label whose position is *interpolated* from the trajectory at the burn
epoch (so it lands on the path) and whose ``availability`` runs from that epoch to the document end.
A finite burn is two entities — an arc tracing the orbit over the burn span, then a companion
point + label marker — both available only over the burn span.

The placement checks read the emitted cartesian straight back against a hand-built **linear**
ephemeris (position X in kilometres equals the elapsed seconds), so the interpolated marker is an
independent hand computation: a burn ``s`` seconds in lands at ``s * 1000`` metres. The guards (a
burn outside the trajectory span) and the time-scale handling (the epoch read in the trajectory's
declared scale, the span carried onto the UTC timeline) are pinned too.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray
from orbit_formats import Maneuver

from gmat_czml.convert.maneuvers import maneuver_packets
from gmat_czml.errors import InvalidUnitsError, ManeuverOutsideTrajectoryError
from gmat_czml.schema import CanonicalInput, validate
from gmat_czml.styles import LabelStyle, LineStyle, ManeuverStyle, PointStyle, Style

# The linear ephemeris epoch base. Every fixture starts here; a maneuver ``s`` seconds in sits at
# the ``s``-th kilometre of the X axis, so an interpolated marker is trivially hand-checkable.
_BASE = "2026-03-01T00:00:00"


def _item(
    *,
    time_scale: str = "UTC",
    frame: str = "EME2000",
    length: str = "km",
    count: int = 11,
    step: float = 60.0,
) -> CanonicalInput:
    """A validated linear single-object trajectory: ``X = elapsed_seconds`` (in ``length``), Y=Z=0.

    ``count`` samples ``step`` seconds apart from :data:`_BASE`, tagged ``frame`` / ``time_scale``.
    A maneuver ``s`` seconds in interpolates to ``X = s`` in the declared length unit.
    """
    seconds = np.arange(count, dtype=np.float64) * step
    positions = np.column_stack([seconds, np.zeros(count), np.zeros(count)]).astype(np.float64)
    epochs = np.array(
        [np.datetime64(_BASE) + np.timedelta64(round(s * 1000), "ms") for s in seconds],
        dtype="datetime64[ns]",
    )
    df = pd.DataFrame(
        {"Epoch": epochs, "X": positions[:, 0], "Y": positions[:, 1], "Z": positions[:, 2]}
    )
    df.attrs.update(
        {
            "object_name": "Sat",
            "central_body": "Earth",
            "coordinate_system": frame,
            "time_scale": time_scale,
            "units": {"length": length, "speed": "km/s"},
        }
    )
    return validate(df)


def _impulsive(
    at: str = "2026-03-01T00:01:30", *, dv: tuple[float, float, float] | None = (0.01, 0.0, 0.0)
) -> Maneuver:
    """An impulsive (zero-duration) maneuver at ``at`` with optional Δv (km/s)."""
    delta_v = None if dv is None else np.array(dv, dtype=np.float64)
    return Maneuver(
        epoch_ignition=np.datetime64(at), ref_frame="RTN", duration=0.0, delta_v=delta_v
    )


def _finite(
    at: str = "2026-03-01T00:05:00",
    *,
    duration: float = 120.0,
    dv: tuple[float, float, float] | None = (0.0, 0.005, 0.0),
) -> Maneuver:
    """A finite maneuver at ``at`` lasting ``duration`` seconds with optional Δv (km/s)."""
    delta_v = None if dv is None else np.array(dv, dtype=np.float64)
    return Maneuver(
        epoch_ignition=np.datetime64(at), ref_frame="RTN", duration=duration, delta_v=delta_v
    )


def _packets(
    maneuvers: Sequence[Maneuver], *, item: CanonicalInput | None = None, entity_id: str = "Sat"
) -> list[Any]:
    """The maneuver packets for ``maneuvers`` against a default linear trajectory."""
    return maneuver_packets(maneuvers, item or _item(), entity_id, Style())


def _packet(packets: list[Any], packet_id: str) -> dict[str, Any]:
    """The serialized packet with the given id (so assertions read emitted JSON, not the model)."""
    for packet in packets:
        parsed: dict[str, Any] = json.loads(packet.dumps())
        if parsed["id"] == packet_id:
            return parsed
    raise AssertionError(f"no packet with id {packet_id!r} in {[p.dumps() for p in packets]}")


def _ids(packets: list[Any]) -> list[str]:
    return [json.loads(packet.dumps())["id"] for packet in packets]


def _cartesian(values: Any) -> NDArray[np.float64]:
    return np.array(values, dtype=np.float64)


# --- impulsive markers --------------------------------------------------------------------


def test_impulsive_is_a_single_point_and_label_packet() -> None:
    packets = _packets([_impulsive()])
    assert _ids(packets) == ["Sat/maneuver/0"]
    marker = _packet(packets, "Sat/maneuver/0")
    assert marker["point"]["show"] is True
    assert marker["point"]["color"]["rgba"] == [255, 140, 0, 255]  # the orange maneuver layer
    assert marker["label"]["text"] == "Δv 0.010 km/s"


def test_impulsive_position_is_interpolated_onto_the_orbit_in_metres() -> None:
    # A burn 90 s in sits at the 90th kilometre on the linear orbit -> 90_000 m, not the raw 90.
    marker = _packet(_packets([_impulsive("2026-03-01T00:01:30")]), "Sat/maneuver/0")
    assert marker["position"]["cartesian"] == [90_000.0, 0.0, 0.0]


def test_impulsive_availability_runs_from_the_epoch_to_the_trajectory_end() -> None:
    marker = _packet(_packets([_impulsive("2026-03-01T00:01:30")]), "Sat/maneuver/0")
    # span is 00:00:00 .. 00:10:00 (11 samples, 60 s apart): the pin appears at the burn and stays.
    assert marker["availability"] == "2026-03-01T00:01:30.000000Z/2026-03-01T00:10:00.000000Z"


def test_impulsive_label_without_delta_v_is_generic() -> None:
    marker = _packet(_packets([_impulsive(dv=None)]), "Sat/maneuver/0")
    assert marker["label"]["text"] == "maneuver"


def test_impulsive_position_carries_the_trajectory_reference_frame() -> None:
    inertial = _packet(_packets([_impulsive()]), "Sat/maneuver/0")
    assert inertial["position"]["referenceFrame"] == "INERTIAL"
    fixed_item = _item(frame="EarthFixed")  # GMAT's Earth-fixed spelling -> ITRF -> FIXED
    fixed = _packet(_packets([_impulsive()], item=fixed_item), "Sat/maneuver/0")
    assert fixed["position"]["referenceFrame"] == "FIXED"


def test_marker_position_is_metres_not_kilometres() -> None:
    # The meta-test: a 90 km interpolated component must come out as 90_000 m, never the raw 90.
    marker = _packet(_packets([_impulsive("2026-03-01T00:01:30")]), "Sat/maneuver/0")
    assert marker["position"]["cartesian"][0] == 90_000.0
    assert marker["position"]["cartesian"][0] != 90.0


# --- finite burns: arc + marker -----------------------------------------------------------


def test_finite_emits_an_arc_then_a_companion_marker() -> None:
    assert _ids(_packets([_finite()])) == ["Sat/maneuver/0", "Sat/maneuver/0/marker"]


def test_finite_arc_spans_the_burn_along_the_orbit() -> None:
    # Ignition 00:05:00 (300 s) .. cut-off 00:07:00 (420 s): interpolated endpoints bracket the one
    # interior sample at 360 s, so the arc is [300 km, 360 km, 420 km] on the X axis, in metres.
    arc = _packet(_packets([_finite()]), "Sat/maneuver/0")
    positions = arc["polyline"]["positions"]
    assert positions["referenceFrame"] == "INERTIAL"
    np.testing.assert_array_equal(
        _cartesian(positions["cartesian"]),
        _cartesian([300_000.0, 0.0, 0.0, 360_000.0, 0.0, 0.0, 420_000.0, 0.0, 0.0]),
    )
    assert arc["polyline"]["arcType"] == "NONE"  # straight chords in inertial space, not draped
    assert arc["polyline"]["width"] == 3.0
    assert arc["polyline"]["material"]["solidColor"]["color"]["rgba"] == [255, 140, 0, 255]


def test_finite_arc_shorter_than_the_sample_step_is_two_endpoints() -> None:
    # A burn wholly between two samples (70 s .. 90 s, samples at 60 s and 120 s) has no interior
    # point: the arc is just its two interpolated endpoints -> 6 cartesian components.
    arc = _packet(_packets([_finite("2026-03-01T00:01:10", duration=20.0)]), "Sat/maneuver/0")
    assert _cartesian(arc["polyline"]["positions"]["cartesian"]).tolist() == [
        70_000.0,
        0.0,
        0.0,
        90_000.0,
        0.0,
        0.0,
    ]


def test_finite_marker_position_is_at_the_ignition_point() -> None:
    marker = _packet(_packets([_finite()]), "Sat/maneuver/0/marker")
    assert marker["position"]["cartesian"] == [300_000.0, 0.0, 0.0]
    assert marker["point"]["color"]["rgba"] == [255, 140, 0, 255]


def test_finite_arc_and_marker_are_available_over_the_burn_span() -> None:
    packets = _packets([_finite()])
    span = "2026-03-01T00:05:00.000000Z/2026-03-01T00:07:00.000000Z"
    assert _packet(packets, "Sat/maneuver/0")["availability"] == span
    assert _packet(packets, "Sat/maneuver/0/marker")["availability"] == span


def test_finite_label_shows_delta_v_and_duration() -> None:
    marker = _packet(_packets([_finite()]), "Sat/maneuver/0/marker")
    assert marker["label"]["text"] == "Δv 0.005 km/s over 120 s"


def test_finite_label_without_delta_v_states_the_duration() -> None:
    marker = _packet(_packets([_finite(dv=None)]), "Sat/maneuver/0/marker")
    assert marker["label"]["text"] == "burn 120 s"


# --- time scale ---------------------------------------------------------------------------


def test_maneuver_epoch_is_read_in_the_trajectory_time_scale() -> None:
    # The maneuver epoch carries no scale, so it is read in the trajectory's: a GPS trajectory's
    # 00:05:00 burn lands at 00:04:42 UTC (GPS is 18 s ahead) on the document timeline.
    gps = _item(time_scale="GPS")
    marker = _packet(_packets([_impulsive("2026-03-01T00:05:00")], item=gps), "Sat/maneuver/0")
    assert marker["availability"].startswith("2026-03-01T00:04:42.000000Z/")


# --- guards -------------------------------------------------------------------------------


def test_burn_before_the_trajectory_start_is_rejected() -> None:
    with pytest.raises(ManeuverOutsideTrajectoryError):
        _packets([_impulsive("2026-02-28T23:59:00")])


def test_burn_after_the_trajectory_end_is_rejected() -> None:
    with pytest.raises(ManeuverOutsideTrajectoryError):
        _packets([_impulsive("2026-03-01T00:11:00")])


def test_finite_burn_whose_cutoff_runs_past_the_end_is_rejected() -> None:
    # Ignition 00:09:30 (within the 00:00..00:10 span) but +120 s cut-off overruns the last state.
    with pytest.raises(ManeuverOutsideTrajectoryError):
        _packets([_finite("2026-03-01T00:09:30", duration=120.0)])


def test_outside_trajectory_error_carries_the_epoch_and_span() -> None:
    with pytest.raises(ManeuverOutsideTrajectoryError) as exc:
        _packets([_impulsive("2026-03-01T00:11:00")])
    assert isinstance(exc.value.epoch, datetime)
    assert exc.value.epoch == datetime(2026, 3, 1, 0, 11, 0, tzinfo=timezone.utc)
    start, end = exc.value.span
    assert (start, end) == (
        datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 0, 10, 0, tzinfo=timezone.utc),
    )


def test_unsupported_length_unit_is_rejected() -> None:
    with pytest.raises(InvalidUnitsError):
        _packets([_impulsive()], item=_item(length="AU"))


# --- ordering and degenerate inputs -------------------------------------------------------


def test_maneuvers_are_numbered_in_order() -> None:
    ids = _ids(
        _packets([_impulsive("2026-03-01T00:01:00"), _finite(), _impulsive("2026-03-01T00:09:00")])
    )
    assert ids == ["Sat/maneuver/0", "Sat/maneuver/1", "Sat/maneuver/1/marker", "Sat/maneuver/2"]


def test_back_to_back_finite_burns_get_distinct_ids_and_abutting_availability() -> None:
    # Two finite burns where the first's cut-off is the second's ignition (00:01:00 + 60 s ->
    # 00:02:00). Each burn keeps its own index-namespaced ids (no collision between the abutting
    # burns) and the first burn's availability ends exactly where the second's begins, so
    # back-to-back burns annotate a contiguous, non-overlapping span.
    packets = _packets(
        [
            _finite("2026-03-01T00:01:00", duration=60.0, dv=None),
            _finite("2026-03-01T00:02:00", duration=60.0, dv=None),
        ]
    )
    assert _ids(packets) == [
        "Sat/maneuver/0",
        "Sat/maneuver/0/marker",
        "Sat/maneuver/1",
        "Sat/maneuver/1/marker",
    ]
    first = _packet(packets, "Sat/maneuver/0")["availability"]
    second = _packet(packets, "Sat/maneuver/1")["availability"]
    assert first.endswith("/2026-03-01T00:02:00.000000Z")
    assert second.startswith("2026-03-01T00:02:00.000000Z/")


def test_no_maneuvers_yields_no_packets() -> None:
    assert _packets([]) == []


# --- custom styling -----------------------------------------------------------------------


def test_custom_maneuver_style_drives_marker_arc_and_label() -> None:
    style = Style(
        maneuver=ManeuverStyle(
            marker=PointStyle(color=(10, 20, 30, 255), pixel_size=5.0),
            label=LabelStyle(color=(1, 2, 3, 255), font="20pt Arial"),
            arc=LineStyle(color=(40, 50, 60, 255), width=8.0),
        )
    )
    packets = maneuver_packets([_finite()], _item(), "Sat", style)
    arc = _packet(packets, "Sat/maneuver/0")
    marker = _packet(packets, "Sat/maneuver/0/marker")
    assert arc["polyline"]["width"] == 8.0
    assert arc["polyline"]["material"]["solidColor"]["color"]["rgba"] == [40, 50, 60, 255]
    assert marker["point"]["color"]["rgba"] == [10, 20, 30, 255]
    assert marker["point"]["pixelSize"] == 5.0
    assert marker["label"]["fillColor"]["rgba"] == [1, 2, 3, 255]
    assert marker["label"]["font"] == "20pt Arial"
