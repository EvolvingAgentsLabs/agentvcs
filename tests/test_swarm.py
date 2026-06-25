"""Tests for swarm versioning (PR4) — the sub-agent topology as a merge dimension."""
import json

from agentvcs import Repository
from agentvcs.merge import merge
from agentvcs.swarm import build_swarm, merge_swarms


def _init(tmp_path, swarm):
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "orchestrate a swarm",
        "models": [],
        "trace": None,
        "state": "fluid",
        "swarm": swarm,
    }))
    (tmp_path / "main.py").write_text("x = 1\n")
    return repo


def _set_swarm(tmp_path, swarm):
    m = json.loads((tmp_path / "agent.json").read_text())
    m["swarm"] = swarm
    (tmp_path / "agent.json").write_text(json.dumps(m))


# ------------------------------------------------------------------ capture

def test_commit_captures_swarm_dimension(tmp_path):
    """A declared swarm becomes a content-addressed pointer on the commit."""
    repo = _init(tmp_path, {
        "analyst": {"role": "data analyst", "skill": "summarize tables"},
        "writer": {"role": "report writer", "skill": "draft prose"},
    })
    oid = repo.commit("base")
    commit = repo.objects.read_obj(oid)
    assert "swarm" in commit
    swarm = repo.objects.read_obj(commit["swarm"])
    assert set(swarm["nodes"]) == {"analyst", "writer"}
    assert swarm["nodes"]["analyst"]["role"] == "data analyst"


def test_no_swarm_no_pointer(tmp_path):
    """Commits without a declared swarm stay byte-identical (no swarm key)."""
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid"}))
    (tmp_path / "main.py").write_text("x = 1\n")
    commit = repo.objects.read_obj(repo.commit("base"))
    assert "swarm" not in commit


# ------------------------------------------------------------------ node merge unit

def test_merge_swarms_revival_conflict():
    """Retired on one side, evolved on the other → conflict, evolution kept."""
    base = {"type": "swarm", "nodes": {"a": {"role": "x", "skill": "s0", "parent": None}}}
    ours = {"type": "swarm", "nodes": {}}  # ours retired a
    theirs = {"type": "swarm",
              "nodes": {"a": {"role": "x", "skill": "s1", "parent": None}}}  # theirs evolved a
    merged, conflicts = merge_swarms(base, ours, theirs)
    assert "a" in merged["nodes"]                      # revival kept
    assert merged["nodes"]["a"]["skill"] == "s1"
    assert any(c["path"] == "swarm/a" for c in conflicts)


def test_merge_swarms_clean_additions():
    """Each side adds a distinct sub-agent → union, no conflict."""
    base = {"type": "swarm", "nodes": {}}
    ours = {"type": "swarm", "nodes": {"a": {"role": "x", "skill": "s", "parent": None}}}
    theirs = {"type": "swarm", "nodes": {"b": {"role": "y", "skill": "s", "parent": None}}}
    merged, conflicts = merge_swarms(base, ours, theirs)
    assert set(merged["nodes"]) == {"a", "b"}
    assert conflicts == []


def test_merge_swarms_one_sided_evolution():
    """Only ours evolves a node theirs left at base → take ours, no conflict."""
    base = {"type": "swarm", "nodes": {"a": {"role": "x", "skill": "s0", "parent": None}}}
    ours = {"type": "swarm", "nodes": {"a": {"role": "x", "skill": "s1", "parent": None}}}
    theirs = {"type": "swarm", "nodes": {"a": {"role": "x", "skill": "s0", "parent": None}}}
    merged, conflicts = merge_swarms(base, ours, theirs)
    assert merged["nodes"]["a"]["skill"] == "s1"
    assert conflicts == []


# ------------------------------------------------------------------ end-to-end merge

