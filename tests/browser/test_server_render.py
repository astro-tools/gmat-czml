"""Headless server-render check: the served page parses in a real CesiumJS client over http.

Boots the ``[server]`` app on a real loopback socket (uvicorn in a background thread), points a
headless browser at ``/``, and lets the embedded viewer fetch ``/document.czml`` over http and parse
it through ``Cesium.CzmlDataSource`` — the DoD's "served page exercised headlessly (CesiumJS parse
over http)". It then samples the satellite across the document clock span to assert the served scene
animates a correct LEO orbit path, the same geometry the schema/golden checks lock.

The check keys on the viewer's parse stage (``window.__czmlParsed`` / ``window.__dataSource``),
which needs no WebGL context, so it does not depend on the runner having a GPU; the Viewer's render
stage is best-effort. Marked ``browser`` (the ``cesium-parse`` CI job): needs
``playwright install chromium`` and the ``[server]`` extra, both present in that job.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Page

from _harness import gmat_leo_dataframe
from gmat_czml import to_czml
from gmat_czml.server import build_app

pytestmark = pytest.mark.browser

# The served document's satellite entity and its expected geometry: a low, near-circular orbit, so
# the sampled radius sits in the LEO band (metres) and varies little, and the path animates.
_SATELLITE_ID = "GmatLeo"
_LEO_RADIUS_MIN_M = 6.6e6
_LEO_RADIUS_MAX_M = 7.0e6
_NEAR_CIRCULAR_SPREAD_M = 1.0e5  # < 100 km variation over the orbit
_PATH_MOTION_M = 1.0e5  # the satellite must move at least this far across the span

_SERVER_START_TIMEOUT_S = 30.0
_PAGE_READY_TIMEOUT_MS = 60_000

# Sample the served satellite from the page's already-loaded data source (parsed over http), in the
# inertial frame the document declares — no WebGL or Earth-orientation data needed.
_SAMPLE_POSITIONS = """
({ entityId, samples }) => {
    const dataSource = window.__dataSource;
    const entity = dataSource.entities.getById(entityId);
    if (!entity || !entity.position) {
        return { count: dataSource.entities.values.length, radii: [], maxMotion: 0 };
    }
    const inertial = Cesium.ReferenceFrame.INERTIAL;
    const start = dataSource.clock.startTime;
    const span = Cesium.JulianDate.secondsDifference(dataSource.clock.stopTime, start);
    const radii = [];
    const points = [];
    for (let i = 0; i < samples; i++) {
        const offset = (span * i) / (samples - 1);
        const t = Cesium.JulianDate.addSeconds(start, offset, new Cesium.JulianDate());
        const p = entity.position.getValueInReferenceFrame(t, inertial, new Cesium.Cartesian3());
        if (!Cesium.defined(p)) { continue; }
        radii.push(Cesium.Cartesian3.magnitude(p));
        points.push(p);
    }
    let maxMotion = 0;
    for (let i = 1; i < points.length; i++) {
        maxMotion = Math.max(maxMotion, Cesium.Cartesian3.distance(points[0], points[i]));
    }
    return { count: dataSource.entities.values.length, radii, maxMotion };
}
"""


def _free_port() -> int:
    """An OS-assigned free loopback port (closed before uvicorn rebinds it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def served_url() -> Iterator[str]:
    """Serve the GMAT LEO document on a uvicorn server in a background thread; yield its URL."""
    document = to_czml(gmat_leo_dataframe())
    port = _free_port()
    config = uvicorn.Config(
        build_app(document), host="127.0.0.1", port=port, log_level="error", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _SERVER_START_TIMEOUT_S
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail(f"uvicorn did not start within {_SERVER_START_TIMEOUT_S:.0f}s")
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_served_page_parses_and_animates_over_http(page: Page, served_url: str) -> None:
    page.goto(served_url)
    # The embedded viewer fetches /document.czml over http and parses it; wait for that stage to
    # finish (or fail). __czmlParsed needs no WebGL, so the assertion is GPU-independent.
    page.wait_for_function(
        "window.__czmlParsed === true || typeof window.__czmlError === 'string'",
        timeout=_PAGE_READY_TIMEOUT_MS,
    )
    assert page.evaluate("window.__czmlError") is None  # the served document parsed cleanly
    assert page.evaluate("window.__entityCount") >= 1  # entities materialised from the served doc

    result: dict[str, Any] = page.evaluate(
        _SAMPLE_POSITIONS, {"entityId": _SATELLITE_ID, "samples": 12}
    )
    radii = result["radii"]
    assert len(radii) >= 10  # the sampled position resolves across the span
    assert all(_LEO_RADIUS_MIN_M <= r <= _LEO_RADIUS_MAX_M for r in radii)  # correct LEO band
    assert max(radii) - min(radii) < _NEAR_CIRCULAR_SPREAD_M  # near-circular, ~constant radius
    assert result["maxMotion"] > _PATH_MOTION_M  # the served scene animates (position varies)
