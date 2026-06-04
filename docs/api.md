# API reference

The full public surface of `gmat_czml`. Every name here is importable from the top-level package
(for example `from gmat_czml import to_czml`).

## Conversion

::: gmat_czml.to_czml

## Documents

::: gmat_czml.CzmlDocument

## Input schema

The canonical input boundary — see the [schema reference](schema.md) for the contract these
validate.

::: gmat_czml.validate

::: gmat_czml.normalize_inputs

::: gmat_czml.recognised_frame

::: gmat_czml.CanonicalInput

## Styling

::: gmat_czml.Style

## Errors

Every error gmat-czml raises on purpose descends from `GmatCzmlError`; the schema-validation
failures additionally descend from `SchemaError`, which is also a `ValueError`.

::: gmat_czml.errors
