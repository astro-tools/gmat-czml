"""Turn a gmat-run ``Results`` into a CZML document, in one hop.

gmat-run runs a GMAT mission headlessly and returns a ``Results`` whose ``ephemerides`` and
``contacts`` are already keyed ``pandas.DataFrame`` views over the run's output files. A GMAT
ephemeris DataFrame *is* gmat-czml's canonical state series — same ``Epoch, X, Y, Z[, VX, VY, VZ]``
columns and the same ``attrs`` spine (``object_name`` / ``coordinate_system`` / ``central_body`` /
``time_scale`` / ``interpolation`` …) — so a trajectory flows into :func:`gmat_czml.to_czml` with no
reshaping. This adapter is the thin convenience that bundles a whole ``Results`` into one document
without the caller wiring each piece by hand.

**gmat-run stays optional.** It is imported *inside* these functions, never at module load, so
importing gmat-czml (and the minimal install) never needs it; calling the adapter without it
installed raises a clear, actionable :class:`ImportError` naming the install. The type annotations
reference ``gmat_run.Results`` only under :data:`typing.TYPE_CHECKING`.

**What maps, and what does not.** A ``Results`` is the run's *output*, which bounds what the adapter
can reach:

- **Ephemerides** map directly — :func:`results_to_trajectories` returns one canonical DataFrame per
  ``EphemerisFile`` resource (naming the object after the resource when the source declared no
  ``OBJECT_NAME``), and :func:`to_czml_from_results` renders them as a multi-object document.
- **Contacts** map to gmat-czml :class:`~gmat_czml.GroundStation` / :class:`~gmat_czml.Contact`
  records, but a GMAT ``ContactLocator`` report names its observer without its geodetic position —
  that lives on the ``GroundStation`` resource in the mission *script*, not in the run output. So
  the caller supplies each observer's placement via a ``stations`` mapping; the adapter pairs it
  with the access windows it reads from the report (:func:`results_to_contacts`).
- **Maneuvers and attitude are not reachable from a bare ``Results``.** gmat-run surfaces no
  maneuver output at all, and attitude lives on ``Mission.attitude_inputs``, not ``Results``.
  To annotate a document with either, read the source ``.opm`` / ``.aem`` through orbit-formats
  and pass the resulting ``Maneuver`` / ``Attitude`` to :func:`gmat_czml.to_czml` directly.

The adapter's own typed errors (:class:`MissingStationError`,
:class:`UnsupportedContactFormatError`) descend from :class:`~gmat_czml.GmatCzmlError`, so they are
catchable with the rest of the family, but live here rather than in the core error module — they are
concepts only this optional adapter raises. Errors from the conversion itself (an unknown contact
target, a duplicate object name, an empty trajectory) propagate from :func:`gmat_czml.to_czml`
unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd

from gmat_czml.assembly import to_czml
from gmat_czml.convert.contacts import Contact, GroundStation
from gmat_czml.document import CzmlDocument
from gmat_czml.errors import EmptyTrajectoryError, GmatCzmlError
from gmat_czml.styles import Style

if TYPE_CHECKING:
    from gmat_run import Results

__all__ = [
    "MissingStationError",
    "UnsupportedContactFormatError",
    "results_to_contacts",
    "results_to_trajectories",
    "to_czml_from_results",
]

# The two access-window columns the adapter reads each contact's ``(start, stop)`` intervals from.
# The window-bearing ContactLocator formats (Legacy, ContactRangeReport, the SiteView variants) all
# carry them; the per-tick AzimuthElevationRange variants report a single ``Time`` per sample, not
# an interval, so they have no windows to map and are rejected rather than misread.
_WINDOW_COLUMNS = ("Start", "Stop")

# The actionable hint raised when the optional gmat-run package is not installed.
_INSTALL_HINT = (
    "the gmat-run adapter needs the optional 'gmat-run' package, which is not installed; "
    "install it with `pip install gmat-run` (or `uv add gmat-run`) to convert a Results into CZML"
)


class MissingStationError(GmatCzmlError):
    """A contact observer has no geodetic placement in the supplied ``stations`` mapping.

    A GMAT ``ContactLocator`` report names its observer but not its position — the observer's
    longitude / latitude / height live on the ``GroundStation`` resource in the mission script, not
    in the run output — so the adapter cannot place the observer without a caller-supplied
    placement. ``observers`` are the unplaced names and ``provided`` the station keys that were
    supplied.
    """

    def __init__(self, observers: Iterable[str], provided: Iterable[str]) -> None:
        self.observers: tuple[str, ...] = tuple(observers)
        self.provided: tuple[str, ...] = tuple(provided)
        names = ", ".join(self.observers)
        have = ", ".join(self.provided) if self.provided else "(none)"
        super().__init__(
            f"no geodetic placement for contact observer(s): {names}; supply a GroundStation for "
            f"each in the stations mapping (provided: {have})"
        )


class UnsupportedContactFormatError(GmatCzmlError):
    """A contact resource whose ``ReportFormat`` carries no access-window columns.

    The adapter builds each contact's windows from the ``Start`` / ``Stop`` columns the
    window-bearing ContactLocator formats emit (Legacy, ContactRangeReport, the SiteView variants).
    The per-tick ``AzimuthElevationRange`` variants report one ``Time`` per sample rather than an
    interval, so there are no windows to map. ``report_format`` is the offending variant and
    ``resource`` the contact resource name.
    """

    def __init__(self, report_format: str, resource: str) -> None:
        self.report_format = report_format
        self.resource = resource
        super().__init__(
            f"contact resource {resource!r} uses ReportFormat {report_format!r}, which carries no "
            "access-window (Start/Stop) columns; use a window-bearing ContactLocator format "
            "(Legacy, ContactRangeReport, or a SiteView variant)"
        )


def to_czml_from_results(
    results: Results,
    *,
    ephemerides: Sequence[str] | None = None,
    stations: Mapping[str, GroundStation] | None = None,
    contact_resources: Sequence[str] | None = None,
    style: Style | None = None,
    playback_seconds: float = 60.0,
    ground_track: bool = False,
) -> CzmlDocument:
    """Convert a gmat-run ``Results`` into a :class:`~gmat_czml.CzmlDocument` in one hop.

    Every ``EphemerisFile`` resource becomes one object in the document; pass ``ephemerides`` to
    render a subset (a sequence of resource names, in the order given) instead of all of them.
    ``style``, ``playback_seconds``, and ``ground_track`` are forwarded to
    :func:`gmat_czml.to_czml` unchanged.

    When ``stations`` is given (``{observer name: GroundStation}``), the run's ``ContactLocator``
    resources are mapped to observer entities and per-window links; ``contact_resources`` selects a
    subset of them (default: all). Every observer named in a mapped report must have a placement in
    ``stations`` — the report does not carry one (see :class:`MissingStationError`). Without
    ``stations`` no contacts are rendered, and passing ``contact_resources`` without ``stations`` is
    an error.

    Maneuvers and attitude are not rendered here: a ``Results`` carries no maneuver output, and
    attitude lives on ``Mission``, not ``Results`` — read the source ``.opm`` / ``.aem`` through
    orbit-formats and pass the result to :func:`gmat_czml.to_czml` directly.

    Raises :class:`ImportError` if gmat-run is not installed,
    :class:`~gmat_czml.EmptyTrajectoryError` if the ``Results`` has no ephemerides,
    :class:`MissingStationError` /
    :class:`UnsupportedContactFormatError` for the contact-mapping failures, and whatever
    :func:`gmat_czml.to_czml` raises for the conversion itself (e.g. a duplicate object name, or a
    contact targeting an object not in the document).
    """
    trajectories = results_to_trajectories(results, names=ephemerides)
    contacts: list[Contact] | None = None
    if stations is not None:
        contacts = results_to_contacts(results, stations, names=contact_resources)
    elif contact_resources is not None:
        raise ValueError(
            "contact_resources was given without stations; supply a stations mapping "
            "({observer name: GroundStation}) so the contact observers can be placed"
        )
    return to_czml(
        trajectories,
        style=style,
        playback_seconds=playback_seconds,
        ground_track=ground_track,
        contacts=contacts,
    )


def results_to_trajectories(
    results: Results, *, names: Sequence[str] | None = None
) -> list[pd.DataFrame]:
    """The ``Results`` ephemerides as canonical state-series DataFrames, one per resource.

    ``names`` selects a subset of ``EphemerisFile`` resources (in the order given); the default is
    every ephemeris in the run, in its insertion order. Each DataFrame is the gmat-run-parsed
    canonical frame, returned as-is when the source declared an ``OBJECT_NAME`` and otherwise with
    the resource name set as ``attrs['object_name']`` (so the object has a stable, unique id). The
    caller's DataFrames are never mutated — the fallback is applied on a shallow copy.

    Raises :class:`ImportError` if gmat-run is absent, :class:`KeyError` if ``names`` references an
    unknown resource, and :class:`~gmat_czml.EmptyTrajectoryError` if the selection is empty.
    """
    checked = _checked_results(results)
    keys = _selected_keys(checked.ephemerides, names, kind="ephemeris")
    if not keys:
        raise EmptyTrajectoryError("the gmat-run Results carries no ephemerides to render")
    return [_trajectory_frame(checked.ephemerides[key], key) for key in keys]


def results_to_contacts(
    results: Results,
    stations: Mapping[str, GroundStation],
    *,
    names: Sequence[str] | None = None,
) -> list[Contact]:
    """The ``Results`` contacts as gmat-czml :class:`~gmat_czml.Contact` records.

    ``stations`` places each observer (``{observer name: GroundStation}``); ``names`` selects a
    subset of ``ContactLocator`` resources (default: all). For each mapped report, the target
    satellite is read from the report and one :class:`~gmat_czml.Contact` is produced per observer,
    its windows the report's ``(Start, Stop)`` access intervals (UTC). The returned contacts are in
    resource order, then observer order within each resource.

    Raises :class:`ImportError` if gmat-run is absent, :class:`KeyError` if ``names`` references an
    unknown resource, :class:`UnsupportedContactFormatError` for a report with no window columns,
    and :class:`MissingStationError` for an observer with no placement in ``stations``.
    """
    checked = _checked_results(results)
    keys = _selected_keys(checked.contacts, names, kind="contact")
    contacts: list[Contact] = []
    for key in keys:
        contacts.extend(_contacts_from_frame(checked.contacts[key], stations, resource=key))
    return contacts


def _results_class() -> type[Results]:
    """Import ``gmat_run.Results`` lazily, raising a clear :class:`ImportError` when absent."""
    try:
        from gmat_run import Results
    except ImportError as exc:  # ModuleNotFoundError, or a half-installed gmat-run
        raise ImportError(_INSTALL_HINT) from exc
    return Results


def _checked_results(results: Results) -> Results:
    """Confirm gmat-run is installed and ``results`` is a ``Results`` before reading it."""
    results_class = _results_class()
    if not isinstance(results, results_class):
        raise TypeError(f"expected a gmat_run.Results, got {type(results).__name__!r}")
    return results


def _selected_keys(
    available: Mapping[str, pd.DataFrame], names: Sequence[str] | None, *, kind: str
) -> list[str]:
    """The resource keys to read: all of ``available`` (insertion order), or the named subset.

    Iterating / membership-testing the lazy ``Results`` mappings does not parse any file, so a
    selection only materialises the DataFrames it actually keeps.
    """
    if names is None:
        return list(available)
    missing = [name for name in names if name not in available]
    if missing:
        joined = ", ".join(sorted(available)) or "(none)"
        raise KeyError(f"no {kind} resource(s) named {missing} in the Results; available: {joined}")
    return list(names)


def _trajectory_frame(frame: pd.DataFrame, resource: str) -> pd.DataFrame:
    """The ephemeris frame, named after its resource when the source declared no ``OBJECT_NAME``.

    Returns the frame untouched when it already carries an object name; otherwise a shallow copy
    whose ``attrs`` name the object after the resource key — leaving the caller's frame unmutated.
    """
    if frame.attrs.get("object_name"):
        return frame
    named: pd.DataFrame = frame.copy(deep=False)
    named.attrs = {**frame.attrs, "object_name": resource}
    return named


def _contacts_from_frame(
    frame: pd.DataFrame, stations: Mapping[str, GroundStation], *, resource: str
) -> list[Contact]:
    """One :class:`~gmat_czml.Contact` per observer in a single ContactLocator report frame."""
    if any(column not in frame.columns for column in _WINDOW_COLUMNS):
        report_format = str(frame.attrs.get("report_format", "unknown"))
        raise UnsupportedContactFormatError(report_format, resource)
    target = frame.attrs.get("target")
    if not target:
        raise ValueError(
            f"contact resource {resource!r} declares no target satellite "
            "(attrs['target'] is missing)"
        )

    observers = _observer_order(frame)
    unplaced = [observer for observer in observers if observer not in stations]
    if unplaced:
        raise MissingStationError(unplaced, sorted(stations))

    return [
        Contact(
            observer=stations[observer],
            target=str(target),
            windows=_windows_for(frame, observer),
        )
        for observer in observers
    ]


def _observer_order(frame: pd.DataFrame) -> list[str]:
    """The observers in first-seen order: ``attrs['observers']`` if present, else the column."""
    declared = frame.attrs.get("observers")
    if isinstance(declared, tuple):
        return [str(observer) for observer in declared]
    seen: dict[str, None] = {}
    for value in frame["Observer"]:
        seen.setdefault(str(value), None)
    return list(seen)


def _windows_for(frame: pd.DataFrame, observer: str) -> list[tuple[datetime, datetime]]:
    """The ``(start, stop)`` access windows for one observer, UTC and sorted by start."""
    rows = frame[frame["Observer"].astype("string") == observer]
    windows = [
        (_as_utc(start), _as_utc(stop))
        for start, stop in zip(rows["Start"], rows["Stop"], strict=True)
    ]
    windows.sort(key=lambda window: window[0])
    return windows


def _as_utc(value: Any) -> datetime:
    """A pandas/NumPy datetime as a UTC-aware :class:`~datetime.datetime`.

    ``ContactLocator`` times are always UTC (gmat-run tags the parsed columns ``time_scale='UTC'``),
    so a naive value is read as UTC and an aware one converted.
    """
    moment = pd.Timestamp(value).to_pydatetime()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
