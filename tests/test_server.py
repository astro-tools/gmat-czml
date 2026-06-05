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
import threading
from collections.abc import Callable
from typing import Any

import pytest
import uvicorn
from czml3 import CZML_VERSION, Document, Packet
from fastapi import FastAPI
from fastapi.testclient import TestClient

import gmat_czml
from gmat_czml import CzmlDocument, server
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


# --- the serve() orchestration ------------------------------------------------------------
#
# build_app and its routes are exercised above with the TestClient; serve() is the surrounding
# orchestration — build the app, wire the bind into uvicorn, and (optionally) schedule a browser
# open. The live socket + real browser path is the browser-marked test_server_render.py, so here we
# mock the two seams (uvicorn.run, which would otherwise block; threading.Timer, which would
# otherwise spawn a real 0.7s thread) and assert the wiring, without binding anything.


class _Recorder:
    """A ``threading.Timer`` stand-in: records the schedule and never spawns a real thread.

    ``serve`` schedules the browser open as ``threading.Timer(0.7, ...).start()``. Swapping the real
    Timer for this keeps the test synchronous — no background thread fires ``webbrowser.open`` after
    the test returns — while recording that the open was scheduled and started.
    """

    def __init__(self, interval: float, function: Callable[[], object]) -> None:
        self.interval = interval
        self.function = function
        self.started = False

    def start(self) -> None:
        self.started = True


def _install_fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``uvicorn.run`` with a recorder so ``serve`` returns instead of blocking."""
    captured: dict[str, Any] = {}

    def _run(app: Any, *, host: str, port: int, log_level: str) -> None:
        captured.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr(uvicorn, "run", _run)
    return captured


def _install_fake_timer(monkeypatch: pytest.MonkeyPatch) -> list[_Recorder]:
    """Replace ``threading.Timer`` with a recorder so no real browser-open thread is spawned."""
    timers: list[_Recorder] = []

    def _make(interval: float, function: Callable[[], object]) -> _Recorder:
        timer = _Recorder(interval, function)
        timers.append(timer)
        return timer

    monkeypatch.setattr(threading, "Timer", _make)
    return timers


def test_serve_runs_uvicorn_with_the_built_app(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_uvicorn(monkeypatch)
    timers = _install_fake_timer(monkeypatch)

    server.serve(_document(), host="0.0.0.0", port=9999, open_browser=True)

    # serve() hands build_app's FastAPI app to uvicorn.run, with the requested bind.
    assert isinstance(captured["app"], FastAPI)
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9999
    # And it schedules (and starts) a browser open just after the server comes up.
    assert len(timers) == 1
    assert timers[0].started


def test_serve_schedules_no_browser_open_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_uvicorn(monkeypatch)
    timers = _install_fake_timer(monkeypatch)

    server.serve(_document(), open_browser=False)

    assert captured["host"] == "127.0.0.1"  # the default bind still reaches uvicorn
    assert timers == []  # but with the browser open suppressed, no timer is scheduled


def test_document_serve_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    # CzmlDocument.serve is a thin wrapper over the lazily-imported server.serve: it must forward
    # this document and the bind kwargs through unchanged.
    captured: dict[str, Any] = {}

    def _record(document: CzmlDocument, *, host: str, port: int, open_browser: bool) -> None:
        captured.update(document=document, host=host, port=port, open_browser=open_browser)

    monkeypatch.setattr(server, "serve", _record)
    document = _document()
    document.serve(port=9001, host="0.0.0.0", open_browser=False)

    assert captured == {
        "document": document,
        "host": "0.0.0.0",
        "port": 9001,
        "open_browser": False,
    }
