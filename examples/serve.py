"""Serve the examples over http and open the viewer.

CesiumJS needs Web Workers, and browsers refuse to create workers on a ``file://`` page — its
origin is ``"null"``, so even a same-folder worker is blocked. The viewer therefore has to be
loaded over http, even from localhost. This starts a local server rooted at this folder and opens
the viewer; drag a ``.czml`` from ``output/`` onto the page (or pass ``?czml=output/<name>.czml``).
Stop it with Ctrl-C.

    python examples/serve.py
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8000
HERE = Path(__file__).resolve().parent


class _Server(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    url = f"http://localhost:{PORT}/viewer.html"
    with _Server(("127.0.0.1", PORT), handler) as httpd:
        print(f"serving {HERE}")
        print(f"open {url}  (Ctrl-C to stop)")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
