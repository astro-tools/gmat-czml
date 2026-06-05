"""Optional, lazily-imported producer adapters.

gmat-czml's input contract is the canonical state-series schema (see :mod:`gmat_czml.schema`), so
any producer that yields it renders through :func:`gmat_czml.to_czml` with no adapter at all. The
adapters here exist only for the convenience of reaching that call in one hop from a producer's
*native* object, and each keeps its producer an **optional** dependency: the producer package is
imported inside the adapter's functions, never at module load, so importing gmat-czml — and the
minimal install — stays free of it.

- :mod:`gmat_czml.adapters.gmat_run` — turn a gmat-run ``Results`` into a CZML document.

This subpackage imports none of its modules eagerly; import the specific adapter you need.
"""

from __future__ import annotations

__all__: list[str] = []
