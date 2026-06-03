"""Tests for the :class:`~gmat_czml.document.CzmlDocument` wrapper.

The wrapper's contract is the in-memory-first triple: ``to_json`` / ``to_dict`` describe the same
document, and ``save`` writes that JSON to disk byte-for-byte identically.
"""

from __future__ import annotations

import json
from pathlib import Path

from czml3 import CZML_VERSION, Document, Packet

from gmat_czml.document import CzmlDocument


def _wrapped() -> CzmlDocument:
    """A wrapper around a trivial two-packet document."""
    preamble = Packet(id="document", name="test", version=CZML_VERSION)
    satellite = Packet(id="sat", name="Sat")
    return CzmlDocument(Document(packets=[preamble, satellite]))


def test_to_json_is_a_json_array_string() -> None:
    payload = json.loads(_wrapped().to_json())
    assert isinstance(payload, list)
    assert payload[0]["id"] == "document"


def test_to_dict_matches_to_json() -> None:
    doc = _wrapped()
    assert doc.to_dict() == json.loads(doc.to_json())


def test_save_is_byte_identical_to_to_json(tmp_path: Path) -> None:
    doc = _wrapped()
    written = doc.save(tmp_path / "out.czml")
    assert written == tmp_path / "out.czml"
    assert written.read_text(encoding="utf-8") == doc.to_json()
    assert written.read_bytes() == doc.to_json().encode("utf-8")


def test_save_accepts_a_string_path(tmp_path: Path) -> None:
    doc = _wrapped()
    written = doc.save(str(tmp_path / "as-str.czml"))
    assert written.read_text(encoding="utf-8") == doc.to_json()


def test_document_property_exposes_the_wrapped_model() -> None:
    model = Document(packets=[Packet(id="document", name="test", version=CZML_VERSION)])
    assert CzmlDocument(model).document is model
