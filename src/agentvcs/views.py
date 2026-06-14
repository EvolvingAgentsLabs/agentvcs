"""Pure JSON projections of repository state.

These functions turn repository objects into the plain dicts that the CLI prints
under ``--json``, that the MCP server returns, and that the local UI serves over
HTTP. Keeping them here (instead of inline in ``cli.py``) means all three speak
exactly one contract — the shapes documented in ``docs/AGENT_MODE.md`` — and the
terminal and the dashboard can never drift apart.

Nothing here does I/O beyond reading the object store; there are no sockets, no
colors, no ``print``. That is what makes the whole surface unit-testable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .diff import diff_commits
from .repository import Repository


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def commit_summary(repo: Repository, oid: str, commit: dict | None = None) -> dict:
    """The lightweight per-commit row used by ``log`` (and as the base of ``show``)."""
    commit = commit or repo.objects.read_obj(oid)
    return {
        "commit": oid,
        "state": commit["state"],
        "timestamp": iso(commit["timestamp"]),
        "message": commit["message"],
        "goal": repo.objects.read_obj(commit["goal"])["text"],
        "parents": commit.get("parents", []),
    }


def log_view(repo: Repository) -> dict:
    return {"commits": [commit_summary(repo, oid, c) for oid, c in repo.log()]}


def commit_view(repo: Repository, oid: str, include_trace: bool = False) -> dict:
    """The full ``show`` projection across every dimension. With ``include_trace``
    the raw trace message blocks are attached (the chat the UI renders)."""
    commit = repo.objects.read_obj(oid)
    models = [repo.objects.read_obj(m) for m in commit["models"]]
    messages = (repo.objects.read_obj(commit["trace"])["messages"]
                if commit.get("trace") else [])
    data = {
        **commit_summary(repo, oid, commit),
        "author": commit["author"],
        "models": [{"provider": m["provider"], "model": m["model"],
                    "version": m["version"], "params": m["params"]} for m in models],
        "trace_messages": len(messages),
        "metrics": commit.get("metrics", {}),
        "crystal": commit.get("crystal"),
        "runtime": _runtime_obj(repo, commit),
        "eval": _eval_summary(repo.read_eval(oid)),
    }
    if include_trace:
        data["trace"] = messages
    return data


def _eval_summary(result: dict | None) -> dict | None:
    """The compact eval verdict for a commit (the side-table entry, minus the
    verbose per-run stdout)."""
    if not result:
        return None
    return {"ok": result.get("ok"), "passed": result.get("passed"),
            "total": result.get("total"), "score": result.get("score"),
            "command": result.get("command")}


def _runtime_obj(repo: Repository, commit: dict) -> dict | None:
    """The operational frame attached to a commit (runtime mode), or None."""
    oid = commit.get("runtime")
    if not oid:
        return None
    obj = repo.objects.read_obj(oid)
    return {k: v for k, v in obj.items() if k != "type"}


def runtime_view(repo: Repository, frame: dict) -> dict:
    """Pass-through projection for a freshly computed live frame (budget/context/
    routing/tools/subagents). Kept here so CLI, MCP and UI share one shape."""
    return frame


def diff_view(repo: Repository, a: str | None, b: str) -> dict:
    return {"a": a, "b": b, "diff": diff_commits(repo, a, b)}


def repo_view(repo: Repository) -> dict:
    """Top-level orientation for the dashboard header and branch list."""
    branches = repo.branches()
    head = repo.head_commit()
    return {
        "current": repo.current_branch(),
        "head": head,
        "branches": [{"name": n, "commit": o} for n, o in sorted(branches.items())],
        "goal": repo.read_manifest().get("goal", ""),
    }
