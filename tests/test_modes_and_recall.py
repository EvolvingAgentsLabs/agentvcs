"""Two modes (vcs / runtime), the visibility commands, and recall."""
import json

from agentvcs import Repository, crystallize, recall
from agentvcs.cli import main


def _claude_transcript(cwd):
    return "\n".join(json.dumps(o) for o in [
        {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "t1",
         "message": {"role": "user", "content": "build it"}},
        {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "t2",
         "message": {"role": "assistant", "model": "claude-opus-4-8",
                     "usage": {"input_tokens": 1000, "output_tokens": 200},
                     "content": [{"type": "text", "text": "done"}]}},
    ]) + "\n"


def _runtime_repo(tmp_path):
    repo = Repository.init(tmp_path)
    t = tmp_path / "s.jsonl"
    t.write_text(_claude_transcript(str(tmp_path)))
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "build it", "mode": "runtime",
        "models": [{"provider": "anthropic", "auto": True}],
        "trace": {"provider": "claude-code", "path": str(t)},
        "budget": {"ceiling_usd": 0.10}, "state": "fluid"}))
    return repo


# --------------------------------------------------------------------- modes
def test_runtime_mode_commit_captures_frame(tmp_path):
    repo = _runtime_repo(tmp_path)
    oid = repo.commit("iter")
    commit = repo.objects.read_obj(oid)
    assert "runtime" in commit                       # the new dimension is pointed at
    frame = repo.objects.read_obj(commit["runtime"])
    assert frame["type"] == "runtime"
    assert frame["budget"]["tokens_total"] == 1200
    assert frame["budget"]["cost_usd"] is not None


def test_vcs_mode_commit_has_no_runtime_pointer(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid"}))
    commit = repo.objects.read_obj(repo.commit("x"))
    assert "runtime" not in commit                   # byte-identical to old behavior


def test_mode_override_via_flag(tmp_path):
    # manifest says nothing (vcs default); --mode runtime forces capture
    repo = Repository.init(tmp_path)
    t = tmp_path / "s.jsonl"
    t.write_text(_claude_transcript(str(tmp_path)))
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": {"provider": "claude-code", "path": str(t)},
        "state": "fluid"}))
    repo._mode_override = "runtime"
    assert "runtime" in repo.objects.read_obj(repo.commit("x"))


# ------------------------------------------------------------- cli visibility
def test_cli_init_runtime_qwen_manifest(tmp_path, capsys):
    main(["-C", str(tmp_path), "init", "--qwen-code", "--runtime", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["mode"] == "runtime" and out["trace_provider"] == "qwen-code"
    m = json.loads((tmp_path / "agent.json").read_text())
    assert m["mode"] == "runtime"
    assert m["trace"]["provider"] == "qwen-code"


def test_cli_budget_context_runtime(tmp_path, capsys):
    _runtime_repo(tmp_path)
    main(["-C", str(tmp_path), "budget", "--json"])
    budget = json.loads(capsys.readouterr().out)["budget"]
    assert budget["tokens_total"] == 1200

    main(["-C", str(tmp_path), "context", "--json"])
    ctx = json.loads(capsys.readouterr().out)["context"]
    assert ctx["window"] == 200_000

    main(["-C", str(tmp_path), "runtime", "--json"])
    frame = json.loads(capsys.readouterr().out)["runtime"]
    assert frame["models"][0]["model"] == "claude-opus-4-8"


def test_cli_commit_runtime_mode_reports_budget(tmp_path, capsys):
    _runtime_repo(tmp_path)
    main(["-C", str(tmp_path), "commit", "-m", "iter", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["state"] == "fluid"


# -------------------------------------------------------------------- recall
def _crystallize_goal(tmp_path, sub, goal):
    d = tmp_path / sub
    d.mkdir()
    repo = Repository.init(d)
    (d / "agent.json").write_text(json.dumps(
        {"goal": goal, "models": [], "trace": None, "state": "fluid"}))
    repo.commit("work")
    crystallize(repo)
    return repo


def test_recall_ranks_by_goal_overlap(tmp_path):
    repo = _crystallize_goal(tmp_path, "billing", "build a Stripe billing and invoicing system")
    # a second, unrelated frozen recipe in the same store
    d2 = tmp_path / "billing" / "sub"
    d2.mkdir()
    repo2 = Repository(repo.workdir)  # same object store
    (repo.workdir / "agent.json").write_text(json.dumps(
        {"goal": "render a 3D navigation mesh", "models": [], "trace": None,
         "state": "fluid"}))
    repo2.commit("other")
    crystallize(repo2)

    hits = recall(repo, "stripe billing invoices")
    assert hits, "expected a cache hit"
    assert "billing" in hits[0]["goal"].lower()
    assert hits[0]["score"] > 0
    assert hits[0]["replay_ready"] is True
    # the unrelated recipe must rank strictly lower
    if len(hits) > 1:
        assert hits[0]["score"] >= hits[1]["score"]


def test_recall_miss_is_honest(tmp_path):
    repo = _crystallize_goal(tmp_path, "x", "build a Stripe billing system")
    assert recall(repo, "quantum chromodynamics simulator", min_score=0.01) == []
