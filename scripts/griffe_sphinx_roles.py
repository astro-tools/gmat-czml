"""Griffe extension: render Sphinx cross-reference roles as plain inline code.

The gmat_czml source docstrings use reStructuredText cross-reference roles such as
``:class:`~gmat_czml.errors.SchemaError```. The mkdocstrings Google-style handler does not interpret
them, so without this extension they leak into the API reference verbatim, e.g. the reader sees
``:class:~gmat_czml.errors.SchemaError`` mid-sentence.

This rewrites every such role in a docstring to a clean inline-code span — the last dotted component
when the role used the ``~`` abbreviation marker, the full target otherwise — so the API reference
reads cleanly without modifying the source docstrings. It is docs-build tooling only; it is wired in
through ``mkdocs.yml`` under the mkdocstrings python handler.
"""

from __future__ import annotations

import re
from typing import Any

from griffe import Extension, Object

# A reST cross-reference role: :class:`~pkg.mod.Name`, :func:`pkg.fn`, :meth:`obj.method`, and the
# explicit-title form :class:`Title <pkg.mod.Name>`.
_ROLE = re.compile(r":(?:py:)?[a-z]+:`([^`]+)`")
_TITLE = re.compile(r".*<([^>]+)>$")


def _replace(match: re.Match[str]) -> str:
    inner = match.group(1).strip()
    abbreviated = inner.startswith("~")
    inner = inner.lstrip("~").strip()
    title = _TITLE.match(inner)
    target = title.group(1) if title else inner
    name = target.rsplit(".", 1)[-1] if abbreviated else target
    return f"`{name}`"


class SphinxRoles(Extension):
    """Rewrite reST cross-reference roles in every docstring to plain inline code."""

    def on_instance(self, *, obj: Object, **kwargs: Any) -> None:
        if obj.docstring is not None:
            obj.docstring.value = _ROLE.sub(_replace, obj.docstring.value)
