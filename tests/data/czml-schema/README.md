# Vendored official CZML JSON schema

This directory is the official CZML JSON schema, vendored verbatim so the
validation harness can check every emitted document against it offline (no
network at test time). It is **third-party material**, not part of the
gmat-czml package, and is used only by the test suite.

## Provenance

- **Source:** [`AnalyticalGraphicsInc/czml-writer`](https://github.com/AnalyticalGraphicsInc/czml-writer), `Schema/` directory — the canonical CZML schema CesiumGS maintains and validates its own examples against (the upstream `Schema/validate.js` runs these files through Ajv).
- **Pinned commit:** `7d37f31846c05c5931b205f6434f9bd275587c0e`
- **License:** Apache-2.0 (Copyright Ansys Government Initiatives (AGI) and Contributors) — see `LICENSE.md` in this directory.
- **Draft:** JSON Schema draft-07 (`$schema` on every file).

## What was copied

The `Schema/` tree was copied verbatim **except**:

- `Schema/Examples/` — example documents referenced only by the non-standard
  `czmlExamples` annotation keyword (not via `$ref`), so they are not needed for
  validation.
- `package.json` — the upstream npm/Ajv tooling manifest, not a schema.

Nothing else was modified. Each file keeps its absolute `$id`
(`https://analyticalgraphicsinc.github.io/czml-writer/Schema/...`); the harness
registers every file under its `$id` so the relative `$ref`s between files
resolve. The validation entry point is `Document.json`.

## Updating

Re-copy the `Schema/` tree from a newer upstream commit and update the pinned
commit above. The golden corpus is regenerated deliberately when this schema or
the `czml3` pin changes; a schema bump that newly rejects existing output is a
signal to investigate, not to silence.
