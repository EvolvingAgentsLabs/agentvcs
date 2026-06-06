"""Replay — deterministically re-execute a crystallized recipe.

Crystallization froze a trusted solution into a recipe: pinned (temperature-0)
models plus the ordered message trace. ``replay`` walks that recipe back out.

The open-source core does not call models itself (zero dependencies, by design),
so replay has two modes:

  * **transcript** (default) — emit the frozen recipe: goal, pinned models, and
    the ordered steps. This is deterministic by construction; it is the canonical
    record a runtime would execute.
  * **executor** (``--exec CMD``) — pipe each step (as JSON) to a command you
    supply (your deterministic model wrapper / runtime) and collect its output.
    Because the models are pinned to temperature 0, a faithful executor yields a
    reproducible run.
"""
from __future__ import annotations

import json
import subprocess

from .repository import Repository, RepoError


def replay(repo: Repository, commit_oid: str | None = None,
           executor: str | None = None) -> dict:
    commit_oid = repo._resolve(commit_oid, expect="commit") if commit_oid else repo.head_commit()
    if not commit_oid:
        raise RepoError("nothing to replay (no commits yet)", code="NO_COMMITS")

    commit = repo.objects.read_obj(commit_oid)
    if commit["state"] != "crystallized" or not commit.get("crystal"):
        raise RepoError(
            f"{commit_oid[:12]} is not crystallized; run `agentvcs freeze` first",
            code="NOT_CRYSTALLIZED")

    recipe = repo.objects.read_obj(commit["crystal"])
    results = []
    for i, step in enumerate(recipe["steps"]):
        entry = {"index": i, "step": step}
        if executor:
            proc = subprocess.run(executor, shell=True, input=json.dumps(step),
                                  capture_output=True, text=True)
            entry["exit_code"] = proc.returncode
            entry["output"] = proc.stdout
            if proc.returncode != 0:
                entry["stderr"] = proc.stderr
        results.append(entry)

    return {
        "commit": commit_oid,
        "source_commit": recipe.get("source_commit"),
        "goal": recipe["goal"],
        "models": recipe["models"],
        "executed": bool(executor),
        "steps": results,
    }
