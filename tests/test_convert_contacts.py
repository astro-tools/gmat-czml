"""Tests for the contact converter (``gmat_czml.convert.contacts``).

These pin the layer this module owns: a producer's contact records become an observer entity placed
at its geodetic position (height scaled km -> metres) plus a per-contact observer -> satellite link
whose endpoints *reference* the two entities' position properties and whose ``availability`` is the
access windows, one CZML interval each. They also pin the guards — an unknown target, an observer
name colliding with an object id, one observer placed two ways, and a duplicated contact — and the
edge cases (no windows, observer reuse across targets).

The known-placement checks read the observer ``cartographicDegrees`` straight back: it is the input
longitude / latitude with height in metres, an independent hand computation needing no projection.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from gmat_czml.convert.contacts import Contact, GroundStation, contact_packets
from gmat_czml.errors import ContactEntityCollisionError, UnknownContactTargetError
from gmat_czml.styles import ContactStyle, LabelStyle, LineStyle, PointStyle, Style


def _window(
    start: tuple[int, int], end: tuple[int, int], *, tz: dt.tzinfo | None = dt.timezone.utc
) -> tuple[dt.datetime, dt.datetime]:
    """A ``(start, end)`` window on 2026-03-01 at the given ``(hour, minute)`` pairs."""
    return (
        dt.datetime(2026, 3, 1, *start, tzinfo=tz),
        dt.datetime(2026, 3, 1, *end, tzinfo=tz),
    )


def _contact(
    *,
    observer: GroundStation | None = None,
    target: str = "Sat",
    windows: list[tuple[dt.datetime, dt.datetime]] | None = None,
) -> Contact:
    """A single contact; tweak per test via the keyword args."""
    station = observer or GroundStation(name="GS1", latitude=40.0, longitude=-75.0, height=0.1)
    passes = windows if windows is not None else [_window((0, 10), (0, 20))]
    return Contact(observer=station, target=target, windows=passes)


def _packet(packets: list[Any], packet_id: str) -> dict[str, Any]:
    """The serialized packet with the given id (so assertions read the emitted JSON, not model)."""
    for packet in packets:
        parsed: dict[str, Any] = json.loads(packet.dumps())
        if parsed["id"] == packet_id:
            return parsed
    raise AssertionError(f"no packet with id {packet_id!r} in {[p.dumps() for p in packets]}")


def _ids(packets: list[Any]) -> list[str]:
    return [json.loads(packet.dumps())["id"] for packet in packets]


# --- observer placement -------------------------------------------------------------------


def test_observer_is_placed_at_its_geodetic_position() -> None:
    packets = contact_packets([_contact()], {"Sat"}, Style())
    observer = _packet(packets, "GS1")
    assert observer["name"] == "GS1"
    # cartographicDegrees order is [longitude, latitude, height_m].
    assert observer["position"]["cartographicDegrees"] == [-75.0, 40.0, 100.0]


def test_observer_height_is_metres_not_kilometres() -> None:
    # A 2 km station altitude must come out as 2000 m, never the raw 2.
    station = GroundStation(name="High", latitude=0.0, longitude=0.0, height=2.0)
    observer = _packet(contact_packets([_contact(observer=station)], {"Sat"}, Style()), "High")
    assert observer["position"]["cartographicDegrees"][2] == 2000.0


def test_observer_carries_a_point_and_a_label() -> None:
    observer = _packet(contact_packets([_contact()], {"Sat"}, Style()), "GS1")
    assert observer["point"]["show"] is True
    assert observer["point"]["color"]["rgba"] == [0, 255, 255, 255]
    assert observer["label"]["text"] == "GS1"


def test_custom_contact_style_drives_observer_and_link() -> None:
    style = Style(
        contact=ContactStyle(
            observer=PointStyle(color=(10, 20, 30, 255), pixel_size=5.0),
            label=LabelStyle(color=(1, 2, 3, 255), font="20pt Arial"),
            link=LineStyle(color=(40, 50, 60, 255), width=8.0),
        )
    )
    packets = contact_packets([_contact()], {"Sat"}, style)
    observer = _packet(packets, "GS1")
    link = _packet(packets, "GS1-to-Sat")
    assert observer["point"]["color"]["rgba"] == [10, 20, 30, 255]
    assert observer["point"]["pixelSize"] == 5.0
    assert observer["label"]["fillColor"]["rgba"] == [1, 2, 3, 255]
    assert observer["label"]["font"] == "20pt Arial"
    assert link["polyline"]["width"] == 8.0
    assert link["polyline"]["material"]["solidColor"]["color"]["rgba"] == [40, 50, 60, 255]


# --- the per-window link ------------------------------------------------------------------


def test_link_references_the_observer_and_target_positions() -> None:
    link = _packet(contact_packets([_contact()], {"Sat"}, Style()), "GS1-to-Sat")
    assert link["polyline"]["positions"]["references"] == ["GS1#position", "Sat#position"]


def test_link_is_available_only_during_each_window() -> None:
    windows = [_window((0, 10), (0, 20)), _window((1, 0), (1, 10))]
    link = _packet(contact_packets([_contact(windows=windows)], {"Sat"}, Style()), "GS1-to-Sat")
    assert link["availability"] == [
        "2026-03-01T00:10:00.000000Z/2026-03-01T00:20:00.000000Z",
        "2026-03-01T01:00:00.000000Z/2026-03-01T01:10:00.000000Z",
    ]


def test_naive_window_times_are_read_as_utc() -> None:
    # A naive datetime carries no zone; the converter reads it as UTC rather than guessing local.
    windows = [_window((0, 10), (0, 20), tz=None)]
    link = _packet(contact_packets([_contact(windows=windows)], {"Sat"}, Style()), "GS1-to-Sat")
    assert link["availability"] == ["2026-03-01T00:10:00.000000Z/2026-03-01T00:20:00.000000Z"]


def test_aware_window_times_are_converted_to_utc() -> None:
    # A +02:00 window at 02:10/02:20 local is 00:10/00:20 UTC.
    plus_two = dt.timezone(dt.timedelta(hours=2))
    windows = [_window((2, 10), (2, 20), tz=plus_two)]
    link = _packet(contact_packets([_contact(windows=windows)], {"Sat"}, Style()), "GS1-to-Sat")
    assert link["availability"] == ["2026-03-01T00:10:00.000000Z/2026-03-01T00:20:00.000000Z"]


def test_link_carries_the_contact_style() -> None:
    link = _packet(contact_packets([_contact()], {"Sat"}, Style()), "GS1-to-Sat")
    polyline = link["polyline"]
    assert polyline["show"] is True
    assert polyline["width"] == 1.0
    assert polyline["arcType"] == "NONE"  # a straight line of sight, not draped on the globe
    assert polyline["material"]["solidColor"]["color"]["rgba"] == [0, 255, 255, 255]


# --- ordering and observer reuse ----------------------------------------------------------


def test_observers_come_before_links() -> None:
    packets = contact_packets([_contact()], {"Sat"}, Style())
    assert _ids(packets) == ["GS1", "GS1-to-Sat"]


def test_one_observer_tracking_two_satellites_is_placed_once() -> None:
    # The same station seen in two contacts (one per satellite) yields one observer and two links.
    station = GroundStation(name="GS1", latitude=40.0, longitude=-75.0, height=0.1)
    contacts = [
        _contact(observer=station, target="SatA"),
        _contact(observer=station, target="SatB"),
    ]
    ids = _ids(contact_packets(contacts, {"SatA", "SatB"}, Style()))
    assert ids == ["GS1", "GS1-to-SatA", "GS1-to-SatB"]


def test_two_observers_seeing_one_satellite_both_render() -> None:
    contacts = [
        _contact(observer=GroundStation("A", 10.0, 20.0), target="Sat"),
        _contact(observer=GroundStation("B", -10.0, -20.0), target="Sat"),
    ]
    ids = _ids(contact_packets(contacts, {"Sat"}, Style()))
    assert ids == ["A", "B", "A-to-Sat", "B-to-Sat"]


# --- degenerate windows -------------------------------------------------------------------


def test_contact_with_no_windows_places_the_observer_but_no_link() -> None:
    packets = contact_packets([_contact(windows=[])], {"Sat"}, Style())
    assert _ids(packets) == ["GS1"]  # observer placed, no link


def test_single_window_contact_link_availability_is_a_one_element_list() -> None:
    # A contact with exactly one window still emits its availability as an interval *collection* (a
    # one-element list), not a bare interval string, so a client reads availability uniformly
    # whether a contact has one window or many.
    link = _packet(
        contact_packets([_contact(windows=[_window((0, 10), (0, 20))])], {"Sat"}, Style()),
        "GS1-to-Sat",
    )
    assert link["availability"] == ["2026-03-01T00:10:00.000000Z/2026-03-01T00:20:00.000000Z"]


def test_no_contacts_yields_no_packets() -> None:
    assert contact_packets([], {"Sat"}, Style()) == []


# --- guards -------------------------------------------------------------------------------


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(UnknownContactTargetError) as exc:
        contact_packets([_contact(target="Ghost")], {"Sat"}, Style())
    assert exc.value.target == "Ghost"
    assert exc.value.known == ("Sat",)


def test_observer_name_colliding_with_an_object_id_is_rejected() -> None:
    # An observer named like a satellite would share its packet id; Cesium would merge them.
    station = GroundStation(name="Sat", latitude=0.0, longitude=0.0)
    with pytest.raises(ContactEntityCollisionError) as exc:
        contact_packets([_contact(observer=station)], {"Sat"}, Style())
    assert exc.value.entity_id == "Sat"


def test_one_observer_name_with_two_placements_is_rejected() -> None:
    contacts = [
        _contact(observer=GroundStation("GS1", 40.0, -75.0), target="SatA"),
        _contact(observer=GroundStation("GS1", 41.0, -75.0), target="SatB"),  # different latitude
    ]
    with pytest.raises(ContactEntityCollisionError) as exc:
        contact_packets(contacts, {"SatA", "SatB"}, Style())
    assert exc.value.entity_id == "GS1"


def test_two_contacts_sharing_observer_and_target_are_rejected() -> None:
    station = GroundStation(name="GS1", latitude=40.0, longitude=-75.0)
    contacts = [_contact(observer=station, target="Sat"), _contact(observer=station, target="Sat")]
    with pytest.raises(ContactEntityCollisionError) as exc:
        contact_packets(contacts, {"Sat"}, Style())
    assert exc.value.entity_id == "GS1-to-Sat"