def test_merge_reconciles_swarm_lifecycle(tmp_path):
    """Two branches reshape the swarm; merge reconciles the whole topology."""
    repo = _init(tmp_path, {
        "analyst": {"role": "analyst", "skill": "v0"},
        "writer": {"role": "writer", "skill": "v0"},
    })
    repo.commit("base")

    # feature: retire the analyst, keep writer
    repo.branch("feature")
    repo.checkout("feature")
    _set_swarm(tmp_path, {"writer": {"role": "writer", "skill": "v0"}})
    repo.commit("feature retires analyst")

    # main: evolve the writer, add a reviewer
    repo.checkout("main")
    _set_swarm(tmp_path, {
        "analyst": {"role": "analyst", "skill": "v0"},
        "writer": {"role": "writer", "skill": "v2"},
        "reviewer": {"role": "reviewer", "skill": "v0"},
    })
    repo.commit("main evolves writer + adds reviewer")

    result = merge(repo, "feature", force=True)
    assert result["status"] == "merged"

    commit = repo.objects.read_obj(repo.head_commit())
    swarm = repo.objects.read_obj(commit["swarm"])
    # writer evolved on ours only → kept; reviewer added on ours → kept;
    # analyst retired on theirs, untouched on ours → honored (gone).
    assert "reviewer" in swarm["nodes"]
    assert "writer" in swarm["nodes"]
    assert "analyst" not in swarm["nodes"]


# ------------------------------------------------------------------ auto-derive

def test_build_swarm_auto_from_fanout(tmp_path, monkeypatch):
    """swarm: "auto" derives a node per sub-agent type the runtime fanned out to."""
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid"}))

    monkeypatch.setattr(repo, "_build_runtime_frame", lambda m, msgs: {
        "subagents": [{"type": "classifier", "count": 2},
                      {"type": "search", "count": 1}]})

    swarm = build_swarm(repo, "auto", messages=[])
    assert set(swarm["nodes"]) == {"classifier", "search"}
    assert swarm["nodes"]["classifier"]["count"] == 2
    assert swarm["nodes"]["classifier"]["parent"] == "coordinator"


def test_build_swarm_auto_empty_returns_none(tmp_path, monkeypatch):
    """No fan-out → no derived topology (so no swarm pointer is written)."""
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid"}))
    monkeypatch.setattr(repo, "_build_runtime_frame", lambda m, msgs: {"subagents": []})
    assert build_swarm(repo, {"auto": True}, messages=[]) is None


def test_auto_swarm_merge_lifecycle(tmp_path, monkeypatch):
    """Two branches whose runtimes fanned out differently merge node-by-node."""
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid", "swarm": "auto"}))
    (tmp_path / "main.py").write_text("x = 1\n")

    fanout = {"v": [{"type": "classifier", "count": 1}]}
    monkeypatch.setattr(repo, "_build_runtime_frame", lambda m, msgs: {
        "subagents": fanout["v"]})
    repo.commit("base")

    repo.branch("feature")
    repo.checkout("feature")
    fanout["v"] = [{"type": "classifier", "count": 1}, {"type": "search", "count": 3}]
    (tmp_path / "main.py").write_text("x = 2\n")
    repo.commit("feature adds a searcher")

    repo.checkout("main")
    fanout["v"] = [{"type": "classifier", "count": 1}, {"type": "writer", "count": 1}]
    (tmp_path / "main.py").write_text("x = 3\n")
    repo.commit("main adds a writer")

    result = merge(repo, "feature", force=True)
    assert result["status"] == "merged"
    swarm = repo.objects.read_obj(repo.objects.read_obj(repo.head_commit())["swarm"])
    # both branches' new sub-agents are unioned onto the shared classifier
    assert set(swarm["nodes"]) == {"classifier", "search", "writer"}


def test_build_swarm_from_skill_file(tmp_path):
    """A node skill can be sourced from a working-tree file."""
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": [], "trace": None, "state": "fluid"}))
    (tmp_path / "analyst.md").write_text("You are a data analyst.\n")
    swarm = build_swarm(repo, {"analyst": {"role": "analyst",
                                           "skill_file": "analyst.md"}})
    blob = repo.objects.read_blob(swarm["nodes"]["analyst"]["skill"])
    assert b"data analyst" in blob
