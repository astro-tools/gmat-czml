"""The optional ``[ion]`` mode: upload an assembled CZML document to Cesium ion as a hosted asset.

A leaf module imported only when an upload is actually requested — by
:meth:`gmat_czml.CzmlDocument.upload_to_ion` and the ``gmat-czml upload`` CLI subcommand — so
importing gmat-czml, and the base install, never needs boto3 (it is the ``[ion]`` extra). Calling
``.upload_to_ion()`` without the extra installed raises a clear :class:`ImportError` naming the
install; that wrapping happens in the caller, which is also why this module imports boto3 at the
top: it is only reached once the extra is present.

The upload is **token passthrough**: the caller supplies a Cesium ion access token and gmat-czml
does nothing with it but forward it as a bearer credential — it manages no ion authentication of its
own. The flow is ion's four-step REST upload: create the asset (``POST /v1/assets``), put the
document bytes at the returned S3 location, notify ion the upload is complete, and (optionally) poll
the asset until it reports ``COMPLETE``. Only the S3 put needs boto3; the three REST calls use the
standard library, so the bytes-signing AWS SDK is the only dependency the extra adds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3

from gmat_czml.errors import IonUploadError

__all__ = ["IonAsset", "upload"]

# Cesium ion's REST root and the asset shape for a CZML document. A CZML is vector data ion serves
# as-is (no tiling), so both the asset type and its source type are CZML. The network is mocked in
# the tests, so these are not exercised against the live API there.
_ION_API_ROOT = "https://api.cesium.com/v1"
_ASSET_TYPE = "CZML"
_SOURCE_TYPE = "CZML"

# The document is uploaded under a fixed source filename within the ion-provided key prefix, so an
# arbitrary asset name (spaces, slashes) never has to be a valid S3 key.
_SOURCE_FILENAME = "document.czml"

# The ion dashboard an uploaded asset is browsable at (the returned reference's human URL).
_DASHBOARD_ROOT = "https://ion.cesium.com/assets"

# Asset states from GET /v1/assets/{id}: one success, two terminal failures.
_STATUS_COMPLETE = "COMPLETE"
_STATUS_ERRORS = frozenset({"ERROR", "DATA_ERROR"})

# Defaults for the wait-until-complete poll loop.
_DEFAULT_POLL_INTERVAL = 2.0
_DEFAULT_TIMEOUT = 300.0


@dataclass(frozen=True)
class IonAsset:
    """A reference to an asset created on Cesium ion.

    Returned by :func:`upload`. ``id`` is ion's numeric asset id — the handle a Cesium client loads
    the asset by (``IonResource.fromAssetId(id)``); ``status`` is the asset's processing state when
    the upload call returned (``COMPLETE`` when it waited for processing, otherwise whatever ion
    reported once the bytes were accepted). :attr:`dashboard_url` is where the asset is browsable in
    the ion dashboard.
    """

    id: int
    name: str
    type: str
    status: str

    @property
    def dashboard_url(self) -> str:
        """The ion dashboard URL the asset is browsable at."""
        return f"{_DASHBOARD_ROOT}/{self.id}"


def upload(
    czml: str,
    token: str,
    *,
    name: str,
    description: str = "",
    wait: bool = True,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> IonAsset:
    """Upload a CZML document to Cesium ion and return a reference to the created asset.

    ``czml`` is the document JSON (what :meth:`gmat_czml.CzmlDocument.to_json` produces); ``token``
    is a Cesium ion access token, forwarded as a bearer credential and nothing more (token
    passthrough — gmat-czml manages no ion authentication). ``name`` titles the asset, and
    ``description`` is optional asset metadata.

    Runs ion's four-step REST upload: create the asset, put the bytes at the returned S3 location,
    notify ion the upload is complete, and — when ``wait`` is set — poll the asset until it reports
    ``COMPLETE`` (giving up after ``timeout`` seconds, sleeping ``poll_interval`` between polls).
    With ``wait=False`` the call returns as soon as the bytes are accepted, carrying whatever status
    ion reported then.

    Raises :class:`ValueError` for an empty token (before any network call), and
    :class:`~gmat_czml.errors.IonUploadError` for an ion-side failure: an HTTP error (e.g. a ``401``
    from a bad token), an asset that lands in an ``ERROR`` / ``DATA_ERROR`` state, or a wait that
    times out.
    """
    if not token:
        raise ValueError("a non-empty Cesium ion access token is required")

    created = _post_json(
        f"{_ION_API_ROOT}/assets",
        token,
        {
            "name": name,
            "description": description,
            "type": _ASSET_TYPE,
            "options": {"sourceType": _SOURCE_TYPE},
        },
    )
    metadata = created["assetMetadata"]
    asset_id = int(metadata["id"])
    upload_location = created["uploadLocation"]
    on_complete = created["onComplete"]

    _s3_put(upload_location, f"{upload_location['prefix']}{_SOURCE_FILENAME}", czml.encode("utf-8"))
    _post_json(on_complete["url"], token, on_complete.get("fields", {}))

    status = str(metadata.get("status", ""))
    if wait:
        status = _wait_until_complete(asset_id, token, poll_interval=poll_interval, timeout=timeout)

    return IonAsset(
        id=asset_id, name=name, type=str(metadata.get("type", _ASSET_TYPE)), status=status
    )


def _wait_until_complete(asset_id: int, token: str, *, poll_interval: float, timeout: float) -> str:
    """Poll the asset until it reports ``COMPLETE``; raise :class:`IonUploadError` otherwise.

    Polls ``GET /v1/assets/{id}`` until the status is ``COMPLETE`` (returned) or a terminal
    ``ERROR`` / ``DATA_ERROR`` (raised), sleeping ``poll_interval`` seconds between polls and giving
    up after ``timeout`` seconds. The first poll happens immediately; the deadline is measured on a
    monotonic clock so it is unaffected by wall-clock changes.
    """
    deadline = monotonic() + timeout
    url = f"{_ION_API_ROOT}/assets/{asset_id}"
    while True:
        asset = _get_json(url, token)
        status = str(asset.get("status") or asset.get("assetMetadata", {}).get("status", ""))
        if status == _STATUS_COMPLETE:
            return status
        if status in _STATUS_ERRORS:
            raise IonUploadError(f"asset {asset_id} finished in state {status}")
        if monotonic() >= deadline:
            raise IonUploadError(
                f"asset {asset_id} did not reach {_STATUS_COMPLETE} within {timeout:g}s "
                f"(last status {status or 'unknown'})"
            )
        sleep(poll_interval)


def _s3_put(upload_location: dict[str, Any], key: str, data: bytes) -> None:
    """Upload ``data`` to the ion-provided S3 location under ``key`` with its temporary credentials.

    ``upload_location`` is ion's ``uploadLocation`` block — the bucket, key prefix, and short-lived
    access key / secret / session token gmat-czml forwards straight to boto3 (it mints no
    credentials of its own). The ``endpoint`` is honoured when ion supplies one.
    """
    client: Any = boto3.client(
        "s3",
        aws_access_key_id=upload_location["accessKey"],
        aws_secret_access_key=upload_location["secretAccessKey"],
        aws_session_token=upload_location["sessionToken"],
        region_name=upload_location.get("region", "us-east-1"),
        endpoint_url=upload_location.get("endpoint"),
    )
    client.put_object(Bucket=upload_location["bucket"], Key=key, Body=data)


def _post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST ``payload`` as JSON to ``url`` with a bearer token, returning the parsed JSON body."""
    return _request("POST", url, token, payload)


def _get_json(url: str, token: str) -> dict[str, Any]:
    """GET ``url`` with a bearer token, returning the parsed JSON body."""
    return _request("GET", url, token, None)


def _request(method: str, url: str, token: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Issue an ion REST request with a bearer token and return the parsed JSON body.

    The single HTTP seam for the three REST calls (create / complete / status). Raises
    :class:`IonUploadError` for an HTTP error status — the message names the code, so an invalid
    token's ``401`` surfaces as a typed, actionable failure rather than a raw traceback — and for a
    transport-level failure; an empty body parses to ``{}`` (the upload-complete call returns none).
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method)) as response:
            body: bytes = response.read()
    except HTTPError as exc:
        raise IonUploadError(f"{method} {url} returned {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise IonUploadError(f"{method} {url} failed: {exc.reason}") from exc
    if not body:
        return {}
    parsed: dict[str, Any] = json.loads(body)
    return parsed
