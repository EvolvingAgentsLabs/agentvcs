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


def _check_no_conflict_markers(repo) -> None:
    """Raise RepoError if any tracked file contains git-style conflict markers."""
    from .repository import DEFAULT_IGNORE
    patterns = repo._ignore_patterns()
    marker = b"<<<<<<< ours"
    for path in sorted(repo.workdir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo.workdir)
        if repo._ignored(rel, patterns):
            continue
        try:
            data = path.read_bytes()
            if marker in data:
                raise RepoError(
                    f"conflict markers found in {rel} — resolve conflicts before freezing",
                    code="CONFLICT_MARKERS")
        except (OSError, PermissionError):
            pass


def crystallize(repo: Repository, commit_oid: str | None = None,
                message: str | None = None, timestamp: int | None = None,
                force: bool = False):
    commit_oid = repo._resolve(commit_oid, expect="commit") if commit_oid else repo.head_commit()
    if not commit_oid:
        raise RepoError("nothing to crystallize (no commits yet)", code="NO_COMMITS")

    commit = repo.objects.read_obj(commit_oid)
    if commit["state"] == "crystallized":
        raise RepoError(f"{commit_oid[:12]} is already crystallized",
                        code="ALREADY_CRYSTALLIZED")

    # Guard: refuse to freeze while conflict markers exist in the working tree
    _check_no_conflict_markers(repo)

    # the eval gate: if agent.json declares an eval, a commit must pass it before
    # it can be frozen — so a "deterministic recipe" is also a *verified* one.
    # No eval declared => no gate (freeze stays exactly as it was). --force skips.
    eval_result = repo.read_eval(commit_oid)
    if repo.read_manifest().get("eval") and not force:
        from .eval import ensure_passing
        eval_result = ensure_passing(repo, commit_oid)

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
        # the recipe carries its own proof: how it was verified, and the score.
        "verified": bool(eval_result and eval_result.get("ok")),
        "eval": ({"command": eval_result["command"], "score": eval_result["score"],
                  "passed": eval_result["passed"], "total": eval_result["total"]}
                 if eval_result else None),
    }
    recipe_oid = repo.objects.write_obj(recipe)

    # 3. human-readable artifact in the working tree
    crystal_dir = repo.workdir / "crystal"
    crystal_dir.mkdir(exist_ok=True)
    artifact = crystal_dir / f"{commit_oid[:12]}.json"
    artifact.write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")

    # 4. record the crystallized commit (re-signed by this instance's Soul; drop
    #    the parent's stale soul/signature before write_commit re-stamps fresh ones)
    new_commit = {
        **{k: v for k, v in commit.items() if k not in ("soul", "signature")},
        "parents": [commit_oid],
        "models": frozen_models,
        "state": "crystallized",
        "crystal": recipe_oid,
        "message": message or f"crystallize {commit_oid[:12]}",
        "timestamp": timestamp if timestamp is not None else int(time.time()),
    }
    new_oid = repo.write_commit(new_commit)
    repo._set_head_commit(new_oid)
    # carry the verification forward so the crystallized commit reads as verified
    # too (this is the oid recall ranks on).
    if eval_result:
        repo.write_eval(new_oid, eval_result)

    # 5. DeSoc: a *verified* crystallization is a proven accomplishment — mint a
    #    Soulbound Token onto this instance's Soul. Best-effort: an un-souled repo
    #    or an unverified (--force) freeze simply mints nothing.
    if recipe.get("verified"):
        try:
            from .sbt import issue_sbt
            issue_sbt(repo, new_oid, eval_result, goal_text=goal.get("text", ""))
        except Exception:
            pass

    return new_oid, artifact
