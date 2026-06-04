"""Official-CZML-schema validation of every emitted document.

Each producer's output — the real GMAT R2026a LEO ephemeris and the Skyfield TLE propagation —
and its orbit-path / ground-track / multi-object variants validate against the *official* CesiumGS
CZML JSON schema vendored under ``tests/data/czml-schema/``. This is the ``czml-validate`` CI job:
it replaces the scaffold's structural smoke check with the real spec, exercised on real producers,
and is independent of czml3 (the library that emits the document).

``test_validator_rejects_malformed_czml`` guards the harness itself — a registry/ref-resolution
regression that turned validation into a no-op would otherwise let everything pass vacuously.
"""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft7Validator

from _harness import DOCUMENTS

pytestmark = pytest.mark.czml


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_emitted_document_validates_against_official_schema(
    name: str, czml_validator: Draft7Validator
) -> None:
    payload = DOCUMENTS[name]().to_dict()
    errors = sorted(czml_validator.iter_errors(payload), key=lambda error: str(error.json_path))
    assert not errors, "official-schema violations in {}:\n{}".format(
        name, "\n".join(f"  @ {error.json_path}: {error.message}" for error in errors)
    )


def test_validator_rejects_malformed_czml(czml_validator: Draft7Validator) -> None:
    payload = DOCUMENTS["gmat-leo.czml"]().to_dict()
    assert not list(czml_validator.iter_errors(payload))  # the unmodified document is valid

    broken = copy.deepcopy(payload)
    broken[0]["clock"]["multiplier"] = "not-a-number"  # the schema requires a number
    assert list(czml_validator.iter_errors(broken))
