"""The optional ``[server]`` mode: serve a CZML document behind an embedded CesiumJS viewer.

A leaf module imported only when the server is actually used — by
:meth:`gmat_czml.CzmlDocument.serve` and the ``gmat-czml serve`` CLI subcommand — so importing
gmat-czml, and the base install, never
needs fastapi or uvicorn (they are the ``[server]`` extra). Calling ``.serve()`` without the extra
installed raises a clear :class:`ImportError` naming the install; that wrapping happens in the
callers, which is also why this module imports fastapi / uvicorn at the top: it is only reached once
the extra is present.

:func:`build_app` builds the FastAPI application — two routes, the embedded viewer at ``/`` and the
document JSON at ``/document.czml`` — and is what the tests drive without binding a socket.
:func:`serve` runs it under uvicorn (blocking until interrupted) and opens a browser. The viewer
page (``_viewer/index.html``, served verbatim) loads CesiumJS from a CDN and the document over http,
so the Web Workers CesiumJS needs load — a ``file://`` page cannot serve them.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import webbrowser
from functools import lru_cache
from importlib import resources

import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from gmat_czml.document import CzmlDocument

__all__ = ["build_app", "serve"]

# The document JSON is served at this path; the viewer fetches it relative to /.
_DOCUMENT_PATH = "/document.czml"


@lru_cache(maxsize=1)
def _viewer_html() -> str:
    """The embedded viewer page, read once from the packaged ``_viewer/index.html`` resource."""
    return (resources.files("gmat_czml") / "_viewer" / "index.html").read_text(encoding="utf-8")


def build_app(document: CzmlDocument) -> FastAPI:
    """Build the FastAPI app that serves ``document``.

    Two routes: ``GET /`` returns the embedded CesiumJS viewer page, and ``GET /document.czml``
    returns the document JSON — byte-for-byte what :meth:`~gmat_czml.CzmlDocument.to_json` produces.
    The document is snapshotted at build time, so the served bytes are stable for the app's life.
    """
    czml = document.to_json()
    html = _viewer_html()
    app = FastAPI(title="gmat-czml", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return html

    @app.get(_DOCUMENT_PATH)
    def czml_document() -> Response:
        return Response(content=czml, media_type="application/json")

    return app


def serve(
    document: CzmlDocument,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Serve ``document`` over http and (optionally) open the viewer in a browser.

    Runs uvicorn and blocks until interrupted (Ctrl-C). When ``open_browser`` is set, a browser tab
    for the viewer is opened shortly after the server starts; that is best-effort and silently does
    nothing in a headless environment.
    """
    app = build_app(document)
    url = f"http://{host}:{port}/"
    if open_browser:
        # Fire just after uvicorn has had a moment to bind, so the opened tab finds the server up.
        threading.Timer(0.7, lambda: _open_browser(url)).start()
    print(f"gmat-czml: serving on {url}  (press Ctrl-C to stop)", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _open_browser(url: str) -> None:
    """Open ``url`` in the default browser, ignoring any failure (e.g. a headless host)."""
    with contextlib.suppress(Exception):  # pragma: no cover - environment-dependent
        webbrowser.open(url)
