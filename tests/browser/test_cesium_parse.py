"""Headless CesiumJS-parse smoke test.

Loads CesiumJS in a real headless browser and parses a trivial CZML fixture through
``Cesium.CzmlDataSource.load`` — catching valid-but-unrenderable output a JSON-schema check alone
would miss. CzmlDataSource parsing needs no WebGL context or ion token, so no ``Viewer`` is created.

This is the placeholder the ``cesium-parse`` CI job runs; the full producer fixtures and goldens
land with the validation-harness work. Marked ``browser`` so the default test run skips it; it
needs ``playwright install chromium``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.browser

_CESIUM_BASE = "https://cdn.jsdelivr.net/npm/cesium@1/Build/Cesium/"
_FIXTURE = Path(__file__).resolve().parent.parent / "data" / "trivial.czml"


def test_cesium_parses_trivial_czml(page: Page) -> None:
    czml = json.loads(_FIXTURE.read_text())
    page.set_content(
        "<!doctype html><html><head>"
        f"<script>window.CESIUM_BASE_URL = '{_CESIUM_BASE}';</script>"
        "</head><body></body></html>"
    )
    page.add_script_tag(url=f"{_CESIUM_BASE}Cesium.js")

    entity_count = page.evaluate(
        """async (czml) => {
            const dataSource = await Cesium.CzmlDataSource.load(czml);
            return dataSource.entities.values.length;
        }""",
        czml,
    )

    assert entity_count >= 1
