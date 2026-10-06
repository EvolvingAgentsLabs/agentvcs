from __future__ import annotations

import dataclasses
from typing import Any, Callable, Mapping, Optional

from .._core import Manifest, current_run_or_none, current_step


@dataclasses.dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    model: str
    manifest_id: str
    stop_reason: Optional[str]
    raw: Any


def render_prompt(manifest: Manifest, agent: str, variables: Optional[Mapping] = None):
    """``(system, user_text)`` from the ``{agent}.prompt`` dimension. Every declared
    variable must be supplied (a missing one is a harness bug, not an empty string)."""
    p = manifest[f"{agent}.prompt"]
    variables = dict(variables or {})
    missing = [v for v in p.get("variables", []) if v not in variables]
    if missing:
        raise KeyError(f"{agent}.prompt needs variables {missing}")
    return p.get("system"), p["template"].format_map(variables)


def config(manifest: Manifest, agent: str):
    model = manifest[f"{agent}.model"]
    sampling = dict(manifest.get(f"{agent}.sampling", {}) or {})
    return model, sampling


def resolve_manifest_for_call(manifest: Optional[Manifest]) -> Manifest:
    if manifest is not None:
        return manifest
    r = current_run_or_none()
    if r is None:
        raise RuntimeError(
            "no active run and no manifest= given: the wrapper reads model, sampling "
            "and prompt from a manifest"
        )
    return r.manifest


def recorded(agent_id: str, call: Callable[[Manifest], Completion], manifest: Optional[Manifest]) -> Completion:
    """Run ``call`` so that its tokens/latency land in a step:
    - inside a ``@step``: added to that step;
    - inside a run but outside a step: recorded as a step of its own (``agent_id``),
      re-executed if a patch lands mid-call;
    - outside a run (e.g. a gate suite): not recorded; ``manifest=`` is required."""
    if current_step() is not None or manifest is not None:
        return call(resolve_manifest_for_call(manifest))
    r = current_run_or_none()
    if r is None:
        return call(resolve_manifest_for_call(None))
    return r.call_step(agent_id, lambda: call(r.manifest), outputs=lambda c: [c.text])


def note(request: Any, response: Any, c: Completion) -> None:
    st = current_step()
    if st is None:
        return
    st.add_tokens(c.tokens_in, c.tokens_out)
    st.add_input(request)
    st.add_output(response)
