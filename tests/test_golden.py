"""Golden-output regression: fixed inputs reproduce the reference CZML.

The committed goldens under ``tests/data/golden/`` are the drift detector for the ``czml3`` (and
``skyfield``) pins — :func:`gmat_czml.to_czml` on each fixed producer fixture must reproduce them.

The comparison is **byte-exact first**. Only on a byte mismatch does it fall back to a structural
compare that forgives a sub-ULP floating-point difference: the inertial->fixed rotation and the
geodetic projection use transcendentals (``arctan2`` / ``sin`` / ``cos``) that are not
correctly-rounded and select CPU-dependent code paths, so a ground-track longitude can differ by
~1 ULP — sub-nanometre on the ground — between runner microarchitectures. Any structural change, or
a numeric change beyond a few ULP, still fails. The orbit-path goldens use only correctly-rounded
operations (scaling, ``sqrt``-based decimation) and stay byte-exact on every platform.

Regenerate deliberately with ``GMAT_CZML_REGEN=1`` when a pin changes; the goldens carry ``-text``
in ``.gitattributes`` so the byte comparison survives CRLF normalisation on every platform.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from _harness import DOCUMENTS, REGEN, golden_bytes, write_golden

pytestmark = pytest.mark.czml

# Cross-architecture last-ULP tolerance for the transcendental-derived values. The observed drift is
# a single ULP; these bounds are ~1e3x above that noise floor yet ~1e6x below any real change (a
# dependency-behaviour or geometry change moves values far more), and physically negligible —
# 1e-9 deg is ~0.1 mm of ground track, 1e-9 m is a nanometre. They apply only on a byte mismatch.
_REL_TOL = 1e-12
_ABS_TOL = 1e-9


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_output_matches_golden(name: str) -> None:
    document = DOCUMENTS[name]()
    if REGEN:
        write_golden(name, document)
        pytest.skip(f"regenerated golden {name}")

    emitted = document.to_json().encode("utf-8")
    golden = golden_bytes(name)
    if emitted == golden:
        return  # byte-identical: the common, strict path

    difference = _first_difference(json.loads(emitted), json.loads(golden), "$")
    assert difference is None, (
        f"{name} differs from its golden beyond floating-point tolerance: {difference}"
    )


def _first_difference(emitted: Any, golden: Any, path: str) -> str | None:
    """The first structural or out-of-tolerance numeric difference, or ``None`` if equivalent.

    Walks the two parsed CZML documents in lockstep: dict keys and list lengths must match exactly,
    strings and other scalars must be equal, and numbers must agree to within the last-ULP tolerance
    (so cross-architecture float drift is forgiven but any meaningful change is reported, with the
    JSON path to it).
    """
    if isinstance(emitted, bool) or isinstance(golden, bool):
        return None if emitted == golden else f"{path}: {emitted!r} != {golden!r}"
    if isinstance(emitted, (int, float)) and isinstance(golden, (int, float)):
        if math.isclose(emitted, golden, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
            return None
        return f"{path}: {emitted!r} != {golden!r}"
    if isinstance(emitted, dict) and isinstance(golden, dict):
        if emitted.keys() != golden.keys():
            return f"{path}: keys {sorted(emitted)} != {sorted(golden)}"
        for key in golden:
            sub = _first_difference(emitted[key], golden[key], f"{path}.{key}")
            if sub is not None:
                return sub
        return None
    if isinstance(emitted, list) and isinstance(golden, list):
        if len(emitted) != len(golden):
            return f"{path}: length {len(emitted)} != {len(golden)}"
        for index, (item_e, item_g) in enumerate(zip(emitted, golden, strict=True)):
            sub = _first_difference(item_e, item_g, f"{path}[{index}]")
            if sub is not None:
                return sub
        return None
    return None if emitted == golden else f"{path}: {emitted!r} != {golden!r}"
