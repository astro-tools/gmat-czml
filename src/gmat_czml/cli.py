"""Command-line interface for gmat-czml.

The ``gmat-czml`` console script and its ``convert`` subcommand, which reads any trajectory the
format layer (orbit-formats) can read and writes the same CZML document the public
:func:`gmat_czml.to_czml` call produces. The CLI is a thin driver over that one call: it parses no
trajectory formats and assembles no CZML itself — reading is delegated to ``orbit_formats.read``
and conversion to :func:`gmat_czml.to_czml`, so ``convert`` and the API stay byte-for-byte in step.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from orbit_formats import Ephemeris, OrbitFormatsError, read

from gmat_czml.assembly import to_czml
from gmat_czml.errors import GmatCzmlError
from gmat_czml.styles import Style

_PROG = "gmat-czml"

# The styles --style offers. v0.1 ships the single baked-in default; the preset system (and the
# wider choice set) is a later release, so the flag is validated to exactly what exists rather than
# accepting names the converter would silently ignore.
_STYLE_CHOICES = ("sat-default",)
_DEFAULT_STYLE = "sat-default"

# Mirrors the to_czml default so an unflagged convert and a bare to_czml() agree.
_DEFAULT_PLAYBACK_SECONDS = 60.0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``gmat-czml`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Convert a trajectory to CZML for Cesium visualization.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    convert = subparsers.add_parser(
        "convert",
        help="Convert a trajectory (any file the format layer can read) to a .czml document.",
        description=(
            "Read a trajectory — an OEM, a GMAT report, an SP3, an STK ephemeris, or any other "
            "format orbit-formats can read — and write the CZML document to_czml produces for it."
        ),
    )
    convert.add_argument(
        "input",
        help="Trajectory to convert (any file the format layer can read).",
    )
    convert.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="PATH",
        help="Path to write the .czml document to.",
    )
    convert.add_argument(
        "--style",
        choices=_STYLE_CHOICES,
        default=_DEFAULT_STYLE,
        help="Visual style applied to every object (default: %(default)s).",
    )
    convert.add_argument(
        "--playback-seconds",
        type=float,
        default=_DEFAULT_PLAYBACK_SECONDS,
        metavar="SECONDS",
        help=(
            "Wall-clock seconds the whole trajectory plays back in, setting the document clock's "
            "default speed (default: %(default)s)."
        ),
    )
    convert.add_argument(
        "--ground-track",
        action="store_true",
        help="Also emit each object's sub-satellite ground track (Earth-only).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``gmat-czml`` console script.

    Returns the process exit code. With no subcommand, prints help and returns ``1``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "convert":
        return _run_convert(args)

    parser.print_help()
    return 1


def _run_convert(args: argparse.Namespace) -> int:
    """Run ``gmat-czml convert``: read the trajectory, assemble the CZML, write it out.

    Returns the process exit code — ``0`` on success, ``1`` for a read failure, a non-trajectory
    input, or an assembly error, each reported as a one-line ``gmat-czml: ...`` message on stderr.
    The assembled document is byte-for-byte what ``to_czml(read(input), ...).to_json()`` produces.
    """
    try:
        trajectory = read(args.input)
    except (OSError, OrbitFormatsError) as exc:
        return _fail(f"cannot read {args.input}: {exc}")

    if not isinstance(trajectory, Ephemeris):
        kind = type(trajectory).__name__
        return _fail(
            f"{args.input} is not a trajectory (read as {kind}); convert needs a state ephemeris"
        )

    try:
        document = to_czml(
            trajectory,
            style=Style(name=args.style),
            playback_seconds=args.playback_seconds,
            ground_track=args.ground_track,
        )
    except (GmatCzmlError, ValueError) as exc:
        return _fail(str(exc))

    document.save(args.output)
    return 0


def _fail(message: str) -> int:
    """Print ``gmat-czml: <message>`` to stderr and return the failure exit code ``1``."""
    print(f"{_PROG}: {message}", file=sys.stderr)
    return 1
