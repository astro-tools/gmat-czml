"""Tests for the optional ``[ion]`` upload helper (``gmat_czml.ion``).

The helper runs Cesium ion's four-step REST upload (create asset → S3 put → notify complete → poll
until COMPLETE). Every test here **mocks the network boundary** — ``urlopen`` is replaced with a
fake that routes by method + URL across the three REST endpoints, and ``boto3.client`` with a fake
S3 client that records the put — so no socket opens, no AWS call is made, and no token is needed.
The poll loop's clock (``monotonic`` / ``sleep``) is mocked too, so the timeout test is
deterministic and nothing actually sleeps.

Unmarked (not ``czml`` / ``browser``), so they run in the cross-platform ``test`` matrix (boto3 is a
dev dep). The missing-``[ion]``-extra path is checked with boto3 forced absent.
"""

from __future__ import annotations

import json
import sys
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import boto3
import pytest
from czml3 import CZML_VERSION, Document, Packet

import gmat_czml
from gmat_czml import CzmlDocument, ion
from gmat_czml.errors import IonUploadError


def _document() -> CzmlDocument:
    """A trivial two-packet document — enough to exercise the upload without real geometry."""
    preamble = Packet(id="document", name="ion-test", version=CZML_VERSION)
    return CzmlDocument(Document(packets=[preamble, Packet(id="Sat", name="Sat")]))


class _FakeResponse:
    """A minimal stand-in for an ``http.client.HTTPResponse`` context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeIon:
    """Routes the three ion REST calls by method + URL, recording every request it answers.

    ``create_status`` is the status returned in the create response (what a ``wait=False`` upload
    reports); ``statuses`` is the sequence the status poll walks through (the last repeats), so an
    ``("IN_PROGRESS", "COMPLETE")`` drives one in-progress poll then completion.
    """

    def __init__(
        self,
        asset_id: int = 42,
        statuses: tuple[str, ...] = ("COMPLETE",),
        create_status: str = "AWAITING_FILES",
        asset_type: str = "CZML",
    ) -> None:
        self.asset_id = asset_id
        self.statuses = statuses
        self.create_status = create_status
        self.asset_type = asset_type
        self.requests: list[dict[str, Any]] = []
        self._poll = 0

    def urlopen(self, request: Any) -> _FakeResponse:
        payload = json.loads(request.data) if request.data else None
        self.requests.append(
            {
                "method": request.method,
                "url": request.full_url,
                "auth": request.headers.get("Authorization"),
                "payload": payload,
            }
        )
        url = request.full_url
        if request.method == "POST" and url.endswith("/v1/assets"):
            return _FakeResponse(self._create_body())
        if request.method == "POST" and url.endswith("/uploadComplete"):
            return _FakeResponse(b"")
        if request.method == "GET" and url.endswith(f"/v1/assets/{self.asset_id}"):
            status = self.statuses[min(self._poll, len(self.statuses) - 1)]
            self._poll += 1
            return _FakeResponse(json.dumps({"id": self.asset_id, "status": status}).encode())
        raise AssertionError(f"unexpected request: {request.method} {url}")

    def _create_body(self) -> bytes:
        return json.dumps(
            {
                "assetMetadata": {
                    "id": self.asset_id,
                    "name": "orbit",
                    "type": self.asset_type,
                    "status": self.create_status,
                },
                "uploadLocation": {
                    "bucket": "assets.cesium.com",
                    "prefix": f"sources/{self.asset_id}/",
                    "accessKey": "AK",
                    "secretAccessKey": "SK",
                    "sessionToken": "ST",
                    "endpoint": "https://s3.amazonaws.com",
                },
                "onComplete": {
                    "method": "POST",
                    "url": f"https://api.cesium.com/v1/assets/{self.asset_id}/uploadComplete",
                    "fields": {},
                },
            }
        ).encode()


class _FakeS3:
    """Records ``put_object`` calls and the credentials the client was built with."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []
        self.client_kwargs: dict[str, Any] = {}

    def client(self, service: str, **kwargs: Any) -> _FakeS3:
        assert service == "s3"
        self.client_kwargs = kwargs
        return self

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeIon, s3: _FakeS3 | None = None) -> _FakeS3:
    """Wire the fakes over the network seams and neutralise the poll sleep."""
    s3 = s3 or _FakeS3()
    monkeypatch.setattr(ion, "urlopen", fake.urlopen)
    # ion.py does `import boto3` and calls boto3.client(...), so patch the module attribute itself.
    monkeypatch.setattr(boto3, "client", s3.client)
    monkeypatch.setattr(ion, "sleep", lambda _seconds: None)
    return s3


# --- the happy path: create, upload, complete, poll, return ------------------------------


