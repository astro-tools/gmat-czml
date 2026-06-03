"""Package-level smoke tests: the import surface and the CLI plumbing."""

from __future__ import annotations

import pytest

import gmat_czml
from gmat_czml.cli import build_parser, main


def test_version_is_exposed() -> None:
    assert isinstance(gmat_czml.__version__, str)
    assert gmat_czml.__version__


def test_cli_parser_accepts_convert() -> None:
    args = build_parser().parse_args(["convert", "orbit.oem", "-o", "orbit.czml"])
    assert args.command == "convert"
    assert args.input == "orbit.oem"
    assert args.output == "orbit.czml"


def test_cli_without_command_prints_help_and_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    assert code == 1
    assert "convert" in capsys.readouterr().out
