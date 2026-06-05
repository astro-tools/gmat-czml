"""App-level tests for the optional ``[server]`` mode (``gmat_czml.server``).

Drives :func:`gmat_czml.server.build_app` with fastapi's ``TestClient`` — no socket is bound — to
pin the two routes and the served-bytes identity: ``GET /`` returns the embedded CesiumJS viewer,
``GET /document.czml`` returns exactly what :meth:`~gmat_czml.CzmlDocument.to_json` produces (as
``application/json``), and an unknown path 404s. The live-server + real-browser exercise of the
served page is the ``browser``-marked ``tests/browser/test_server_render.py``.

The missing-``[server]``-extra path is checked here too — with fastapi forced absent,
:meth:`~gmat_czml.CzmlDocument.serve` must raise an :class:`ImportError` naming the install. These
are unmarked, so they run in the cross-platform ``test`` matrix (fastapi / httpx are dev deps).
"""

from __future__ import annotations

import sys

import pytest
from czml3 import CZML_VERSION, Document, Packet
from fastapi.testclient import TestClient

import gmat_czml
from gmat_czml import CzmlDocument
from gmat_czml.server import build_app


def _document() -> CzmlDocument:
    """A trivial two-packet document — enough to exercise the routes without real geometry."""
    preamble = Packet(id="document", name="srv-test", version=CZML_VERSION)
    satellite = Packet(id="Sat", name="Sat")
    return CzmlDocument(Document(packets=[preamble, satellite]))


def _client(document: CzmlDocument) -> TestClient:
    return TestClient(build_app(document))


# --- the two routes -----------------------------------------------------------------------


def test_index_serves_the_embedded_viewer() -> None:
    response = _client(_document()).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Cesium.js" in body  # the page loads CesiumJS
    assert "document.czml" in body  # and auto-loads the served document


def test_document_route_is_byte_identical_to_to_json() -> None:
    document = _document()
    response = _client(document).get("/document.czml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    # The served document is byte-for-byte what to_json() / save() produce, so the viewer animates
    # exactly the document a `convert` would have written.
    assert response.text == document.to_json()


def test_unknown_path_is_404() -> None:
    assert _client(_document()).get("/nope").status_code == 404


# --- the missing-extra contract -----------------------------------------------------------


def test_serve_without_the_extra_raises_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the [server] extra being absent: map "fastapi" to None so its import fails, and clear
    # the cached gmat_czml.server module *and its package attribute* so the lazy `from gmat_czml
    # import server` in CzmlDocument.serve re-executes (and fails on `import fastapi`) instead of
    # reusing the already-imported module. It must surface as an ImportError naming the install.
    monkeypatch.setitem(sys.modules, "fastapi", None)
    monkeypatch.delitem(sys.modules, "gmat_czml.server", raising=False)
    monkeypatch.delattr(gmat_czml, "server", raising=False)
    with pytest.raises(ImportError, match=r"gmat-czml\[server\]"):
        _document().serve(open_browser=False)