def test_upload_creates_uploads_completes_and_returns_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeIon()
    s3 = _install(monkeypatch, fake)
    czml = '[{"id":"document"}]'

    asset = ion.upload(czml, "tok-123", name="orbit", description="a pass")

    assert isinstance(asset, ion.IonAsset)
    assert asset.id == 42
    assert asset.status == "COMPLETE"
    assert asset.type == "CZML"
    assert asset.dashboard_url == "https://ion.cesium.com/assets/42"

    # The create POST carries the CZML asset shape.
    create = next(r for r in fake.requests if r["url"].endswith("/v1/assets"))
    assert create["method"] == "POST"
    assert create["payload"] == {
        "name": "orbit",
        "description": "a pass",
        "type": "CZML",
        "options": {"sourceType": "CZML"},
    }

    # The bytes went to S3 under the returned prefix, as a fixed source file, with the ion creds.
    assert len(s3.puts) == 1
    put = s3.puts[0]
    assert put["Bucket"] == "assets.cesium.com"
    assert put["Key"] == "sources/42/document.czml"
    assert put["Body"] == czml.encode("utf-8")
    assert s3.client_kwargs["aws_access_key_id"] == "AK"
    assert s3.client_kwargs["aws_secret_access_key"] == "SK"
    assert s3.client_kwargs["aws_session_token"] == "ST"
    assert s3.client_kwargs["endpoint_url"] == "https://s3.amazonaws.com"

    # onComplete was POSTed.
    assert any(r["url"].endswith("/uploadComplete") for r in fake.requests)


def test_upload_forwards_bearer_token_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeIon()
    _install(monkeypatch, fake)
    ion.upload("[]", "secret-token", name="x")
    assert fake.requests  # create + complete + at least one status poll
    for request in fake.requests:
        assert request["auth"] == "Bearer secret-token"


def test_upload_polls_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeIon(statuses=("IN_PROGRESS", "IN_PROGRESS", "COMPLETE"))
    _install(monkeypatch, fake)
    asset = ion.upload("[]", "tok", name="x")
    assert asset.status == "COMPLETE"
    polls = [r for r in fake.requests if r["method"] == "GET"]
    assert len(polls) == 3


def test_upload_no_wait_skips_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeIon(create_status="AWAITING_FILES")
    _install(monkeypatch, fake)
    asset = ion.upload("[]", "tok", name="x", wait=False)
    # No status poll happened; the reported status is whatever the create response carried.
    assert asset.status == "AWAITING_FILES"
    assert not any(r["method"] == "GET" for r in fake.requests)


# --- the failure contract -----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["ERROR", "DATA_ERROR"])
def test_upload_raises_when_asset_finishes_in_error(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    fake = _FakeIon(statuses=(bad,))
    _install(monkeypatch, fake)
    with pytest.raises(IonUploadError, match=bad):
        ion.upload("[]", "tok", name="x")


def test_upload_times_out_when_never_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeIon(statuses=("IN_PROGRESS",))  # never completes
    _install(monkeypatch, fake)
    # First monotonic() sets the deadline at t=0; every later reading is past it, so the first
    # poll's check trips the timeout — no real waiting.
    clock = iter([0.0] + [1e9] * 8)
    monkeypatch.setattr(ion, "monotonic", lambda: next(clock))
    with pytest.raises(IonUploadError, match="did not reach COMPLETE"):
        ion.upload("[]", "tok", name="x", timeout=5.0)


def test_upload_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: Any) -> _FakeResponse:
        raise HTTPError(request.full_url, 401, "Unauthorized", Message(), None)

    monkeypatch.setattr(ion, "urlopen", boom)
    with pytest.raises(IonUploadError, match="401"):
        ion.upload("[]", "bad-token", name="x")


def test_upload_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: Any) -> _FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr(ion, "urlopen", boom)
    with pytest.raises(IonUploadError, match="connection refused"):
        ion.upload("[]", "tok", name="x")


def test_upload_rejects_an_empty_token() -> None:
    # The guard fires before any network call, so no fakes are needed.
    with pytest.raises(ValueError, match="access token"):
        ion.upload("[]", "", name="x")


# --- the CzmlDocument method --------------------------------------------------------------


def test_document_upload_to_ion_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_upload(
        czml: str, token: str, *, name: str, description: str = "", wait: bool = True
    ) -> ion.IonAsset:
        captured.update(czml=czml, token=token, name=name, description=description, wait=wait)
        return ion.IonAsset(id=7, name=name, type="CZML", status="COMPLETE")

    monkeypatch.setattr(ion, "upload", _fake_upload)
    document = _document()
    asset = document.upload_to_ion("tok", name="n", description="d", wait=False)

    assert asset.id == 7
    assert captured == {
        "czml": document.to_json(),
        "token": "tok",
        "name": "n",
        "description": "d",
        "wait": False,
    }


def test_upload_to_ion_without_the_extra_raises_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the [ion] extra being absent: map "boto3" to None so its import fails, and clear the
    # cached gmat_czml.ion module and its package attribute so the lazy import in
    # CzmlDocument.upload_to_ion re-executes (and fails on `import boto3`). It must surface as an
    # ImportError naming the install.
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.delitem(sys.modules, "gmat_czml.ion", raising=False)
    monkeypatch.delattr(gmat_czml, "ion", raising=False)
    with pytest.raises(ImportError, match=r"gmat-czml\[ion\]"):
        _document().upload_to_ion("tok", name="x")
