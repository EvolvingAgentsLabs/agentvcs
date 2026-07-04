"""Trace providers — pluggable sources for the **trace** dimension.

Classic agentvcs reads the trace from a flat file declared in ``agent.json``
(``"trace": "traces/run.jsonl"``). That is *active* logging: the agent must
remember to write the file, which costs tokens and is easy to get wrong.

A provider flips this to *passive* capture: instead of asking the agent to log,
agentvcs vacuums the agent's **native** session log at commit time. The agent
just works; ``agentvcs commit`` reads the high-fidelity trace it already
produced. Declared in the manifest as an object::

    "trace": { "provider": "claude-code", "auto": true }

Each provider is ``pull(decl: dict, workdir: Path) -> list[dict]`` and returns
the ordered message list. Adding a new source (e.g. Fazm's SQLite) is one
module + one registry entry — the on-disk format never changes.
"""
from __future__ import annotations

from pathlib import Path

from . import anthropic_managed
from . import claude_code
from . import odyssey
from . import qwen_code
from . import vercel_eve

# provider name (as written in agent.json) -> provider module
_PROVIDERS = {
    "claude-code": claude_code,
    "qwen-code": qwen_code,
    "vercel-eve": vercel_eve,
    "anthropic-managed": anthropic_managed,
    "odyssey": odyssey,
}


def _provider(decl: dict):
    """Resolve a declaration to its provider module, or raise a stable,
    branchable error code (imported lazily to avoid a module-load cycle with
    repository.py)."""
    name = decl.get("provider")
    mod = _PROVIDERS.get(name)
    if mod is None:
        from ..repository import RepoError
        known = ", ".join(sorted(_PROVIDERS)) or "(none)"
        raise RepoError(f"unknown trace provider {name!r} (known: {known})",
                        code="UNKNOWN_TRACE_PROVIDER")
    return mod


def pull_trace(decl: dict, workdir) -> list:
    """Materialize a provider's trace as an ordered message list."""
    return _provider(decl).pull(decl, Path(workdir))


def describe_trace(decl: dict, workdir) -> dict:
    """Report where a provider's trace comes from, without capturing a commit."""
    mod = _provider(decl)
    if hasattr(mod, "describe"):
        return mod.describe(decl, Path(workdir))
    return {"provider": decl.get("provider")}


def pull_runtime(decl: dict, workdir, budget: dict | None = None) -> dict | None:
    """Reconstruct the operational frame (budget/context/routing/tools/subagents)
    the runtime hides. Returns ``None`` if the provider can't (so the caller can
    fall back to deriving a frame from the normalized messages instead)."""
    mod = _provider(decl)
    if hasattr(mod, "runtime"):
        return mod.runtime(decl, Path(workdir), budget=budget)
    return None
