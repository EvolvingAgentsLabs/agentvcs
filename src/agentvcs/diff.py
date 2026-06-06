"""Dimensional diff — the core value proposition made visible.

Comparing two agentvcs commits doesn't just diff code; it reports what changed in
*each* dimension independently: which files moved, whether the goal was redirected,
whether a model was swapped or re-tuned, and how the message trace grew. This is
what lets a human (or a merge agent) reason about an evolving fleet.
"""
from __future__ import annotations

from .repository import Repository


def _tree_entries(repo: Repository, commit: dict) -> dict[str, str]:
    return repo.objects.read_obj(commit["tree"])["entries"]


def _diff_code(repo, a, b) -> dict:
    old = _tree_entries(repo, a) if a else {}
    new = _tree_entries(repo, b)
    added = sorted(p for p in new if p not in old)
    removed = sorted(p for p in old if p not in new)
    modified = sorted(p for p in new if p in old and old[p] != new[p])
    return {"added": added, "removed": removed, "modified": modified}


def _diff_goal(repo, a, b) -> dict | None:
    new = repo.objects.read_obj(b["goal"])["text"]
    old = repo.objects.read_obj(a["goal"])["text"] if a else None
    if old == new:
        return None
    return {"from": old, "to": new}


def _model_label(m: dict) -> str:
    base = f"{m.get('provider', '')}/{m.get('model', '')}"
    if m.get("version"):
        base += f"@{m['version']}"
    params = m.get("params") or {}
    if params:
        kv = ",".join(f"{k}={params[k]}" for k in sorted(params))
        base += f" [{kv}]"
    return base


def _diff_models(repo, a, b) -> dict | None:
    new = [_model_label(repo.objects.read_obj(o)) for o in b["models"]]
    old = [_model_label(repo.objects.read_obj(o)) for o in a["models"]] if a else []
    if old == new:
        return None
    return {"from": old, "to": new}


def _diff_trace(repo, a, b) -> dict | None:
    new_n = len(repo.objects.read_obj(b["trace"])["messages"]) if b.get("trace") else 0
    old_n = 0
    if a and a.get("trace"):
        old_n = len(repo.objects.read_obj(a["trace"])["messages"])
    if old_n == new_n:
        return None
    return {"from": old_n, "to": new_n, "delta": new_n - old_n}


def diff_commits(repo: Repository, oid_a: str | None, oid_b: str) -> dict:
    """Diff dimensions of commit b against commit a (a may be None for root)."""
    b = repo.objects.read_obj(oid_b)
    a = repo.objects.read_obj(oid_a) if oid_a else None
    return {
        "code": _diff_code(repo, a, b),
        "goal": _diff_goal(repo, a, b),
        "models": _diff_models(repo, a, b),
        "trace": _diff_trace(repo, a, b),
        "state": None if (a and a["state"] == b["state"])
        else {"from": a["state"] if a else None, "to": b["state"]},
    }
