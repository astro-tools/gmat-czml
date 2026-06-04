"""Headless CesiumJS-parse + orbit-path check on the real producer fixtures.

Loads each emitted document in a real headless browser through ``Cesium.CzmlDataSource.load`` —
catching valid-but-unrenderable output a JSON-schema check alone would miss — then samples the
satellite's position across the document's clock span to assert the scene actually *animates* and
traces a *correct orbit path*: the radius stays in the expected LEO band and is near-constant, and
the position varies over time.

Positions are read in the inertial frame the document declares, so no ICRF→fixed Earth-orientation
data is needed and the check stays hermetic (CzmlDataSource parsing needs no WebGL context or ion
token, so no ``Viewer`` is created). This replaces the scaffold's trivial-fixture placeholder; it
is the ``cesium-parse`` CI job and needs ``playwright install chromium``.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

from _harness import DOCUMENTS

pytestmark = pytest.mark.browser

_CESIUM_BASE = "https://cdn.jsdelivr.net/npm/cesium@1/Build/Cesium/"

# Each producer's orbit-path document, the entity to sample, and the expected geometry: a LEO
# radius band (metres) and the near-circular spread bound. The GMAT LEO and the ISS TLE are both
# low, near-circular orbits, so the sampled radius must sit in band and vary little.
_CASES = [
    pytest.param("gmat-leo.czml", "GmatLeo", id="gmat-leo"),
    pytest.param("skyfield-iss.czml", "ISS (ZARYA)", id="skyfield-iss"),
]

_LEO_RADIUS_MIN_M = 6.6e6
_LEO_RADIUS_MAX_M = 7.0e6
_NEAR_CIRCULAR_SPREAD_M = 1.0e5  # < 100 km variation over the orbit
_PATH_MOTION_M = 1.0e5  # the satellite must move at least this far across the span

_SAMPLE_POSITIONS = """
async ({ czml, entityId, samples }) => {
    const dataSource = await Cesium.CzmlDataSource.load(czml);
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


@pytest.mark.parametrize(("document_name", "entity_id"), _CASES)
def test_cesium_renders_a_correct_orbit_path(
    page: Page, document_name: str, entity_id: str
) -> None:
    czml = DOCUMENTS[document_name]().to_dict()
    page.set_content(
        "<!doctype html><html><head>"
        f"<script>window.CESIUM_BASE_URL = '{_CESIUM_BASE}';</script>"
        "</head><body></body></html>"
    )
    page.add_script_tag(url=f"{_CESIUM_BASE}Cesium.js")

    result: dict[str, Any] = page.evaluate(
        _SAMPLE_POSITIONS, {"czml": czml, "entityId": entity_id, "samples": 12}
    )

    assert result["count"] >= 1  # entities materialised
    radii = result["radii"]
    assert len(radii) >= 10  # the sampled position resolves across the span
    assert all(_LEO_RADIUS_MIN_M <= r <= _LEO_RADIUS_MAX_M for r in radii)  # correct LEO band
    assert max(radii) - min(radii) < _NEAR_CIRCULAR_SPREAD_M  # near-circular, ~constant radius
    assert result["maxMotion"] > _PATH_MOTION_M  # the path animates (position varies over time)


# The contacts scene: the observer's expected geodetic placement (matching the _harness fixture)
# and the entity ids Cesium must materialise.
_CONTACTS_OBSERVER_ID = "Canberra"
_CONTACTS_LINK_ID = "Canberra-to-GmatLeo"
_CONTACTS_OBSERVER_LON = 148.9819
_CONTACTS_OBSERVER_LAT = -35.4014
_GEODETIC_TOL_DEG = 1.0e-4  # ~10 m on the ground — well inside visualization tolerance

_READ_CONTACTS = """
async ({ czml, observerId, linkId }) => {
    const dataSource = await Cesium.CzmlDataSource.load(czml);
    const observer = dataSource.entities.getById(observerId);
    const link = dataSource.entities.getById(linkId);
    const out = { count: dataSource.entities.values.length, hasLink: false, lon: null, lat: null };
    out.hasLink = Cesium.defined(link) && Cesium.defined(link.polyline);
    if (Cesium.defined(observer) && Cesium.defined(observer.position)) {
        const p = observer.position.getValue(dataSource.clock.startTime, new Cesium.Cartesian3());
        if (Cesium.defined(p)) {
            const carto = Cesium.Cartographic.fromCartesian(p);
            out.lon = Cesium.Math.toDegrees(carto.longitude);
            out.lat = Cesium.Math.toDegrees(carto.latitude);
        }
    }
    return out;
}
"""


def test_cesium_parses_a_contacts_scene(page: Page) -> None:
    # The contacts document loads and its observer + link entities materialise: the observer
    # resolves to its declared geodetic position and the link carries a polyline (the referenced
    # line of sight Cesium draws between the observer and the satellite during each window).
    czml = DOCUMENTS["gmat-leo-contacts.czml"]().to_dict()
    page.set_content(
        "<!doctype html><html><head>"
        f"<script>window.CESIUM_BASE_URL = '{_CESIUM_BASE}';</script>"
        "</head><body></body></html>"
    )
    page.add_script_tag(url=f"{_CESIUM_BASE}Cesium.js")

    result: dict[str, Any] = page.evaluate(
        _READ_CONTACTS,
        {"czml": czml, "observerId": _CONTACTS_OBSERVER_ID, "linkId": _CONTACTS_LINK_ID},
    )

    assert result["count"] >= 3  # satellite + observer + link entities materialised
    assert result["hasLink"]  # the observer -> satellite link is a renderable polyline
    assert result["lon"] == pytest.approx(_CONTACTS_OBSERVER_LON, abs=_GEODETIC_TOL_DEG)
    assert result["lat"] == pytest.approx(_CONTACTS_OBSERVER_LAT, abs=_GEODETIC_TOL_DEG)
