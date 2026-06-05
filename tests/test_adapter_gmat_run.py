"""Tests for the gmat-run producer adapter (:mod:`gmat_czml.adapters.gmat_run`).

The whole module is skipped when gmat-run is not installed (the adapter is optional and gmat-run is
a dev-only dependency), so these run on the full test/lint/typecheck environment but never gate the
minimal install. They build a ``Results`` straight from committed output fixtures — the real GMAT
LEO CCSDS-OEM ephemeris and a Legacy ``ContactLocator`` report — so the adapter is exercised through
gmat-run's actual parsers with no GMAT engine in the loop.

The guards that do not need a real parser (the object-name fallback, the unsupported contact format,
and the absent-gmat-run error) are driven from synthesized inputs so they need no extra fixture.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

gmat_run = pytest.importorskip("gmat_run")
from gmat_run import Results  # noqa: E402  (after importorskip)

from gmat_czml import CzmlDocument, GroundStation  # noqa: E402
from gmat_czml.adapters import gmat_run as adapter  # noqa: E402
from gmat_czml.adapters.gmat_run import (  # noqa: E402
    MissingStationError,
    UnsupportedContactFormatError,
    results_to_contacts,
    results_to_trajectories,
    to_czml_from_results,
)
from gmat_czml.errors import DuplicateObjectNameError, EmptyTrajectoryError  # noqa: E402

_DATA = Path(__file__).parent / "data"
_GMAT_OEM = _DATA / "gmat-leo.oem"
_GMAT_CONTACTS = _DATA / "gmat-leo-contacts.report"

# A real geodetic placement for the contact observer in the committed report (the Canberra DSN
# complex); the report names the observer but not its position, so the adapter takes it from here.
_CANBERRA = GroundStation(name="Canberra", latitude=-35.4014, longitude=148.9819, height=0.55)


def _results(**paths: object) -> Results:
    """A ``Results`` over the committed fixtures (no GMAT run needed)."""
    return Results(output_dir=_DATA, log="", **paths)  # type: ignore[arg-type]


def _ids(document: CzmlDocument) -> list[str]:
    return [packet["id"] for packet in document.to_dict()]


# --- ephemerides -------------------------------------------------------------------------


def test_results_to_trajectories_reads_the_canonical_frame() -> None:
    frames = results_to_trajectories(_results(ephemeris_paths={"EphemerisFile1": _GMAT_OEM}))
    assert len(frames) == 1
    frame = frames[0]
    assert list(frame.columns) == ["Epoch", "X", "Y", "Z", "VX", "VY", "VZ"]
    assert frame.attrs["object_name"] == "GmatLeo"
    assert frame.attrs["coordinate_system"] == "EME2000"
    assert frame.attrs["time_scale"] == "UTC"


def test_one_hop_renders_the_ephemeris() -> None:
    document = to_czml_from_results(_results(ephemeris_paths={"EphemerisFile1": _GMAT_OEM}))
    assert isinstance(document, CzmlDocument)
    ids = _ids(document)
    assert ids[0] == "document"
    assert "GmatLeo" in ids


def test_ground_track_flag_is_forwarded() -> None:
    document = to_czml_from_results(
        _results(ephemeris_paths={"EphemerisFile1": _GMAT_OEM}), ground_track=True
    )
    assert any(packet_id.startswith("GmatLeo/groundtrack") for packet_id in _ids(document))


def test_ephemerides_selection_picks_a_subset() -> None:
    results = _results(ephemeris_paths={"A": _GMAT_OEM, "B": _GMAT_OEM})
    frames = results_to_trajectories(results, names=["A"])
    assert len(frames) == 1


def test_unknown_ephemeris_selection_raises() -> None:
    results = _results(ephemeris_paths={"EphemerisFile1": _GMAT_OEM})
    with pytest.raises(KeyError, match="ephemeris"):
        results_to_trajectories(results, names=["nope"])


def test_duplicate_object_name_across_ephemerides_is_rejected() -> None:
    # Two resources reading the same OEM both resolve to object_name "GmatLeo"; the conversion
    # rejects the id collision rather than silently merging the two satellites.
    results = _results(ephemeris_paths={"A": _GMAT_OEM, "B": _GMAT_OEM})
    with pytest.raises(DuplicateObjectNameError):
        to_czml_from_results(results)


def test_object_name_falls_back_to_the_resource_key(tmp_path: Path) -> None:
    oem = tmp_path / "unnamed.oem"
    oem.write_text(
        "CCSDS_OEM_VERS = 2.0\n"
        "CREATION_DATE = 2026-01-01T00:00:00.000\n"
        "ORIGINATOR = TEST\n\n"
        "META_START\n"
        "REF_FRAME = EME2000\n"
        "CENTER_NAME = Earth\n"
        "TIME_SYSTEM = UTC\n"
        "META_STOP\n"
        "2026-03-01T00:00:00.000 7000.0 0.0 0.0 0.0 7.5 0.0\n"
        "2026-03-01T00:10:00.000 6900.0 100.0 0.0 -0.1 7.5 0.0\n",
        encoding="utf-8",
    )
    frames = results_to_trajectories(
        Results(output_dir=tmp_path, log="", ephemeris_paths={"MySat": oem})
    )
    assert frames[0].attrs["object_name"] == "MySat"


def test_empty_results_raises() -> None:
    with pytest.raises(EmptyTrajectoryError):
        results_to_trajectories(_results())


# --- contacts ----------------------------------------------------------------------------


def test_contacts_place_the_observer_and_link() -> None:
    results = _results(
        ephemeris_paths={"EphemerisFile1": _GMAT_OEM},
        contact_paths={"Contacts1": _GMAT_CONTACTS},
    )
    document = to_czml_from_results(results, stations={"Canberra": _CANBERRA})
    ids = _ids(document)
    assert "Canberra" in ids
    assert "Canberra-to-GmatLeo" in ids


def test_results_to_contacts_reads_the_windows() -> None:
    results = _results(contact_paths={"Contacts1": _GMAT_CONTACTS})
    contacts = results_to_contacts(results, {"Canberra": _CANBERRA})
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact.target == "GmatLeo"
    assert contact.observer is _CANBERRA
    assert len(contact.windows) == 2
    first_start, first_stop = contact.windows[0]
    assert first_start == dt.datetime(2026, 3, 1, 0, 10, tzinfo=dt.timezone.utc)
    assert first_stop == dt.datetime(2026, 3, 1, 0, 22, tzinfo=dt.timezone.utc)


def test_missing_station_placement_raises() -> None:
    results = _results(contact_paths={"Contacts1": _GMAT_CONTACTS})
    with pytest.raises(MissingStationError, match="Canberra"):
        results_to_contacts(results, {})


def test_no_stations_renders_no_contacts() -> None:
    results = _results(
        ephemeris_paths={"EphemerisFile1": _GMAT_OEM},
        contact_paths={"Contacts1": _GMAT_CONTACTS},
    )
    ids = _ids(to_czml_from_results(results))
    assert not any("Canberra" in packet_id for packet_id in ids)


def test_contact_resources_without_stations_is_an_error() -> None:
    results = _results(
        ephemeris_paths={"EphemerisFile1": _GMAT_OEM},
        contact_paths={"Contacts1": _GMAT_CONTACTS},
    )
    with pytest.raises(ValueError, match="stations"):
        to_czml_from_results(results, contact_resources=["Contacts1"])


def test_per_tick_contact_format_is_rejected() -> None:
    # An AzimuthElevationRange report carries one Time per tick, not Start/Stop windows.
    frame = pd.DataFrame(
        {
            "Pass": [1, 1],
            "Observer": ["GS1", "GS1"],
            "Time": pd.to_datetime(["2026-03-01T00:10:00", "2026-03-01T00:11:00"]),
            "Azimuth": [10.0, 12.0],
            "Elevation": [5.0, 7.0],
            "Range": [2000.0, 1900.0],
        }
    )
    frame.attrs["report_format"] = "AzimuthElevationRangeReport"
    frame.attrs["target"] = "GmatLeo"
    with pytest.raises(UnsupportedContactFormatError, match="AzimuthElevationRangeReport"):
        adapter._contacts_from_frame(frame, {"GS1": _CANBERRA}, resource="Contacts1")


def test_window_report_without_a_target_is_rejected() -> None:
    # A window-bearing report (Start/Stop present) that declares no target satellite cannot be
    # attributed to an object, so it is rejected rather than producing an untargetable contact.
    frame = pd.DataFrame(
        {
            "Observer": ["GS1"],
            "Start": pd.to_datetime(["2026-03-01T00:10:00"]),
            "Stop": pd.to_datetime(["2026-03-01T00:22:00"]),
        }
    )
    with pytest.raises(ValueError, match="no target"):
        adapter._contacts_from_frame(frame, {"GS1": _CANBERRA}, resource="Contacts1")


def test_observer_order_falls_back_to_the_observer_column() -> None:
    # With no attrs['observers'] tuple, observer identity and order come from the Observer column —
    # first-seen and de-duplicated. Two windows for GS1 and one for GS2 yield one contact each, in
    # column order, GS1's windows sorted by start.
    frame = pd.DataFrame(
        {
            "Observer": ["GS1", "GS2", "GS1"],
            "Start": pd.to_datetime(
                ["2026-03-01T00:10:00", "2026-03-01T00:30:00", "2026-03-01T01:05:00"]
            ),
            "Stop": pd.to_datetime(
                ["2026-03-01T00:22:00", "2026-03-01T00:42:00", "2026-03-01T01:17:00"]
            ),
        }
    )
    frame.attrs["target"] = "GmatLeo"
    stations = {
        "GS1": GroundStation(name="GS1", latitude=-35.0, longitude=149.0, height=0.0),
        "GS2": GroundStation(name="GS2", latitude=10.0, longitude=20.0, height=0.0),
    }
    contacts = adapter._contacts_from_frame(frame, stations, resource="Contacts1")
    assert [contact.observer.name for contact in contacts] == ["GS1", "GS2"]  # first-seen order
    gs1 = next(contact for contact in contacts if contact.observer.name == "GS1")
    assert len(gs1.windows) == 2  # both GS1 windows, sorted by start
    assert gs1.windows[0][0] == dt.datetime(2026, 3, 1, 0, 10, tzinfo=dt.timezone.utc)


def test_as_utc_converts_an_aware_timestamp() -> None:
    # An already-aware window endpoint is converted to UTC, not relabelled: 05:10 at +05:00 is
    # 00:10 UTC (the naive-is-UTC path is covered by the real-report windows test above).
    aware = pd.Timestamp(dt.datetime(2026, 3, 1, 5, 10, tzinfo=dt.timezone(dt.timedelta(hours=5))))
    assert adapter._as_utc(aware) == dt.datetime(2026, 3, 1, 0, 10, tzinfo=dt.timezone.utc)


# --- the optional-dependency boundary ----------------------------------------------------


def test_absent_gmat_run_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gmat_run", None)
    with pytest.raises(ImportError, match="pip install gmat-run"):
        adapter._results_class()


def test_non_results_argument_is_rejected() -> None:
    # gmat-run is installed but the argument is not a Results: the adapter rejects it with a clear
    # TypeError rather than failing deep in an attribute access on the wrong object.
    with pytest.raises(TypeError, match="Results"):
        results_to_trajectories("not a results")  # type: ignore[arg-type]
