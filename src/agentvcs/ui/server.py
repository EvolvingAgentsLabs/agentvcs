"""The thin HTTP transport for the dashboard — standard library only.

Routes ``GET /api/*`` to the pure :func:`agentvcs.ui.api.handle` and serves the
single-page ``index.html`` for everything else. Binds loopback by default; the
dashboard is a local window onto the repo, not a network service.
"""
from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import api
from ..repository import RepoError, Repository

_MAX_PORT_PROBES = 20  # how many consecutive ports to try before giving up


def _load_index() -> bytes:
    """Read the bundled single-page app. Uses importlib.resources so it works the
    same installed from a wheel or run straight from the source tree."""
    return (files("agentvcs.ui") / "index.html").read_bytes()


def _make_handler(repo: Repository, index_html: bytes):
    class Handler(BaseHTTPRequestHandler):
        # quiet by default — the dashboard shouldn't spam the terminal it serves from
        def log_message(self, *args):  # noqa: D401
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, obj: dict):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path.startswith("/api/") or parts.path == "/api":
                route = [seg for seg in parts.path.split("/")[2:] if seg != ""]
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                try:
                    status, body = api.handle(repo, route, query)
                except Exception as e:  # never leak a stack trace to the browser
                    status, body = 500, {"ok": False,
                                         "error": {"code": "INTERNAL", "message": str(e)}}
                self._send_json(status, body)
                return
            # everything else is the single-page app
            self._send(200, index_html, "text/html; charset=utf-8")

    return Handler


def build_server(repo: Repository, host: str, port: int) -> ThreadingHTTPServer:
    """Bind a server for ``repo``. If ``port`` is busy, probe the next few ports
    and use the first free one (friendlier than failing). ``port=0`` lets the OS
    pick (used by tests). Raises ``PORT_IN_USE`` if nothing in range is free."""
    index_html = _load_index()
    handler = _make_handler(repo, index_html)
    last_err: OSError | None = None
    probes = 1 if port == 0 else _MAX_PORT_PROBES
    for candidate in range(port, port + probes):
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as e:
            last_err = e
            continue
    raise RepoError(
        f"no free port in {port}..{port + _MAX_PORT_PROBES - 1} on {host}"
        + (f" ({last_err})" if last_err else ""),
        code="PORT_IN_USE")


def serve(repo: Repository, host: str = "127.0.0.1", port: int = 8080,
          open_browser: bool = True, on_ready=None) -> None:
    """Build, announce, and serve until interrupted. ``on_ready(url)`` is called
    with the bound URL once (for the CLI to print it / agents to capture it)."""
    httpd = build_server(repo, host, port)
    bound_host, bound_port = httpd.server_address[0], httpd.server_address[1]
    url = f"http://{bound_host}:{bound_port}"
    if on_ready:
        on_ready(url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # headless box, no browser — the URL was already reported
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
