"""Tests for the ``gmat-czml convert`` CLI (``gmat_czml.cli``).

The load-bearing guard is the DoD identity: ``gmat-czml convert`` writes byte-for-byte the document
the equivalent :func:`gmat_czml.to_czml` call produces, so the CLI is only ever a thin driver over
the API and the two cannot drift. The rest pin the flag wiring — each core flag maps to its
``to_czml`` argument — and the failure contract: a one-line ``gmat-czml: ...`` message and a
non-zero exit for a missing file, a non-trajectory input, an unknown style, and no subcommand.

These are unmarked (not ``czml``), so they run in the cross-platform ``test`` matrix rather than the
single-platform CZML-schema-validation job; the fixture is read on both sides of every identity
assertion, so the comparison is robust to serialization and line-ending differences.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orbit_formats import Ephemeris, read

from gmat_czml import Style, to_czml
from gmat_czml.cli import main

_FIXTURE = Path(__file__).parent / "data" / "leo.oem"

# A valid TLE (the canonical example, correct checksums) reads to mean elements, not a state
# ephemeris — the non-trajectory input the converter must reject cleanly.
_TLE = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
)


def _trajectory() -> Ephemeris:
    """The fixture parsed through orbit-formats — the same read the CLI performs."""
    obj = read(_FIXTURE)
    assert isinstance(obj, Ephemeris)
    return obj


def _expected(
    *,
    style: Style | None = None,
    playback_seconds: float = 60.0,
    ground_track: bool = False,
) -> str:
    """The JSON the public API produces for the fixture with the given ``to_czml`` options.

    The defaults mirror the CLI's, so ``_expected()`` is what an unflagged ``convert`` must write.
    """
    return to_czml(
        _trajectory(),
        style=style,
        playback_seconds=playback_seconds,
        ground_track=ground_track,
    ).to_json()


# --- the DoD identity ---------------------------------------------------------------------


def test_convert_writes_what_to_czml_would(tmp_path: Path) -> None:
    out = tmp_path / "orbit.czml"
    rc = main(["convert", str(_FIXTURE), "-o", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == _expected()


# --- flag wiring: each core flag maps to its to_czml argument ------------------------------


def test_ground_track_flag_maps_to_the_api(tmp_path: Path) -> None:
    out = tmp_path / "gt.czml"
    rc = main(["convert", str(_FIXTURE), "-o", str(out), "--ground-track"])
    assert rc == 0
    written = out.read_text(encoding="utf-8")
    assert written == _expected(ground_track=True)
    assert written != _expected()  # the flag genuinely adds the ground-track packet


def test_playback_seconds_flag_maps_to_the_api(tmp_path: Path) -> None:
    out = tmp_path / "pb.czml"
    rc = main(["convert", str(_FIXTURE), "-o", str(out), "--playback-seconds", "30"])
    assert rc == 0
    written = out.read_text(encoding="utf-8")
    assert written == _expected(playback_seconds=30.0)
    assert written != _expected()  # the clock speed actually changes


def test_style_flag_maps_to_the_api(tmp_path: Path) -> None:
    out = tmp_path / "st.czml"
    rc = main(["convert", str(_FIXTURE), "-o", str(out), "--style", "sat-default"])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == _expected(style=Style("sat-default"))


def test_unknown_style_is_rejected(tmp_path: Path) -> None:
    out = tmp_path / "no.czml"
    with pytest.raises(SystemExit) as excinfo:
        main(["convert", str(_FIXTURE), "-o", str(out), "--style", "fancy"])
    assert excinfo.value.code == 2  # argparse usage error
    assert not out.exists()


# --- the failure contract -----------------------------------------------------------------


def test_missing_input_fails_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "no.czml"
    rc = main(["convert", str(tmp_path / "absent.oem"), "-o", str(out)])
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert err.startswith("gmat-czml: ")
    assert "cannot read" in err


def test_non_trajectory_input_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tle = tmp_path / "iss.tle"
    tle.write_text(_TLE, encoding="utf-8")
    out = tmp_path / "no.czml"
    rc = main(["convert", str(tle), "-o", str(out)])
    assert rc == 1
    assert not out.exists()
    assert "not a trajectory" in capsys.readouterr().err


def test_no_subcommand_prints_help_and_returns_one(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 1
    assert "convert" in capsys.readouterr().out  # help lists the subcommand


# --- --help documents the subcommand and its options (DoD) --------------------------------


def test_convert_help_documents_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["convert", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--output", "--style", "--playback-seconds", "--ground-track"):
        assert flag in out
