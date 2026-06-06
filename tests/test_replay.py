import json

import pytest

from agentvcs import Repository, RepoError, crystallize, replay


def setup_frozen(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "run.jsonl").write_text(
        '{"role":"planner","content":"plan"}\n{"role":"worker","content":"act"}\n')
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "Do the thing",
        "models": [{"provider": "anthropic", "model": "claude-opus-4-8",
                    "params": {"temperature": 1.0}}],
        "trace": "traces/run.jsonl", "state": "fluid"}))
    fluid = repo.commit("fluid")
    frozen, _ = crystallize(repo, fluid)
    return repo, fluid, frozen


def test_replay_emits_frozen_recipe(tmp_path):
    repo, fluid, frozen = setup_frozen(tmp_path)
    result = replay(repo, frozen)
    assert result["commit"] == frozen
    assert result["source_commit"] == fluid
    assert result["goal"] == "Do the thing"
    assert result["models"][0]["params"]["temperature"] == 0  # pinned
    assert [s["step"]["content"] for s in result["steps"]] == ["plan", "act"]
    assert result["executed"] is False


def test_replay_on_fluid_errors(tmp_path):
    repo, fluid, frozen = setup_frozen(tmp_path)
    with pytest.raises(RepoError) as e:
        replay(repo, fluid)
    assert e.value.code == "NOT_CRYSTALLIZED"


def test_replay_with_executor_runs_each_step(tmp_path):
    repo, fluid, frozen = setup_frozen(tmp_path)
    # `cat` echoes the step JSON it receives on stdin back to stdout
    result = replay(repo, frozen, executor="cat")
    assert result["executed"] is True
    assert len(result["steps"]) == 2
    for s in result["steps"]:
        assert s["exit_code"] == 0
        assert json.loads(s["output"]) == s["step"]  # executor saw the exact step


def test_replay_defaults_to_head_after_freeze(tmp_path):
    repo, fluid, frozen = setup_frozen(tmp_path)  # freeze moved HEAD to the crystal
    result = replay(repo)  # no commit arg
    assert result["commit"] == frozen
