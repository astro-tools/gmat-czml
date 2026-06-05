"""The :class:`CzmlDocument` wrapper over a czml3 ``Document``.

The object :func:`gmat_czml.to_czml` returns. It is an in-memory-first handle on the assembled
CZML: :meth:`~CzmlDocument.to_dict` and :meth:`~CzmlDocument.to_json` produce the whole document
without ever touching disk (the downstream consumer needs it as a dict / string, not only as a
file), and :meth:`~CzmlDocument.save` writes exactly what :meth:`~CzmlDocument.to_json` returns.
:meth:`~CzmlDocument.serve` hosts it over http behind an embedded CesiumJS viewer; that path needs
the optional ``[server]`` extra, imported lazily so the base install stays free of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from czml3 import Document

if TYPE_CHECKING:
    from gmat_czml.ion import IonAsset

__all__ = ["CzmlDocument"]

# Raised (as the message of a re-wrapped ImportError) when .serve() is called without the optional
# [server] extra installed. Names the install so the failure is actionable.
_SERVER_INSTALL_HINT = (
    "serving needs the optional '[server]' extra (fastapi + uvicorn), which is not installed; "
    "install it with `pip install gmat-czml[server]` (or `uv add 'gmat-czml[server]'`)"
)

# The same, for .upload_to_ion() without the optional [ion] extra (boto3) installed.
_ION_INSTALL_HINT = (
    "uploading to Cesium ion needs the optional '[ion]' extra (boto3), which is not installed; "
    "install it with `pip install gmat-czml[ion]` (or `uv add 'gmat-czml[ion]'`)"
)


class CzmlDocument:
    """A handle on an assembled CZML document.

    Wraps the czml3 :class:`~czml3.Document` the converters produce. The three accessors are the
    public surface:

    - :meth:`to_json` — the document as a CZML JSON string;
    - :meth:`to_dict` — the same document as parsed JSON (CZML's top level is a JSON *array* of
      packets, so this is a ``list``);
    - :meth:`save` — write the JSON to a file, byte-for-byte identical to :meth:`to_json`.

    The wrapped czml3 object is available as :attr:`document` for callers that need the model.
    """

    def __init__(self, document: Document) -> None:
        self._document = document

    @property
    def document(self) -> Document:
        """The wrapped czml3 :class:`~czml3.Document`."""
        return self._document

    def to_json(self) -> str:
        """The document as a CZML JSON string — a JSON array whose first element is the preamble."""
        return self._document.dumps()

    def to_dict(self) -> list[Any]:
        """The document as a list of packet dicts, parsed from :meth:`to_json`.

        Parsing the serialized JSON (rather than walking the model) guarantees the dict form and
        the string form describe exactly the same document.
        """
        parsed: list[Any] = json.loads(self.to_json())
        return parsed

    def save(self, path: str | Path) -> Path:
        """Write the document to ``path`` (UTF-8) and return the path it was written to.

        The file holds exactly what :meth:`to_json` returns — no trailing newline is added — so a
        saved document and an in-memory ``to_json()`` are byte-for-byte identical.
        """
        destination = Path(path)
        destination.write_text(self.to_json(), encoding="utf-8")
        return destination

    def serve(
        self,
        port: int = 8080,
        *,
        host: str = "127.0.0.1",
        open_browser: bool = True,
    ) -> None:
        """Serve this document over http behind an embedded CesiumJS viewer, blocking until stopped.

        Hosts a small FastAPI app — the viewer page at ``/`` and this document's JSON at
        ``/document.czml`` — and runs it under uvicorn, so the viewer's CesiumJS loads the document
        over http (a ``file://`` page cannot, its Web Workers are blocked). Blocks until interrupted
        (Ctrl-C). When ``open_browser`` is set, a browser tab is opened once the server is up.

        Requires the optional ``[server]`` extra (``pip install gmat-czml[server]``); without it,
        this raises :class:`ImportError` with an actionable install hint.
        """
        try:
            from gmat_czml import server
        except ImportError as exc:  # the [server] extra (fastapi / uvicorn) is not installed
            raise ImportError(_SERVER_INSTALL_HINT) from exc
        server.serve(self, host=host, port=port, open_browser=open_browser)

    def upload_to_ion(
        self,
        token: str,
        *,
        name: str,
        description: str = "",
        wait: bool = True,
    ) -> IonAsset:
        """Upload this document to Cesium ion as a hosted asset and return a reference to it.

        Forwards ``token`` to ion as a bearer credential and nothing more — token passthrough, no
        ion authentication is managed here. ``name`` titles the asset, ``description`` is optional
        metadata, and ``wait`` (the default) blocks until ion finishes processing the asset, while
        ``wait=False`` returns as soon as the upload is accepted. Returns an
        :class:`~gmat_czml.ion.IonAsset` carrying the new asset's id and status.

        Requires the optional ``[ion]`` extra (``pip install gmat-czml[ion]``); without it, this
        raises :class:`ImportError` with an actionable install hint. An ion-side failure (a bad
        token, a processing error, a timeout) raises :class:`~gmat_czml.errors.IonUploadError`.
        """
        try:
            from gmat_czml import ion
        except ImportError as exc:  # the [ion] extra (boto3) is not installed
            raise ImportError(_ION_INSTALL_HINT) from exc
        return ion.upload(self.to_json(), token, name=name, description=description, wait=wait)
