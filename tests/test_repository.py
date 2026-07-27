import json

import pytest

from agentvcs import Repository, RepoError, diff_commits


def write_manifest(path, goal, models, trace=None, state="fluid"):
    (path / "agent.json").write_text(json.dumps({
        "goal": goal, "models": models, "trace": trace, "state": state,
    }))


def test_init_creates_metadata_and_template(tmp_path):
    Repository.init(tmp_path)
    assert (tmp_path / ".agentvcs" / "HEAD").exists()
    assert (tmp_path / "agent.json").exists()
    with pytest.raises(RepoError):
        Repository.init(tmp_path)  # refuses to re-init


def test_commit_captures_all_dimensions(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "run.jsonl").write_text(
        '{"role":"planner","content":"plan"}\n{"role":"worker","content":"act"}\n')
    write_manifest(tmp_path, "Solve refunds",
                   [{"provider": "anthropic", "model": "claude-opus-4-8",
                     "params": {"temperature": 1.0}}],
                   trace="traces/run.jsonl")

    oid = repo.commit("first")
    commit = repo.objects.read_obj(oid)
    assert repo.objects.read_obj(commit["goal"])["text"] == "Solve refunds"
    assert len(commit["models"]) == 1
    assert len(repo.objects.read_obj(commit["trace"])["messages"]) == 2
    assert commit["state"] == "fluid"
    assert "main.py" in repo.objects.read_obj(commit["tree"])["entries"]


def test_log_follows_first_parent(tmp_path):
    repo = Repository.init(tmp_path)
    write_manifest(tmp_path, "g", [])
    a = repo.commit("a")
    (tmp_path / "f.txt").write_text("x")
    b = repo.commit("b")
    history = [oid for oid, _ in repo.log()]
    assert history == [b, a]


def test_dimensional_diff_isolates_changes(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1")
    write_manifest(tmp_path, "Goal A",
                   [{"provider": "anthropic", "model": "claude-opus-4-8",
                     "params": {"temperature": 1.0}}])
    a = repo.commit("a")

    # change only the goal — code/models must report no change
    write_manifest(tmp_path, "Goal B",
                   [{"provider": "anthropic", "model": "claude-opus-4-8",
                     "params": {"temperature": 1.0}}])
    b = repo.commit("b")
    d = diff_commits(repo, a, b)
    assert d["goal"] == {"from": "Goal A", "to": "Goal B"}
    assert d["models"] is None
    # the goal lives in agent.json, so that file moves — but application code does not
    assert "f.txt" not in d["code"]["modified"]
    assert d["code"]["modified"] == ["agent.json"]

    # now change only code
    (tmp_path / "f.txt").write_text("v2")
    c = repo.commit("c")
    d2 = diff_commits(repo, b, c)
    assert d2["goal"] is None
    assert d2["code"]["modified"] == ["f.txt"]


def test_branch_and_checkout_restores_tree(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("on main")
    write_manifest(tmp_path, "g", [])
    repo.commit("main commit")

    repo.branch("experiment")
    repo.checkout("experiment")
    (tmp_path / "f.txt").write_text("on experiment")
    (tmp_path / "new.txt").write_text("only on experiment")
    repo.commit("experiment commit")

    repo.checkout("main")
    assert (tmp_path / "f.txt").read_text() == "on main"
    assert not (tmp_path / "new.txt").exists()  # removed on checkout

    repo.checkout("experiment")
    assert (tmp_path / "f.txt").read_text() == "on experiment"
    assert (tmp_path / "new.txt").read_text() == "only on experiment"
