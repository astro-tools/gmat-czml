"""Command-line interface for gmat-czml.

The ``gmat-czml`` console script and its subcommands. ``convert`` reads any trajectory the format
layer (orbit-formats) can read and writes the CZML document the public :func:`gmat_czml.to_czml`
call produces; ``serve`` builds that same document and hosts it over http behind an embedded
CesiumJS viewer (the optional ``[server]`` extra). Both are thin drivers over the API: they parse
no trajectory formats and assemble no CZML themselves — reading is delegated to
``orbit_formats.read`` and conversion to :func:`gmat_czml.to_czml`, so the CLI and the API stay
byte-for-byte in step.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from orbit_formats import Ephemeris, OrbitFormatsError, read

from gmat_czml.assembly import to_czml
from gmat_czml.document import CzmlDocument
from gmat_czml.errors import GmatCzmlError
from gmat_czml.styles import PRESET_NAMES, preset

_PROG = "gmat-czml"

# --style offers the named style presets (sat-default plus the colour palette); the flag is
# validated to exactly the recognised set rather than accepting names the converter would reject.
# The full colour / width / glyph customization API is the Python surface (gmat_czml.Style).
_DEFAULT_STYLE = "sat-default"

# Mirrors the to_czml default so an unflagged convert and a bare to_czml() agree.
_DEFAULT_PLAYBACK_SECONDS = 60.0

# The serve subcommand's default bind — loopback only (a local-sharing tool, not a public host).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080


class _CliError(Exception):
    """An internal, already-formatted CLI failure: its message is printed as ``gmat-czml: ...``."""


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
    _add_input_argument(convert)
    convert.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="PATH",
        help="Path to write the .czml document to.",
    )
    _add_render_arguments(convert)

    serve = subparsers.add_parser(
        "serve",
        help="Serve a trajectory as CZML behind an embedded CesiumJS viewer (needs [server]).",
        description=(
            "Read a trajectory, assemble the same CZML document convert would, and host it over "
            "http behind an embedded CesiumJS viewer. Needs the optional [server] extra "
            "(pip install gmat-czml[server]). Blocks until interrupted (Ctrl-C)."
        ),
    )
    _add_input_argument(serve)
    serve.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        metavar="HOST",
        help="Interface to bind (default: %(default)s).",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        metavar="PORT",
        help="Port to listen on (default: %(default)s).",
    )
    serve.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser tab when the server starts.",
    )
    _add_render_arguments(serve)

    return parser


def _add_input_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared positional trajectory ``input`` argument."""
    parser.add_argument(
        "input",
        help="Trajectory to render (any file the format layer can read).",
    )


def _add_render_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared rendering flags — ``--style`` / ``--playback-seconds`` / ``--ground-track``.

    The same three flags feed convert and serve, so both produce the same document for one input.
    """
    parser.add_argument(
        "--style",
        choices=PRESET_NAMES,
        default=_DEFAULT_STYLE,
        help="Style preset applied to every object (default: %(default)s).",
    )
    parser.add_argument(
        "--playback-seconds",
        type=float,
        default=_DEFAULT_PLAYBACK_SECONDS,
        metavar="SECONDS",
        help=(
            "Wall-clock seconds the whole trajectory plays back in, setting the document clock's "
            "default speed (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--ground-track",
        action="store_true",
        help="Also emit each object's sub-satellite ground track (Earth-only).",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``gmat-czml`` console script.

    Returns the process exit code. With no subcommand, prints help and returns ``1``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "convert":
        return _run_convert(args)
    if args.command == "serve":
        return _run_serve(args)

    parser.print_help()
    return 1


def _run_convert(args: argparse.Namespace) -> int:
    """Run ``gmat-czml convert``: read the trajectory, assemble the CZML, write it out.

    Returns the process exit code — ``0`` on success, ``1`` for a read failure, a non-trajectory
    input, or an assembly error, each reported as a one-line ``gmat-czml: ...`` message on stderr.
    The assembled document is byte-for-byte what ``to_czml(read(input), ...).to_json()`` produces.
    """
    try:
        document = _assemble_document(args)
    except _CliError as exc:
        return _fail(str(exc))

    document.save(args.output)
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    """Run ``gmat-czml serve``: assemble the CZML and host it behind the embedded viewer.

    The served document is byte-for-byte the one ``convert`` would write for the same input and
    flags. Returns ``0`` on a clean shutdown (Ctrl-C), ``1`` for a read failure, a non-trajectory
    input, an assembly error, or the missing ``[server]`` extra — each a one-line ``gmat-czml: ...``
    message on stderr. Blocks while the server runs.
    """
    try:
        document = _assemble_document(args)
    except _CliError as exc:
        return _fail(str(exc))

    try:
        document.serve(port=args.port, host=args.host, open_browser=not args.no_open)
    except ImportError as exc:  # the [server] extra is not installed
        return _fail(str(exc))
    except KeyboardInterrupt:  # pragma: no cover - interactive Ctrl-C
        return 0
    return 0


def _assemble_document(args: argparse.Namespace) -> CzmlDocument:
    """Read the trajectory and assemble the CZML, or raise :class:`_CliError` with a short message.

    Shared by ``convert`` and ``serve`` so both build the identical document from one input and the
    same flags. Raises :class:`_CliError` for a read failure, a non-trajectory input, or an assembly
    error; the caller turns that into a ``gmat-czml: ...`` message and a non-zero exit.
    """
    try:
        trajectory = read(args.input)
    except (OSError, OrbitFormatsError) as exc:
        raise _CliError(f"cannot read {args.input}: {exc}") from exc

    if not isinstance(trajectory, Ephemeris):
        kind = type(trajectory).__name__
        raise _CliError(
            f"{args.input} is not a trajectory (read as {kind}); needs a state ephemeris"
        )

    try:
        return to_czml(
            trajectory,
            style=preset(args.style),
            playback_seconds=args.playback_seconds,
            ground_track=args.ground_track,
        )
    except (GmatCzmlError, ValueError) as exc:
        raise _CliError(str(exc)) from exc


def _fail(message: str) -> int:
    """Print ``gmat-czml: <message>`` to stderr and return the failure exit code ``1``."""
    print(f"{_PROG}: {message}", file=sys.stderr)
    return 1
