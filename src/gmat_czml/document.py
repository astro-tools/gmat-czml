"""The :class:`CzmlDocument` wrapper over a czml3 ``Document``.

The object :func:`gmat_czml.to_czml` returns. It is an in-memory-first handle on the assembled
CZML: :meth:`~CzmlDocument.to_dict` and :meth:`~CzmlDocument.to_json` produce the whole document
without ever touching disk (the downstream consumer needs it as a dict / string, not only as a
file), and :meth:`~CzmlDocument.save` writes exactly what :meth:`~CzmlDocument.to_json` returns.
Serving the document over HTTP is a later release.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from czml3 import Document

__all__ = ["CzmlDocument"]


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
