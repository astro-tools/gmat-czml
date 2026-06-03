"""Command-line interface for gmat-czml.

The ``gmat-czml`` console script and its ``convert`` subcommand, which turns a trajectory into a
``.czml``. The parser is wired here so the console script and its help work; the conversion body
is filled in with the converter work and currently raises a clear not-implemented error.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the ``gmat-czml`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="gmat-czml",
        description="Convert a trajectory to CZML for Cesium visualization.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    convert = subparsers.add_parser(
        "convert",
        help="Convert a trajectory (a canonical file or DataFrame) to a .czml document.",
    )
    convert.add_argument(
        "input",
        help="Trajectory to convert (any file the format layer can read).",
    )
    convert.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path to write the .czml document to.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``gmat-czml`` console script.

    Returns the process exit code. With no subcommand, prints help and returns ``1``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    raise NotImplementedError("gmat-czml convert is not implemented yet.")
