"""Tests for the ``gmat-czml serve`` CLI subcommand (``gmat_czml.cli``).

``serve`` is a thin driver: it reads the trajectory and assembles the same CZML document ``convert``
would (the shared ``_assemble_document``), then hands it to :meth:`~gmat_czml.CzmlDocument.serve`.
The serve call blocks on a real server, so every test here **monkeypatches** ``CzmlDocument.serve``
to capture its arguments instead of binding a socket — the guards are (1) the bind flags map through
(``--host`` / ``--port`` / ``--no-open``), (2) the document handed to ``serve`` is byte-identical to
the one ``to_czml`` would build for the same input and render flags, and (3) the failure contract: a
one-line ``gmat-czml: ...`` message and a non-zero exit for a missing file, a non-trajectory input,
and the missing ``[server]`` extra.

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

_FIXTURE = Path(__file__).parent / "data" / "leo.oem"

# A valid TLE reads to mean elements, not a state ephemeris — the non-trajectory input serve drops.
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
def captured_serve(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``CzmlDocument.serve`` with a recorder, so no server is ever bound.

    Captures the document it was called on and the bind kwargs. ``main(["serve", ...])`` then
    returns ``0`` without blocking, and the test inspects what would have been served.
    """
    captured: dict[str, Any] = {}

    def _record(
        self: CzmlDocument,
        port: int = 8080,
        *,
        host: str = "127.0.0.1",
        open_browser: bool = True,
    ) -> None:
        captured["document"] = self
        captured["port"] = port
        captured["host"] = host
        captured["open_browser"] = open_browser

    monkeypatch.setattr(CzmlDocument, "serve", _record)
    return captured


# --- parser wiring ------------------------------------------------------------------------


def test_parser_accepts_serve_with_defaults() -> None:
    args = build_parser().parse_args(["serve", "orbit.oem"])
    assert args.command == "serve"
    assert args.input == "orbit.oem"
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.no_open is False


# --- the DoD: serve builds what convert would, and the bind flags map through --------------


def test_serve_hosts_the_document_to_czml_would_build(captured_serve: dict[str, Any]) -> None:
    rc = main(["serve", str(_FIXTURE)])
    assert rc == 0
    assert captured_serve["port"] == 8080
    assert captured_serve["host"] == "127.0.0.1"
    assert captured_serve["open_browser"] is True
    # The hosted document is byte-for-byte the one a bare to_czml / `convert` produces.
    assert captured_serve["document"].to_json() == to_czml(_trajectory()).to_json()


def test_bind_flags_map_through(captured_serve: dict[str, Any]) -> None:
    rc = main(["serve", str(_FIXTURE), "--host", "0.0.0.0", "--port", "9001", "--no-open"])
    assert rc == 0
    assert captured_serve["host"] == "0.0.0.0"
    assert captured_serve["port"] == 9001
    assert captured_serve["open_browser"] is False


def test_render_flags_change_the_hosted_document(captured_serve: dict[str, Any]) -> None:
    rc = main(["serve", str(_FIXTURE), "--ground-track", "--style", "sat-red"])
    assert rc == 0
    # The CLI applies the named preset (preset("sat-red")), not a bare Style(name=...) — so the
    # hosted document carries the sat-red palette and the ground track, like the matching convert.
    expected = to_czml(_trajectory(), style=preset("sat-red"), ground_track=True).to_json()
    assert captured_serve["document"].to_json() == expected
    assert captured_serve["document"].to_json() != to_czml(_trajectory()).to_json()


# --- the failure contract -----------------------------------------------------------------


def test_missing_input_fails_cleanly(
    captured_serve: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["serve", str(tmp_path / "absent.oem")])
    assert rc == 1
    assert "document" not in captured_serve  # serve was never reached
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "cannot read" in err


def test_non_trajectory_input_fails_cleanly(
    captured_serve: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tle = tmp_path / "iss.tle"
    tle.write_text(_TLE, encoding="utf-8")
    rc = main(["serve", str(tle)])
    assert rc == 1
    assert "document" not in captured_serve
    assert "not a trajectory" in capsys.readouterr().err


def test_serve_without_the_extra_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The real lazy-import path: with fastapi forced absent (and the cached server module + its
    # package attribute cleared so the lazy import re-executes), serve raises the actionable
    # ImportError, which the CLI reports as a one-line gmat-czml: message and a non-zero exit.
    monkeypatch.setitem(sys.modules, "fastapi", None)
    monkeypatch.delitem(sys.modules, "gmat_czml.server", raising=False)
    monkeypatch.delattr(gmat_czml, "server", raising=False)
    rc = main(["serve", str(_FIXTURE)])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "gmat-czml[server]" in err


# --- --help documents the subcommand and its options --------------------------------------


def test_serve_help_documents_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["serve", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--host",
        "--port",
        "--no-open",
        "--style",
        "--playback-seconds",
        "--ground-track",
    ):
        assert flag in out
