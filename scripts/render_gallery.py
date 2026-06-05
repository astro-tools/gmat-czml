"""Headless render harness for the documentation gallery.

Runs the example scripts, loads each ``.czml`` in ``examples/viewer.html`` through a real headless
browser, and captures the images committed under ``docs/assets/gallery/`` — a still PNG per
example plus one animated GIF for the flagship LEO + ground-track scene. The committed images are
what the docs build embeds, so ``mkdocs build`` never needs a browser; this script is how they are
regenerated, deliberately, the same way the golden corpus is.

Requirements (this is a dev-only maintenance script — its dependencies are deliberately kept out of
the project lockfile so the gallery never affects the published package or its install):

- Playwright (in the dev group) and its browser: ``uv run playwright install chromium``.
- On Linux, the chromium system libraries: ``sudo uv run playwright install-deps chromium``
  (a headless GPU is not needed — rendering uses software WebGL via SwiftShader).
- Pillow assembles the GIF (no external ffmpeg needed): ``pip install pillow``.

Imagery: with a Cesium ion access token in the ``CESIUM_ION_TOKEN`` environment variable the globe
uses ion world imagery; without one it falls back to the offline Natural Earth II imagery bundled
with CesiumJS. The token is read from the environment only and is never written anywhere.

Run from the repository root::

    CESIUM_ION_TOKEN=... python scripts/render_gallery.py
"""

from __future__ import annotations

import functools
import http.server
import io
import os
import socketserver
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"
GALLERY_DIR = REPO_ROOT / "docs" / "assets" / "gallery"

VIEWPORT = {"width": 1280, "height": 720}
GIF_FRAMES = 36
GIF_FPS = 12
GIF_WIDTH = 540
GIF_COLORS = 96

# The full chromium binary in new-headless mode renders WebGL in software (SwiftShader) without a
# display or GPU — the path that works in CI and on a headless WSL box alike.
LAUNCH_ARGS = [
    "--headless=new",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--enable-unsafe-swiftshader",
    "--use-gl=angle",
    "--use-angle=swiftshader",
]


@dataclass(frozen=True)
class Scene:
    """One gallery entry: the example to run, its output document, and the image to write."""

    script: str  # example script filename, relative to examples/
    czml: str  # produced document filename, relative to examples/output/
    image: str  # still image filename, written under docs/assets/gallery/
    animate: bool = False  # also capture an animated GIF (image stem + .gif)
    freeze: float = 1.0  # fraction of the span to freeze the still at (1.0 = end)
    track: bool = False  # follow the body-box entity up close (for the attitude orientation)


SCENES = [
    Scene("leo_ground_track.py", "leo-ground-track.czml", "leo-ground-track.png", animate=True),
    Scene("geo.py", "geo.czml", "geo.png"),
    Scene("skyfield_tle.py", "skyfield-iss.czml", "skyfield-iss.png"),
    # The annotation scenes freeze mid-span where their windowed entity is live: a contact link
    # shown only during the pass (~0.31), and the finite-burn arc shown only while it fires (~0.53).
    Scene("contacts_mission.py", "contacts.czml", "contacts.png", freeze=0.31),
    Scene("maneuver_mission.py", "maneuvers.czml", "maneuvers.png", freeze=0.53),
    # The body box is small against the whole-orbit framing, so track it up close — the GIF is
    # then the axes turning, which is the point of the attitude entity.
    Scene("attitude_mission.py", "attitude.czml", "attitude.png", animate=True, track=True),
]


def run_examples() -> None:
    """Run each example script so its document exists under examples/output/."""
    for scene in SCENES:
        print(f"running examples/{scene.script}")
        subprocess.run([sys.executable, str(EXAMPLES / scene.script)], check=True, cwd=REPO_ROOT)


