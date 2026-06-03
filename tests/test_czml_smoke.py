"""CZML validation smoke test.

A minimal structural check that the czml3 backend produces a well-formed document — a JSON array
whose first packet is the document preamble carrying the CZML version. The full official-CZML-schema
validation and the golden corpus land with the validation-harness work; this is the placeholder the
``czml-validate`` CI job runs against.
"""

from __future__ import annotations

import json

import pytest
from czml3 import CZML_VERSION, Document, Packet

pytestmark = pytest.mark.czml


def _trivial_document() -> Document:
    preamble = Packet(id="document", name="gmat-czml smoke", version=CZML_VERSION)
    satellite = Packet(id="sat", name="Sat")
    return Document(packets=[preamble, satellite])


def test_document_serializes_to_a_json_array() -> None:
    payload = json.loads(_trivial_document().dumps())
    assert isinstance(payload, list)
    assert len(payload) == 2


def test_first_packet_is_the_document_preamble() -> None:
    payload = json.loads(_trivial_document().dumps())
    assert payload[0]["id"] == "document"
    assert payload[0]["version"] == CZML_VERSION
