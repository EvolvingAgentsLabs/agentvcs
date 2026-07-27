"""The eval/score gate — the trust layer agentvcs versions but a runtime never does.

agentvcs already versions four things and freezes the trusted ones into recipes.
But "trusted" was an honor system: ``freeze`` would crystallize a commit whether or
not the solution actually worked, so a "deterministic recipe" could be
deterministically wrong, and ``recall`` would happily hand it back.

The eval gate closes that hole. You declare, in ``agent.json``, how to *prove* a
solution works::

    "eval": {
      "command": "pytest -q",     # exit 0 = pass (override with "passing")
      "runs": 3,                  # run N times; pass only if ALL pass (flake gate)
      "score_command": "..."      # optional: prints a numeric score to stdout
    }                             # (or just  "eval": "pytest -q")

``agentvcs eval`` runs it and records the result in a side-table keyed by commit id
(``.agentvcs/evals/<oid>.json``). It is deliberately **not** part of the commit
object: the same code+goal+trace must keep the same content id even if a test
flakes — eval is a *measurement about* a commit, not part of its identity.

Two things consume the measurement:
  * ``freeze`` refuses to crystallize a commit that hasn't passed its eval (unless
    forced) — and stamps the frozen recipe with its proof.
  * ``recall`` surfaces ``verified`` recipes first, so an agent replays a solution
    that is *known* to work, not merely one that looks similar.

Why the gate must *reject*, not just *score* (kinetic proofreading). Hopfield/Ninio
proofreading lowers an error rate only when the intermediate is **discarded
irreversibly** between stages; a stage that merely re-scores and lets the candidate
proceed buys nothing. ``freeze``'s hard ``EVAL_FAILED`` is exactly that irreversible
discard, which is what makes a crystallized recipe trustworthy. It also means
per-edit verification is the high-leverage knob: chaining ``n`` independent
reject-capable evals drives the break-rate ``μ`` down like ``εⁿ``, and in the Eigen
bound ``μL < ln σ`` (see ``dynamics.price``) halving ``μ`` roughly doubles the spec
size you can safely self-modify — a far better return than sharpening ``σ``.
"""
from __future__ import annotations

import re
import subprocess
import time

from .repository import Repository, RepoError

_FLOAT = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_score(text: str):
    """Pull the first number out of a score command's stdout (handles ``0.95``,
    ``score: 0.95``, ``92%`` → 92.0)."""
    m = _FLOAT.search(text or "")
    return float(m.group()) if m else None


def _normalize(decl) -> dict:
    if isinstance(decl, str):
        return {"command": decl}
    if isinstance(decl, dict):
        return decl
    raise RepoError("invalid 'eval' in agent.json (want a string or object)",
                    code="BAD_EVAL")


def run_eval(repo: Repository, commit_oid: str | None = None, *,
             store: bool = True, timestamp: int | None = None) -> dict:
    """Run the declared eval against the working tree and attribute the result to
    a commit (default HEAD). Returns the result dict and, when ``store``, writes it
    to the side-table so ``freeze``/``recall`` can read it."""
    manifest = repo.read_manifest()
    decl = manifest.get("eval")
    if not decl:
        raise RepoError("no 'eval' declared in agent.json — add "
                        '"eval": {"command": "..."} to gate freeze on a real check',
                        code="NO_EVAL")
    decl = _normalize(decl)
    cmd = decl.get("command")
    if not cmd:
        raise RepoError("eval.command is required", code="BAD_EVAL")

    oid = repo._resolve(commit_oid, expect="commit") if commit_oid else repo.head_commit()
    if not oid:
        raise RepoError("nothing to evaluate (no commits yet)", code="NO_COMMITS")

    runs = max(1, int(decl.get("runs", 1)))
    passing = int(decl.get("passing", 0))   # exit code that counts as a pass
    results, passes = [], 0
    for i in range(runs):
        proc = subprocess.run(cmd, shell=True, cwd=repo.workdir,
                              capture_output=True, text=True)
        ok = proc.returncode == passing
        passes += int(ok)
        results.append({"run": i, "exit_code": proc.returncode, "ok": ok,
                        "stdout_tail": (proc.stdout or "")[-800:],
                        "stderr_tail": (proc.stderr or "")[-400:]})

    # score: an explicit score_command wins; otherwise the pass rate is the score.
    score = None
    score_cmd = decl.get("score_command")
    if score_cmd:
        sp = subprocess.run(score_cmd, shell=True, cwd=repo.workdir,
                            capture_output=True, text=True)
        score = _parse_score(sp.stdout)
    if score is None:
        score = round(passes / runs, 4)

    result = {
        "commit": oid,
        "command": cmd,
        "runs": runs,
        "passed": passes,
        "total": runs,
        "passing_exit": passing,
        "score": score,
        "ok": passes == runs,                 # ALL runs must pass — flake-resistant
        "results": results,
        "ts": timestamp if timestamp is not None else int(time.time()),
    }
    if store:
        repo.write_eval(oid, result)
    return result


def ensure_passing(repo: Repository, commit_oid: str, *, auto_run: bool = True) -> dict:
    """Return a *passing* eval result for ``commit_oid`` or raise. Used by the
    freeze gate. If none is recorded and ``auto_run``, run it now."""
    result = repo.read_eval(commit_oid)
    if result is None:
        if not auto_run:
            raise RepoError(f"{commit_oid[:12]} has no eval recorded — run "
                            "`agentvcs eval` first (or freeze --force)",
                            code="UNVERIFIED")
        result = run_eval(repo, commit_oid)
    if not result.get("ok"):
        raise RepoError(
            f"{commit_oid[:12]} failed its eval "
            f"({result['passed']}/{result['total']} runs passing) — fix it or "
            "freeze --force to override the gate",
            code="EVAL_FAILED")
    return result
