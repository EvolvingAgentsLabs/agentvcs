"""OpenAI-compatible chat completions (llama.cpp ``llama-server``, vLLM, Ollama's
``/v1``), stdlib HTTP only.

    client = OpenAICompatClient("http://127.0.0.1:8080/v1")
    with avcs.run(manifest) as run:
        c = client.complete("extract", {"document": text})   # one step, or part of
                                                               # the enclosing @step

The request is built from the active manifest on every call: ``{agent}.model.id``
is the ``model`` field, every non-null field of ``{agent}.sampling`` is copied
into the body as is (``temperature``, ``top_p``, ``top_k``, ``min_p``, ``seed``,
``max_tokens``, ``stop``, and llama.cpp's ``grammar``), and ``{agent}.prompt``
gives the system and user messages. A patch to any of those changes the next call.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Mapping, Optional

from .._core import Manifest
from ._common import Completion, config, note, recorded, render_prompt


class OpenAICompatError(RuntimeError):
    pass


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self.timeout = timeout

    def request_body(self, manifest: Manifest, agent: str, variables: Optional[Mapping] = None) -> dict:
        model, sampling = config(manifest, agent)
        system, user = render_prompt(manifest, agent, variables)
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user}
        ]
        body = {"model": model["id"], "messages": messages}
        body.update({k: v for k, v in sampling.items() if v is not None})
        return body

    def post(self, body: Mapping) -> dict:
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise OpenAICompatError(f"HTTP {e.code} from {self.base_url}: {detail}") from None

    def complete(
        self,
        agent: str,
        variables: Optional[Mapping] = None,
        *,
        agent_id: Optional[str] = None,
        manifest: Optional[Manifest] = None,
    ) -> Completion:
        def call(m: Manifest) -> Completion:
            body = self.request_body(m, agent, variables)
            t0 = time.perf_counter()
            resp = self.post(body)
            latency = (time.perf_counter() - t0) * 1000.0
            choice = (resp.get("choices") or [{}])[0]
            usage = resp.get("usage") or {}
            c = Completion(
                text=(choice.get("message") or {}).get("content") or "",
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                latency_ms=round(latency, 3),
                model=body["model"],
                manifest_id=m.id,
                stop_reason=choice.get("finish_reason"),
                raw=resp,
            )
            note(body, resp, c)
            return c

        return recorded(agent_id or agent, call, manifest)
