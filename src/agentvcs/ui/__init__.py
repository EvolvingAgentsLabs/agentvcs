"""The local dashboard — a read-only visual window onto an agentvcs repository.

``agentvcs ui`` serves a single-page app (``index.html``) backed by a tiny
read-only JSON API (``api.handle``). Both run on the Python standard library
alone — ``http.server`` for transport, vanilla JS/CSS for the frontend — so the
dashboard adds **zero** runtime dependencies, exactly like the rest of the core.

The split that keeps it testable: ``api.py`` is pure (repository in, dict out, no
sockets) and ``server.py`` is the thin HTTP shell that routes to it and serves the
static page.
"""
from .server import serve

__all__ = ["serve"]
