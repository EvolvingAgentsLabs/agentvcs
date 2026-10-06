"""Claude via the official ``anthropic`` Python SDK (optional dependency:
``pip install anthropic``).

    client = AnthropicClient()              # credentials resolved by the SDK
    with avcs.run(manifest) as run:
        c = client.complete("summarize", {"extraction": ex})

The call is built from the active manifest on every call: ``{agent}.model.id`` is
the model (e.g. ``claude-opus-5-5``); ``{agent}.prompt`` gives ``system`` and the
user message; from ``{agent}.sampling`` only fields the Messages API accepts are
forwarded — ``max_tokens`` (default 16000), ``stop`` / ``stop_sequences``,
``output_config`` (e.g. ``{"effort": "low"}``), ``thinking``, and ``temperature``
/ ``top_p`` / ``top_k``. Current Claude models reject the last three (HTTP 400):
leave them out of manifests for those models; agentvcs does not second-guess the
manifest. Fields meant for local servers (``seed``, ``grammar``, ``min_p``) are
dropped. Tokens come from ``usage.input_tokens`` / ``usage.output_tokens``.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from .._core import Manifest
from ._common import Completion, config, note, recorded, render_prompt

_FORWARD = ("temperature", "top_p", "top_k", "output_config", "thinking", "metadata")


class AnthropicClient:
    def __init__(self, client: Any = None, **client_kwargs: Any):
        """``client``: an ``anthropic.Anthropic`` (or anything with
        ``.messages.create``). Otherwise one is built with ``client_kwargs``
        (e.g. ``base_url=``, ``api_key=``, ``max_retries=``)."""
        if client is None:
            import anthropic  # optional dependency

            client = anthropic.Anthropic(**client_kwargs)
        self.client = client

    def request_params(self, manifest: Manifest, agent: str, variables: Optional[Mapping] = None) -> dict:
        model, sampling = config(manifest, agent)
        system, user = render_prompt(manifest, agent, variables)
        params: dict = {
            "model": model["id"],
            "max_tokens": int(sampling.get("max_tokens") or 16000),
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            params["system"] = system
        stop = sampling.get("stop_sequences", sampling.get("stop"))
        if stop:
            params["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
        for k in _FORWARD:
            if sampling.get(k) is not None:
                params[k] = sampling[k]
        return params

    def complete(
        self,
        agent: str,
        variables: Optional[Mapping] = None,
        *,
        agent_id: Optional[str] = None,
        manifest: Optional[Manifest] = None,
    ) -> Completion:
        def call(m: Manifest) -> Completion:
            params = self.request_params(m, agent, variables)
            t0 = time.perf_counter()
            resp = self.client.messages.create(**params)
            latency = (time.perf_counter() - t0) * 1000.0
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            if hasattr(resp, "to_dict"):
                raw = resp.to_dict()
            else:  # a duck-typed client: keep what the wrapper read
                raw = {"text": text, "stop_reason": getattr(resp, "stop_reason", None),
                       "usage": {"input_tokens": resp.usage.input_tokens,
                                 "output_tokens": resp.usage.output_tokens}}
            c = Completion(
                text=text,
                tokens_in=int(resp.usage.input_tokens or 0),
                tokens_out=int(resp.usage.output_tokens or 0),
                latency_ms=round(latency, 3),
                model=params["model"],
                manifest_id=m.id,
                stop_reason=getattr(resp, "stop_reason", None),
                raw=raw,
            )
            note(params, raw, c)
            return c

        return recorded(agent_id or agent, call, manifest)
