"""Shared support for the gmat-czml validation harness.

Not a test module — the leading underscore keeps pytest from collecting it. It holds the three
things the schema-validation, golden-regression, and headless-CesiumJS tests all build on:

- :func:`czml_validator` — a draft-07 validator bound to the *official* CZML JSON schema vendored
  under ``tests/data/czml-schema/`` (CesiumGS/czml-writer), so the check is the real spec and is
  independent of czml3 (the library that emits the document);
- the two **producer fixtures** — a real GMAT R2026a CCSDS-OEM LEO ephemeris and a Skyfield TLE
  propagation — each normalised to the canonical state series :func:`gmat_czml.to_czml` consumes;
- :data:`DOCUMENTS` — the catalogue of named documents the goldens and the schema check both
  drive, so there is a single source of truth for what gets validated and locked.

Golden bytes are written and read verbatim (``-text`` in ``.gitattributes`` keeps them byte-stable
across platforms); regeneration is deliberate and gated on ``GMAT_CZML_REGEN`` — the goldens drift
only when the ``czml3`` or ``skyfield`` pin changes.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import numpy as np
import orbit_formats as of
import pandas as pd
from jsonschema import Draft7Validator
from orbit_formats import Ephemeris, Maneuver
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from gmat_czml import Contact, CzmlDocument, GroundStation, to_czml

_DATA = Path(__file__).parent / "data"
_SCHEMA_DIR = _DATA / "czml-schema"
GOLDEN_DIR = _DATA / "golden"

_GMAT_OEM = _DATA / "gmat-leo.oem"
_ISS_TLE = _DATA / "iss.tle"

# The validation entry point of the vendored schema: a CZML document is an array of packets.
_DOCUMENT_SCHEMA_ID = "https://analyticalgraphicsinc.github.io/czml-writer/Schema/Document.json"

# Regeneration is opt-in: set GMAT_CZML_REGEN=1 to overwrite the goldens with current output.
REGEN = bool(os.environ.get("GMAT_CZML_REGEN"))


# --- official-schema validator ------------------------------------------------------------


def _schema_resources() -> Iterator[tuple[str, Resource[Any]]]:
    """Every vendored schema file, keyed by its own ``$id`` so the relative ``$ref``s resolve."""
    for path in sorted(_SCHEMA_DIR.rglob("*.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        schema_id = contents.get("$id")
        if isinstance(schema_id, str):
            yield schema_id, Resource.from_contents(contents, default_specification=DRAFT7)


def czml_validator() -> Draft7Validator:
    """A draft-07 validator bound to the vendored official CZML schema (via ``Document.json``)."""
    registry: Registry[Any] = Registry().with_resources(_schema_resources())
    return Draft7Validator({"$ref": _DOCUMENT_SCHEMA_ID}, registry=registry)


# --- producer fixtures --------------------------------------------------------------------


def gmat_leo_dataframe() -> pd.DataFrame:
    """The committed real GMAT R2026a LEO ephemeris, read into the canonical state series.

    GMAT is not a runtime/CI dependency — the OEM is a committed byte fixture; orbit-formats
    reads it (EME2000 / UTC, Lagrange degree 5).
    """
    return cast(Ephemeris, of.read(_GMAT_OEM)).to_dataframe()


def skyfield_iss_dataframe() -> pd.DataFrame:
    """An ISS TLE propagated one orbit with Skyfield, as the canonical state series.

    Fully offline: ``builtin=True`` uses Skyfield's bundled timescale data, and an Earth-satellite
    GCRS position needs no JPL ephemeris. The committed TLE is propagated from near its own epoch;
    positions land in GCRS (tagged ``GCRF``), the frame orbit-formats and gmat-czml recognise.
    """
    from skyfield.api import EarthSatellite, load

    name, line1, line2 = _ISS_TLE.read_text(encoding="utf-8").splitlines()[:3]
    timescale = load.timescale(builtin=True)
    satellite = EarthSatellite(line1, line2, name.strip(), timescale)

    minutes = np.arange(0.0, 93.0, 3.0)
    times = timescale.utc(2024, 1, 9, 12, minutes)
    geocentric = satellite.at(times)
    position_km = np.asarray(geocentric.position.km, dtype=np.float64)
    velocity_kms = np.asarray(geocentric.velocity.km_per_s, dtype=np.float64)

    frame = pd.DataFrame(
        {
            "Epoch": pd.to_datetime(times.utc_datetime()).tz_localize(None),
            "X": position_km[0],
            "Y": position_km[1],
            "Z": position_km[2],
            "VX": velocity_kms[0],
            "VY": velocity_kms[1],
            "VZ": velocity_kms[2],
        }
    )
    frame.attrs.update(
        {
            "object_name": "ISS (ZARYA)",
            "central_body": "Earth",
            "coordinate_system": "GCRF",
            "time_scale": "UTC",
            "units": {"length": "km", "speed": "km/s", "angle": "deg", "time": "s"},
            "interpolation": "LAGRANGE",
            "interpolation_degree": 5,
        }
    )
    return frame


def gmat_leo_contacts() -> list[Contact]:
    """Two access windows from a ground station to the GMAT LEO, for the contacts path.

    A station placed at a real geodetic location (the Canberra DSN complex) with two windows inside
    the GMAT LEO span (2026-03-01 00:00 -> 01:36:40 UTC), so the link materialises and shows on the
    clock. The windows are illustrative placements, not a computed access solution — gmat-czml
    renders the contacts it is given; computing them is the producer's job (charter non-goal).
    """
    station = GroundStation(name="Canberra", latitude=-35.4014, longitude=148.9819, height=0.55)
    windows = [
        (
            dt.datetime(2026, 3, 1, 0, 10, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 3, 1, 0, 22, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2026, 3, 1, 1, 5, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 3, 1, 1, 17, tzinfo=dt.timezone.utc),
        ),
    ]
    return [Contact(observer=station, target="GmatLeo", windows=windows)]


def gmat_leo_maneuvers() -> list[Maneuver]:
    """One impulsive and one finite burn inside the GMAT LEO span, for the maneuver path.

    Both ignitions fall within the GMAT LEO span (2026-03-01 00:00 -> 01:36:40 UTC): an impulsive
    Δv at 00:30 and a 120 s finite burn at 01:00, with Δv in the burn's own RTN frame. The values
    are illustrative placements, not a computed maneuver plan — gmat-czml renders the maneuvers it
    is given; planning them is the producer's job.
    """
    return [
        Maneuver(
            epoch_ignition=np.datetime64("2026-03-01T00:30:00"),
            ref_frame="RTN",
            duration=0.0,
            delta_v=np.array([0.012, 0.0, 0.0]),
        ),
        Maneuver(
            epoch_ignition=np.datetime64("2026-03-01T01:00:00"),
            ref_frame="RTN",
            duration=120.0,
            delta_v=np.array([0.0, 0.006, 0.0]),
        ),
    ]


# --- the catalogue the goldens and the schema check share ---------------------------------

# Each entry is a golden filename -> a factory producing the document for that fixed input. The
# set spans both producers, the orbit-path and ground-track (multi-segment) paths, the contacts
# path (observer placement + per-window link), the maneuver path (impulsive marker + finite arc),
# and a multi-object document, so the goldens and the official-schema check cover the surface.
DOCUMENTS: dict[str, Callable[[], CzmlDocument]] = {
    "gmat-leo.czml": lambda: to_czml(gmat_leo_dataframe()),
    "gmat-leo-groundtrack.czml": lambda: to_czml(gmat_leo_dataframe(), ground_track=True),
    "gmat-leo-contacts.czml": lambda: to_czml(gmat_leo_dataframe(), contacts=gmat_leo_contacts()),
    "gmat-leo-maneuvers.czml": lambda: to_czml(
        gmat_leo_dataframe(), maneuvers=gmat_leo_maneuvers()
    ),
    "skyfield-iss.czml": lambda: to_czml(skyfield_iss_dataframe()),
    "skyfield-iss-groundtrack.czml": lambda: to_czml(skyfield_iss_dataframe(), ground_track=True),
    "multi-object.czml": lambda: to_czml(
        [gmat_leo_dataframe(), skyfield_iss_dataframe()], ground_track=True
    ),
}


# --- golden I/O ---------------------------------------------------------------------------


def golden_bytes(name: str) -> bytes:
    """The committed golden as raw bytes (byte-exact comparison; never newline-translated)."""
    return (GOLDEN_DIR / name).read_bytes()


def write_golden(name: str, document: CzmlDocument) -> None:
    """Overwrite a golden with current output, verbatim (used only under ``GMAT_CZML_REGEN``)."""
    GOLDEN_DIR.mkdir(exist_ok=True)
    (GOLDEN_DIR / name).write_bytes(document.to_json().encode("utf-8"))
