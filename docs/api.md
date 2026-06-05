# API reference

The full public surface of `gmat_czml`. Every name here is importable from the top-level package
(for example `from gmat_czml import to_czml`).

## Conversion

::: gmat_czml.to_czml

## Documents

::: gmat_czml.CzmlDocument

## Server mode

Hosting a document over http behind an embedded CesiumJS viewer — see the
[server mode guide](server.md). The entry point is
[`CzmlDocument.serve`][gmat_czml.CzmlDocument.serve], documented on `CzmlDocument` above.

## Cesium ion upload

Uploading a document to Cesium ion as a hosted asset — see the
[ion upload guide](ion.md). The entry point is
[`CzmlDocument.upload_to_ion`][gmat_czml.CzmlDocument.upload_to_ion]; it returns the `IonAsset`
below, which lives in the `gmat_czml.ion` submodule (it is a return value, not a top-level export).

::: gmat_czml.ion.IonAsset

## Input schema

The canonical input boundary — see the [schema reference](schema.md) for the contract these
validate.

::: gmat_czml.validate

::: gmat_czml.normalize_inputs

::: gmat_czml.recognised_frame

::: gmat_czml.CanonicalInput

## Contacts

The contact record gmat-czml owns — an observer's placement and the access windows it sees a
satellite over. See the [contacts conversion](conversion/contacts.md) for what each becomes in CZML.

::: gmat_czml.GroundStation

::: gmat_czml.Contact

## Styling

::: gmat_czml.Style

::: gmat_czml.PointStyle

::: gmat_czml.ImageBillboard

::: gmat_czml.LabelStyle

::: gmat_czml.PathStyle

::: gmat_czml.TrackStyle

::: gmat_czml.LineStyle

::: gmat_czml.ManeuverStyle

::: gmat_czml.ContactStyle

::: gmat_czml.AttitudeStyle

::: gmat_czml.preset

## Errors

Every error gmat-czml raises on purpose descends from `GmatCzmlError`; the schema-validation
failures additionally descend from `SchemaError`, which is also a `ValueError`.

::: gmat_czml.errors

## gmat-run adapter

The optional one-hop bridge from a gmat-run `Results` to a document — see the
[gmat-run adapter guide](conversion/gmat-run-adapter.md). It lives in its own module because
gmat-run is an optional dependency, imported only inside these functions.

::: gmat_czml.adapters.gmat_run
