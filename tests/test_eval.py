"""The eval/score gate: prove a solution works before it can be frozen or recalled."""
import json

import pytest

from agentvcs import Repository, RepoError, crystallize, recall, run_eval
from agentvcs.cli import main


def _repo(tmp_path, command=None, goal="build a thing", **evalkw):
    repo = Repository.init(tmp_path)
    manifest = {"goal": goal, "models": [], "trace": None, "state": "fluid"}
    if command is not None:
        manifest["eval"] = {"command": command, **evalkw}
    (tmp_path / "agent.json").write_text(json.dumps(manifest))
    repo.commit("work")
    return repo


# ------------------------------------------------------------------ run_eval
def test_eval_pass_records_score(tmp_path):
    repo = _repo(tmp_path, "true")
    r = run_eval(repo)
    assert r["ok"] and r["passed"] == 1 and r["total"] == 1 and r["score"] == 1.0
    # persisted to the side-table keyed by commit, not in the commit object
    assert repo.read_eval(repo.head_commit())["ok"] is True
    assert "eval" not in repo.objects.read_obj(repo.head_commit())


def test_eval_fail(tmp_path):
    repo = _repo(tmp_path, "false")
    r = run_eval(repo)
    assert r["ok"] is False and r["score"] == 0.0


def test_eval_runs_all_must_pass(tmp_path):
    repo = _repo(tmp_path, "true", runs=3)
    r = run_eval(repo)
    assert r["passed"] == 3 and r["total"] == 3 and r["ok"]


def test_eval_score_command_overrides_passrate(tmp_path):
    repo = _repo(tmp_path, "true", score_command="echo 0.87")
    r = run_eval(repo)
    assert r["score"] == 0.87 and r["ok"]


def test_eval_requires_declaration(tmp_path):
    repo = _repo(tmp_path)  # no eval in manifest
    with pytest.raises(RepoError) as e:
        run_eval(repo)
    assert e.value.code == "NO_EVAL"


# --------------------------------------------------------------- freeze gate
def test_freeze_blocked_on_failing_eval(tmp_path):
    repo = _repo(tmp_path, "false")
    with pytest.raises(RepoError) as e:
        crystallize(repo)                 # auto-runs the eval, which fails
    assert e.value.code == "EVAL_FAILED"


def test_freeze_force_overrides_gate(tmp_path):
    repo = _repo(tmp_path, "false")
    new_oid, _ = crystallize(repo, force=True)
    recipe = repo.objects.read_obj(repo.objects.read_obj(new_oid)["crystal"])
    assert recipe["verified"] is False    # honest: force-frozen, not proven


def test_freeze_passes_when_eval_passes_and_marks_verified(tmp_path):
    repo = _repo(tmp_path, "true")
    new_oid, _ = crystallize(repo)        # auto-runs eval, passes, then freezes
    recipe = repo.objects.read_obj(repo.objects.read_obj(new_oid)["crystal"])
    assert recipe["verified"] is True
    assert recipe["eval"]["command"] == "true"
    # the crystallized commit itself reads as verified (the oid recall ranks on)
    assert repo.read_eval(new_oid)["ok"] is True


def test_freeze_ungated_when_no_eval_declared(tmp_path):
    repo = _repo(tmp_path)                 # no eval => no gate (back-compat)
    new_oid, _ = crystallize(repo)
    recipe = repo.objects.read_obj(repo.objects.read_obj(new_oid)["crystal"])
    assert recipe["verified"] is False


# -------------------------------------------------------- recall trust order
def test_recall_ranks_verified_first(tmp_path):
    repo = _repo(tmp_path, "true", goal="build a billing system")
    a_oid, _ = crystallize(repo)          # verified
    # a second, unverified recipe with an overlapping goal in the same store
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "billing reports module", "models": [], "trace": None,
        "state": "fluid", "eval": {"command": "true"}}))
    repo.commit("b")
    b_oid, _ = crystallize(repo, force=True)   # skip the gate -> unverified

    hits = recall(repo, "billing")
    assert hits[0]["commit"] == a_oid and hits[0]["verified"] is True
    # verified_only drops the unverified one entirely
    vonly = recall(repo, "billing", verified_only=True)
    assert {h["commit"] for h in vonly} == {a_oid}
    assert all(h["commit"] != b_oid for h in vonly)


# --------------------------------------------------------------- cli surface
def test_cli_eval_and_gated_freeze(tmp_path, capsys):
    _repo(tmp_path, "false")
    main(["-C", str(tmp_path), "eval", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True            # the command ran fine...
    assert out["passing"] is False      # ...but the eval did not pass

    # freeze is blocked by the gate
    main(["-C", str(tmp_path), "freeze", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["error"]["code"] == "EVAL_FAILED"

    # --force pushes it through, flagged unverified
    main(["-C", str(tmp_path), "freeze", "--force", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["verified"] is False
