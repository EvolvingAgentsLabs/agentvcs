import json

from agentvcs import Repository, crystallize


def setup_repo(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "run.jsonl").write_text(
        '{"role":"planner","content":"decide"}\n{"role":"worker","content":"do"}\n')
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "Refund flow",
        "models": [{"provider": "anthropic", "model": "claude-opus-4-8",
                    "params": {"temperature": 1.0}}],
        "trace": "traces/run.jsonl",
        "state": "fluid",
    }))
    return repo


def test_crystallize_pins_models_and_writes_recipe(tmp_path):
    repo = setup_repo(tmp_path)
    fluid = repo.commit("fluid solution")

    new_oid, artifact = crystallize(repo, fluid)
    new = repo.objects.read_obj(new_oid)

    assert new["state"] == "crystallized"
    assert new["parents"] == [fluid]
    # models pinned to deterministic decoding
    model = repo.objects.read_obj(new["models"][0])
    assert model["params"]["temperature"] == 0
    assert model["params"]["top_p"] == 1
    # original fluid commit is untouched
    assert repo.objects.read_obj(fluid)["state"] == "fluid"
    # recipe artifact exists and replays the trace steps
    assert artifact.exists()
    recipe = json.loads(artifact.read_text())
    assert recipe["goal"] == "Refund flow"
    assert len(recipe["steps"]) == 2


def test_crystallize_twice_is_rejected(tmp_path):
    repo = setup_repo(tmp_path)
    repo.commit("fluid")
    new_oid, _ = crystallize(repo)
    import pytest
    from agentvcs import RepoError
    with pytest.raises(RepoError):
        crystallize(repo, new_oid)