def serve(directory: Path) -> tuple[socketserver.TCPServer, int]:
    """A background HTTP server rooted at ``directory``; returns the server and its port."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _load_scene(
    page: Page, base_url: str, czml: str, token: str, freeze: float, track: bool
) -> None:
    """Boot the viewer for one document, then wait for the scene and its imagery to settle."""
    page.goto(f"{base_url}/viewer.html", wait_until="load")
    page.evaluate("opts => window.boot(opts)", {"token": token, "czml": f"output/{czml}"})
    page.wait_for_function("() => window.__czmlReady === true", timeout=60_000)
    # Let the globe imagery tiles finish loading before the capture.
    page.wait_for_function(
        "() => window.__viewer && window.__viewer.scene.globe.tilesLoaded", timeout=60_000
    )
    page.wait_for_timeout(1500)
    page.evaluate(
        "() => { const p = document.getElementById('panel'); if (p) p.style.display = 'none'; }"
    )
    if track:
        # Install a per-frame camera aim that points at the body-box entity from a fixed offset and
        # a close range, so the orientation fills the frame instead of being a speck against the
        # whole-orbit framing. Both the still and the GIF call it after setting the clock time.
        page.evaluate(
            """() => {
                const ds = window.__dataSource;
                let target = null;
                for (const e of ds.entities.values) { if (e.box) { target = e; break; } }
                window.__aimBox = (time) => {
                    const v = window.__viewer;
                    if (!target || !target.position) return;
                    const pos = target.position.getValue(time);
                    if (!pos) return;
                    v.camera.lookAt(pos, new Cesium.HeadingPitchRange(
                        Cesium.Math.toRadians(35), Cesium.Math.toRadians(-12), 3.2e6));
                };
            }"""
        )
    # Freeze the still at a scene-chosen fraction of the span. The default (1.0) sits at the end so
    # the orbit path — which trails behind the current time — is drawn in full; an annotation scene
    # whose entity is shown only over a window (a contact link, a finite-burn arc) overrides this to
    # a fraction where that entity is live. A tracked scene re-aims the camera at the body box.
    page.evaluate(
        """({ fraction, track }) => {
            const v = window.__viewer;
            const start = v.clock.startTime, stop = v.clock.stopTime;
            const span = Cesium.JulianDate.secondsDifference(stop, start);
            v.clock.shouldAnimate = false;
            v.clock.currentTime = Cesium.JulianDate.addSeconds(
                start, span * fraction, new Cesium.JulianDate());
            if (track) window.__aimBox(v.clock.currentTime);
            v.scene.render();
        }""",
        {"fraction": freeze, "track": track},
    )


def _capture_gif(page: Page, stem: Path, track: bool) -> None:
    """Step the clock across the span and assemble the screenshot frames into a GIF."""
    frames: list[Image.Image] = []
    for i in range(GIF_FRAMES):
        page.evaluate(
            """({ i, n, track }) => {
                const v = window.__viewer;
                const start = v.clock.startTime, stop = v.clock.stopTime;
                const span = Cesium.JulianDate.secondsDifference(stop, start);
                const t = Cesium.JulianDate.addSeconds(
                    start, (span * i) / n, new Cesium.JulianDate());
                v.clock.currentTime = t;
                if (track) window.__aimBox(t);
                v.scene.render();
            }""",
            {"i": i, "n": GIF_FRAMES, "track": track},
        )
        png = page.screenshot()
        frame = Image.open(io.BytesIO(png)).convert("RGB")
        height = round(frame.height * GIF_WIDTH / frame.width)
        frames.append(frame.resize((GIF_WIDTH, height), Image.LANCZOS).quantize(colors=GIF_COLORS))
    gif = stem.with_suffix(".gif")
    frames[0].save(
        gif,
        save_all=True,
        append_images=frames[1:],
        duration=round(1000 / GIF_FPS),
        loop=0,
        optimize=True,
    )
    print(f"  wrote {gif.relative_to(REPO_ROOT)} ({round(gif.stat().st_size / 1024)} KB)")


def main() -> int:
    token = os.environ.get("CESIUM_ION_TOKEN", "")
    print("ion token: " + ("present" if token else "absent — using offline imagery"))
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)

    run_examples()
    httpd, port = serve(EXAMPLES)
    base_url = f"http://127.0.0.1:{port}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False, args=LAUNCH_ARGS)
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
            for scene in SCENES:
                print(f"rendering {scene.image}")
                _load_scene(page, base_url, scene.czml, token, scene.freeze, scene.track)
                still = GALLERY_DIR / scene.image
                page.screenshot(path=str(still))
                kb = round(still.stat().st_size / 1024)
                print(f"  wrote {still.relative_to(REPO_ROOT)} ({kb} KB)")
                if scene.animate:
                    _capture_gif(page, still, scene.track)
            browser.close()
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
