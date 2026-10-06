import agentvcs as avcs
from conftest import manifest


def test_checkpoint_resume_restore(store):
    state = {"kv": []}
    with avcs.run(manifest(), store=store, run_id="parent") as run:

        @run.checkpoint
        def snap(step):
            return f"kv:{len(state['kv'])}@{step.step_index}"

        @avcs.step("x")
        def work(tok):
            state["kv"].append(tok)

        for t in "abcd":
            work(t)
    refs = [e["body"]["checkpoint_ref"] for e in run.log() if e["kind"] == "step"]
    assert refs == ["kv:1@0", "kv:2@1", "kv:3@2", "kv:4@3"]

    restored = []
    child = run.resume(2, manifest(model="m-2"), run_id="child")
    child.restore(restored.append)
    assert restored == []  # not before entering
    with child:
        assert restored == ["kv:2@1"]  # state after step from_step - 1
        assert child.next_step == 2
        assert child.manifest["x.model"]["id"] == "m-2"
        work("C")
    start = child.log()[0]["body"]
    assert start["parent"] == {"run_id": "parent", "from_step": 2, "checkpoint_ref": "kv:2@1"}
    (s,) = [e["body"] for e in child.log() if e["kind"] == "step"]
    assert s["step_index"] == 2 and s["checkpoint_ref"] == "kv:5@2"  # hook inherited
    assert avcs.cli("verify", "child", store=store)["valid"]


def test_top_level_resume_from_another_process_shape(store):
    with avcs.run(manifest(), store=store, run_id="p") as run:
        run.checkpoint(lambda s: f"ck{s.step_index}")

        @avcs.step("x")
        def work():
            pass

        work()
        work()
    got = []
    child = avcs.resume("p", 1, run.manifest.id, store=store, restore=got.append)
    with child:
        pass
    assert got == ["ck0"]
    assert child.parent["from_step"] == 1


def test_resume_from_zero_restores_none(store):
    with avcs.run(manifest(), store=store, run_id="p") as run:
        pass
    got = []
    with avcs.resume("p", 0, run.manifest.id, store=store, restore=got.append):
        pass
    assert got == [None]
