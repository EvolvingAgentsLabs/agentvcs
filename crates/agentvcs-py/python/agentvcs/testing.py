"""Local HTTP fakes of model servers, for tests and offline examples. They never
reach a network beyond 127.0.0.1.

    with FakeOpenAIServer(lambda req: "hello") as srv:
        client = OpenAICompatClient(srv.base_url)

``respond(request_json) -> str`` produces the reply text; token usage is counted
as whitespace-separated words, so it is deterministic. Every request is kept in
``srv.requests``.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional


def _words(s: str) -> int:
    return len(s.split())


class _FakeServer:
    paths: tuple = ()

    def __init__(self, respond: Callable[[dict], str], status: int = 200):
        self.respond = respond
        self.status = status
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path.split("?")[0] not in outer.paths:
                    return self._send(404, {"error": f"no route {self.path}"})
                outer.requests.append(req)
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                if outer.status != 200:
                    return self._send(outer.status, {"error": {"message": "fake failure"}})
                self._send(200, outer.reply(req, outer.respond(req)))

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    def reply(self, req: dict, text: str) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class FakeOpenAIServer(_FakeServer):
    """``POST /v1/chat/completions`` as llama.cpp / vLLM / Ollama answer it."""

    paths = ("/v1/chat/completions", "/chat/completions")

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def reply(self, req: dict, text: str) -> dict:
        prompt = " ".join(str(m.get("content", "")) for m in req.get("messages", []))
        return {
            "id": f"chatcmpl-fake-{len(self.requests)}",
            "object": "chat.completion",
            "model": req.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": _words(prompt), "completion_tokens": _words(text),
                      "total_tokens": _words(prompt) + _words(text)},
        }


class FakeAnthropicServer(_FakeServer):
    """``POST /v1/messages`` in the Messages API response shape."""

    paths = ("/v1/messages",)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def reply(self, req: dict, text: str) -> dict:
        prompt = " ".join(
            str(m.get("content", "")) for m in req.get("messages", [])
        ) + " " + str(req.get("system") or "")
        return {
            "id": f"msg_fake{len(self.requests)}",
            "type": "message",
            "role": "assistant",
            "model": req.get("model"),
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": _words(prompt), "output_tokens": _words(text)},
        }
