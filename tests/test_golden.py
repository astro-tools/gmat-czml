"""Golden-output regression: fixed inputs produce byte-identical CZML.

The committed goldens under ``tests/data/golden/`` are the drift detector for the ``czml3`` (and
``skyfield``) pins — :func:`gmat_czml.to_czml` on each fixed producer fixture must reproduce them
byte-for-byte. Regenerate deliberately with ``GMAT_CZML_REGEN=1`` when a pin changes; the goldens
carry ``-text`` in ``.gitattributes`` so the byte comparison survives CRLF normalisation on every
platform.
"""

from __future__ import annotations

import pytest

from _harness import DOCUMENTS, REGEN, golden_bytes, write_golden

pytestmark = pytest.mark.czml


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_output_matches_golden(name: str) -> None:
    document = DOCUMENTS[name]()
    if REGEN:
        write_golden(name, document)
        pytest.skip(f"regenerated golden {name}")
    assert document.to_json().encode("utf-8") == golden_bytes(name)
