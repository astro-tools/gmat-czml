# Server mode

CZML is rendered by a Cesium client, not by gmat-czml — so to *see* a document you normally drop it
into a viewer (see [viewing the output](getting-started.md#viewing-the-result)). Server mode bundles
that last step: it hosts a document over http behind an embedded CesiumJS viewer and opens it in your
browser, so one call takes a trajectory all the way to a spinning globe.

It is the one-click local-sharing path — a quick look at a result, or a link to hand a colleague on
the same network. It is **not** a hosting service: the server runs on your machine and binds to
loopback by default.

## Install the extra

Server mode is the optional `[server]` extra — [FastAPI](https://fastapi.tiangolo.com/) and
[uvicorn](https://www.uvicorn.org/). A plain install stays light and never pulls them in; add the
extra when you want to serve:

```bash
pip install gmat-czml[server]      # or: uv add 'gmat-czml[server]'
```

Calling `serve` without the extra raises a clear `ImportError` naming this install.

## From Python

[`CzmlDocument.serve`][gmat_czml.CzmlDocument.serve] hosts the document and (by default) opens a
browser tab once the server is up. It blocks until you stop it with `Ctrl-C`:

```python
from orbit_formats import read
from gmat_czml import to_czml

trajectory = read("mission.oem")
to_czml(trajectory, ground_track=True).serve()      # opens http://127.0.0.1:8080/
```

The same document you would `save` is the one that is served — `serve` writes no file. Bind and
browser behaviour are keyword options:

```python
document.serve(port=9000, host="0.0.0.0", open_browser=False)
```

- **`port`** — the port to listen on (default `8080`).
- **`host`** — the interface to bind. The default `127.0.0.1` is loopback-only; set `0.0.0.0` to
  reach it from another machine on your network.
- **`open_browser`** — open a browser tab when the server starts (default `True`); best-effort, and
  a no-op on a headless host.

## From the command line

`gmat-czml serve` reads a trajectory and serves the same document `convert` would write — the
rendering flags (`--style`, `--playback-seconds`, `--ground-track`) match, so the served scene is
byte-for-byte the one you would have saved:

```bash
gmat-czml serve mission.oem --ground-track
gmat-czml serve mission.oem --port 9000 --no-open
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | the trajectory to serve — any file orbit-formats can read |
| `--host HOST` | interface to bind (default `127.0.0.1`, loopback only) |
| `--port PORT` | port to listen on (default `8080`) |
| `--no-open` | do not open a browser tab when the server starts |
| `--style`, `--playback-seconds`, `--ground-track` | the same rendering flags as [`convert`](cli.md) |

It blocks while the server runs and exits cleanly on `Ctrl-C`. Without the `[server]` extra it prints
a one-line `gmat-czml: …` install hint and exits non-zero.

## Why a server and not a file

CesiumJS loads its terrain and imagery through Web Workers, which browsers refuse to create on a
`file://` (null-origin) page — open a viewer straight off disk and the globe never appears. Serving
the page over http is what makes those workers load, so server mode hosts both the viewer and the
document together: the viewer page at `/` and the document JSON at `/document.czml`, which the page
fetches relative to itself. The viewer pulls CesiumJS from a CDN, so a network connection is needed
the first time it loads.
