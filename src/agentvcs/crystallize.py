"""Crystallization — freezing a fluid agent into a deterministic recipe.

While a commit is ``fluid`` it evolves probabilistically: models run at high
temperature, code and goals mutate between iterations. Once a sub-problem is
solved well enough, you ``freeze`` it. Crystallization:

  1. pins every model to deterministic decoding (temperature 0, top_p 1),
  2. extracts the message trace into an ordered, replayable recipe of steps,
  3. emits a human-readable artifact under ``crystal/<commit>.json``, and
  4. records a new ``crystallized`` commit whose parent is the fluid one.

The result is a frozen path that can be re-executed cheaply and predictably,
without burning tokens re-deriving a solution you already trust.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .repository import Repository, RepoError


def crystallize(repo: Repository, commit_oid: str | None = None,
                message: str | None = None, timestamp: int | None = None):
    commit_oid = commit_oid or repo.head_commit()
    if not commit_oid:
        raise RepoError("nothing to crystallize (no commits yet)")

    commit = repo.objects.read_obj(commit_oid)
    if commit["state"] == "crystallized":
        raise RepoError(f"{commit_oid[:12]} is already crystallized")

    # 1. pin models to deterministic decoding
    frozen_models = []
    for moid in commit["models"]:
        m = repo.objects.read_obj(moid)
        params = dict(m.get("params") or {})
        params["temperature"] = 0
        params["top_p"] = 1
        frozen_models.append(repo.objects.write_obj({**m, "params": params}))

    # 2. extract the replayable recipe
    goal = repo.objects.read_obj(commit["goal"])
    steps = []
    if commit.get("trace"):
        steps = repo.objects.read_obj(commit["trace"])["messages"]
    recipe = {
        "type": "crystal",
        "source_commit": commit_oid,
        "goal": goal.get("text", ""),
        "models": [repo.objects.read_obj(o) for o in frozen_models],
        "steps": steps,
    }
    recipe_oid = repo.objects.write_obj(recipe)

    # 3. human-readable artifact in the working tree
    crystal_dir = repo.workdir / "crystal"
    crystal_dir.mkdir(exist_ok=True)
    artifact = crystal_dir / f"{commit_oid[:12]}.json"
    artifact.write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")

    # 4. record the crystallized commit
    new_commit = {
        **commit,
        "parents": [commit_oid],
        "models": frozen_models,
        "state": "crystallized",
        "crystal": recipe_oid,
        "message": message or f"crystallize {commit_oid[:12]}",
        "timestamp": timestamp if timestamp is not None else int(time.time()),
    }
    new_oid = repo.objects.write_obj(new_commit)
    repo._set_head_commit(new_oid)
    return new_oid, artifact
