# Cesium ion upload

[Cesium ion](https://cesium.com/platform/cesium-ion/) hosts geospatial assets and streams them to
any Cesium client. The optional `[ion]` extra uploads a CZML document to ion as a hosted asset, so
instead of shipping a `.czml` around you hand out an asset id (or a dashboard link) that a viewer
loads with `IonResource.fromAssetId(id)`.

The upload is **token passthrough**: you supply a Cesium ion access token and gmat-czml forwards it
as a bearer credential and nothing more — it manages no ion account or authentication of its own.

## Install the extra

ion upload is the optional `[ion]` extra — [boto3](https://boto3.amazonaws.com/), which signs the S3
put that ion's upload flow hands back. A plain install never pulls it in:

```bash
pip install gmat-czml[ion]      # or: uv add 'gmat-czml[ion]'
```

Calling `upload_to_ion` without the extra raises a clear `ImportError` naming this install.

## Get an access token

Create a token in the [ion dashboard](https://ion.cesium.com/tokens) with **assets:write** (and
**assets:read** if you want the call to wait for processing). Pass it directly, or — for the CLI —
set it in the `CESIUM_ION_TOKEN` environment variable. Keep tokens out of source control.

## From Python

[`CzmlDocument.upload_to_ion`][gmat_czml.CzmlDocument.upload_to_ion] uploads the document and returns
an [`IonAsset`][gmat_czml.ion.IonAsset] describing the created asset:

```python
from orbit_formats import read
from gmat_czml import to_czml

trajectory = read("mission.oem")
asset = to_czml(trajectory, ground_track=True).upload_to_ion(token, name="Mission LEO")

print(asset.id)             # the numeric asset id a Cesium client loads by
print(asset.status)         # "COMPLETE" once ion has finished processing
print(asset.dashboard_url)  # where the asset is browsable on ion
```

`name` titles the asset and `description` is optional metadata. By default the call **waits** until
ion finishes processing the asset (so the returned `status` is `COMPLETE`); pass `wait=False` to
return as soon as the bytes are accepted, carrying whatever status ion reported then:

```python
asset = document.upload_to_ion(token, name="Mission LEO", description="v3 reentry", wait=False)
```

Load the uploaded asset in a Cesium client by its id:

```js
const resource = await Cesium.IonResource.fromAssetId(assetId);
viewer.dataSources.add(await Cesium.CzmlDataSource.load(resource));
```

## From the command line

`gmat-czml upload` reads a trajectory, assembles the same document `convert` would, and uploads it.
The token comes from `--token` or the `CESIUM_ION_TOKEN` environment variable; a missing token fails
before any document is built or any network call is made:

```bash
export CESIUM_ION_TOKEN=...                       # or pass --token
gmat-czml upload mission.oem --name "Mission LEO" --ground-track
```

On success it prints the asset id, status, and dashboard URL:

```text
gmat-czml: uploaded asset 1234567 (COMPLETE) — https://ion.cesium.com/assets/1234567
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | the trajectory to upload — any file orbit-formats can read |
| `--name NAME` | asset name on ion (default: the input file's base name) |
| `--description TEXT` | optional asset description |
| `--token TOKEN` | Cesium ion access token (falls back to `CESIUM_ION_TOKEN`) |
| `--no-wait` | return once the upload is accepted, without waiting for ion to finish processing |
| `--style`, `--playback-seconds`, `--ground-track` | the same rendering flags as [`convert`](cli.md) |

## Errors

An ion-side failure raises [`IonUploadError`][gmat_czml.errors.IonUploadError] (a `GmatCzmlError`) with a
message that names the cause — an HTTP error such as a `401` from a bad token, an asset that finishes
in an `ERROR` state, or a wait that times out. An empty token raises `ValueError` before any network
call. From the CLI each surfaces as a one-line `gmat-czml: …` message and a non-zero exit.
