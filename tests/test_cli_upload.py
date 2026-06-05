"""Tests for the ``gmat-czml upload`` CLI subcommand (``gmat_czml.cli``).

``upload`` is a thin driver: it resolves a Cesium ion token (``--token`` else the
``CESIUM_ION_TOKEN`` environment variable), reads the trajectory and assembles the same CZML
document ``convert`` would (the shared ``_assemble_document``), then hands it to
:meth:`~gmat_czml.CzmlDocument.upload_to_ion`. The upload talks to the network, so every test here
**monkeypatches** ``CzmlDocument.upload_to_ion`` to capture its arguments and return a canned
asset — no socket is opened. The guards are (1) the token resolves from the flag and the env (flag
wins),
(2) the render flags map through and the uploaded document is byte-identical to the one ``to_czml``
would build, and (3) the failure contract: a one-line ``gmat-czml: ...`` message and a non-zero exit
for a missing token (before any work), a missing file, a non-trajectory input, an ion-side failure,
and the missing ``[ion]`` extra.

Unmarked (not ``czml`` / ``browser``), so they run in the cross-platform ``test`` matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from orbit_formats import Ephemeris, read

import gmat_czml
from gmat_czml import CzmlDocument, preset, to_czml
from gmat_czml.cli import build_parser, main
from gmat_czml.errors import IonUploadError
from gmat_czml.ion import IonAsset

_FIXTURE = Path(__file__).parent / "data" / "leo.oem"

# A valid TLE reads to mean elements, not a state ephemeris — the non-trajectory input upload drops.
_TLE = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)


def _trajectory() -> Ephemeris:
    obj = read(_FIXTURE)
    assert isinstance(obj, Ephemeris)
    return obj


@pytest.fixture
def captured_upload(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``CzmlDocument.upload_to_ion`` with a recorder, so no network call is ever made.

    Captures the document it was called on and the upload kwargs, and returns a canned
    :class:`~gmat_czml.ion.IonAsset`. ``main(["upload", ...])`` then returns ``0`` without any I/O,
    and the test inspects what would have been uploaded.
    """
    captured: dict[str, Any] = {}

    def _record(
        self: CzmlDocument,
        token: str,
        *,
        name: str,
        description: str = "",
        wait: bool = True,
    ) -> IonAsset:
        captured["document"] = self
        captured["token"] = token
        captured["name"] = name
        captured["description"] = description
        captured["wait"] = wait
        return IonAsset(id=99, name=name, type="CZML", status="COMPLETE")

    monkeypatch.setattr(CzmlDocument, "upload_to_ion", _record)
    return captured


# --- parser wiring ------------------------------------------------------------------------


def test_parser_accepts_upload_with_defaults() -> None:
    args = build_parser().parse_args(["upload", "orbit.oem"])
    assert args.command == "upload"
    assert args.input == "orbit.oem"
    assert args.name is None
    assert args.description == ""
    assert args.token is None
    assert args.no_wait is False


# --- token resolution + the document upload would build -----------------------------------


def test_upload_uses_token_flag_and_builds_the_convert_document(
    captured_upload: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["upload", str(_FIXTURE), "--token", "tok-flag", "--name", "Orbit", "--description", "d"]
    )
    assert rc == 0
    assert captured_upload["token"] == "tok-flag"
    assert captured_upload["name"] == "Orbit"
    assert captured_upload["description"] == "d"
    assert captured_upload["wait"] is True
    # The uploaded document is byte-for-byte the one a bare to_czml / `convert` produces.
    assert captured_upload["document"].to_json() == to_czml(_trajectory()).to_json()
    # Success reports the new asset's id and dashboard URL on stdout.
    out = capsys.readouterr().out
    assert "99" in out
    assert "https://ion.cesium.com/assets/99" in out


def test_token_falls_back_to_env(
    captured_upload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CESIUM_ION_TOKEN", "tok-env")
    rc = main(["upload", str(_FIXTURE)])
    assert rc == 0
    assert captured_upload["token"] == "tok-env"


def test_token_flag_overrides_env(
    captured_upload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CESIUM_ION_TOKEN", "tok-env")
    rc = main(["upload", str(_FIXTURE), "--token", "tok-flag"])
    assert rc == 0
    assert captured_upload["token"] == "tok-flag"


def test_default_name_is_the_input_stem(captured_upload: dict[str, Any]) -> None:
    rc = main(["upload", str(_FIXTURE), "--token", "t"])
    assert rc == 0
    assert captured_upload["name"] == _FIXTURE.stem  # "leo"


def test_no_wait_flag_maps_through(captured_upload: dict[str, Any]) -> None:
    rc = main(["upload", str(_FIXTURE), "--token", "t", "--no-wait"])
    assert rc == 0
    assert captured_upload["wait"] is False


def test_render_flags_change_the_uploaded_document(captured_upload: dict[str, Any]) -> None:
    rc = main(["upload", str(_FIXTURE), "--token", "t", "--ground-track", "--style", "sat-red"])
    assert rc == 0
    expected = to_czml(_trajectory(), style=preset("sat-red"), ground_track=True).to_json()
    assert captured_upload["document"].to_json() == expected
    assert captured_upload["document"].to_json() != to_czml(_trajectory()).to_json()


# --- the failure contract -----------------------------------------------------------------


def test_missing_token_fails_before_any_work(
    captured_upload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    rc = main(["upload", str(_FIXTURE)])
    assert rc == 1
    assert "document" not in captured_upload  # upload_to_ion was never reached
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "CESIUM_ION_TOKEN" in err


def test_missing_input_fails_cleanly(
    captured_upload: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["upload", str(tmp_path / "absent.oem"), "--token", "t"])
    assert rc == 1
    assert "document" not in captured_upload  # upload was never reached
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "cannot read" in err


def test_non_trajectory_input_fails_cleanly(
    captured_upload: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tle = tmp_path / "iss.tle"
    tle.write_text(_TLE, encoding="utf-8")
    rc = main(["upload", str(tle), "--token", "t"])
    assert rc == 1
    assert "document" not in captured_upload
    assert "not a trajectory" in capsys.readouterr().err


def test_ion_upload_error_is_reported_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(
        self: CzmlDocument, token: str, *, name: str, description: str = "", wait: bool = True
    ) -> IonAsset:
        raise IonUploadError("asset 5 finished in state ERROR")

    monkeypatch.setattr(CzmlDocument, "upload_to_ion", _boom)
    rc = main(["upload", str(_FIXTURE), "--token", "t"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "Cesium ion upload failed" in err


def test_upload_without_the_extra_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The real lazy-import path: with boto3 forced absent (and the cached ion module + its package
    # attribute cleared so the lazy import re-executes), upload_to_ion raises the actionable
    # ImportError, which the CLI reports as a one-line gmat-czml: message and a non-zero exit.
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.delitem(sys.modules, "gmat_czml.ion", raising=False)
    monkeypatch.delattr(gmat_czml, "ion", raising=False)
    rc = main(["upload", str(_FIXTURE), "--token", "t"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "gmat-czml[ion]" in err


# --- --help documents the subcommand and its options --------------------------------------


def test_upload_help_documents_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["upload", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--name",
        "--description",
        "--token",
        "--no-wait",
        "--style",
        "--playback-seconds",
        "--ground-track",
    ):
        assert flag in out
