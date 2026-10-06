import json

import pytest

import agentvcs as avcs
from conftest import manifest


def steps(run):
    return [e["body"] for e in run.log() if e["kind"] == "step"]


def test_step_records_hashes_tokens_latency_metrics(store):
    with avcs.run(manifest(), store=store, run_id="r") as run:

        @avcs.step(agent_id="extractor")
        def extract(doc, *, upper=False):
            s = avcs.current_step()
            assert s.agent_id == "extractor" and s.step_index == 0
            s.add_tokens(10, 3)
            s.metric("f1", 0.5)
            return {"party": doc.upper() if upper else doc}

        assert extract("acme", upper=True) == {"party": "ACME"}
    (b,) = steps(run)
    assert b["agent_id"] == "extractor" and b["step_index"] == 0
    assert b["manifest_id"] == run.manifest.id
    assert b["tokens"] == {"in": 10, "out": 3}
    assert b["metrics"] == {"f1": 0.5}
    assert b["latency_ms"] >= 0 and b["started_at"] <= b["ended_at"]
    assert b["checkpoint_ref"] is None
    # inputs: the positional arg (raw UTF-8) + kwargs (canonical JSON); outputs: result
    assert run.get(b["inputs"][0]) == b"acme"
    assert json.loads(run.get(b["inputs"][1])) == {"upper": True}
    assert json.loads(run.get(b["outputs"][0])) == {"party": "ACME"}
    assert b["outputs"][0] == avcs.hash_json({"party": "ACME"})


def test_agent_id_defaults_to_function_name_and_steps_count_up(store):
    with avcs.run(manifest(), store=store) as run:

        @avcs.step()
        def summarize(x):
            return None

        for i in range(3):
            summarize(i)
    assert [(b["agent_id"], b["step_index"], b["outputs"]) for b in steps(run)] == [
        ("summarize", i, []) for i in range(3)
    ]


def test_inputs_outputs_and_metrics_overrides(store):
    with avcs.run(manifest(), store=store) as run:

        @avcs.step("c", inputs=lambda obj: [obj["id"]], outputs=lambda r: [r, "extra"],
                   metrics=lambda r, obj: {"len": len(r)})
        def check(obj):
            return "ok"

        check({"id": "doc-1", "handle": object()})
    (b,) = steps(run)
    assert [run.get(h) for h in b["inputs"]] == [b"doc-1"]
    assert [run.get(h) for h in b["outputs"]] == [b"ok", b"extra"]
    assert b["metrics"] == {"len": 2}


def test_unhashable_input_says_how_to_fix_it(store):
    with avcs.run(manifest(), store=store):

        @avcs.step("a")
        def f(x):
            return 1

        with pytest.raises(TypeError, match="inputs="):
            f(object())


def test_step_outside_a_run_raises(store):
    @avcs.step("a")
    def f():
        return 1

    with pytest.raises(avcs.NoActiveRun):
        f()


def test_steps_do_not_nest(store):
    with avcs.run(manifest(), store=store):

        @avcs.step("inner")
        def inner():
            return 1

        @avcs.step("outer")
        def outer():
            return inner()

        with pytest.raises(RuntimeError, match="nest"):
            outer()


def test_a_failing_step_is_not_recorded_and_fails_the_run(store):
    with pytest.raises(ZeroDivisionError):
        with avcs.run(manifest(), store=store) as run:

            @avcs.step("a")
            def f():
                return 1 / 0

            f()
    assert [e["kind"] for e in run.log()] == ["run_start", "run_end"]
    assert run.log()[-1]["body"]["status"] == "failed"


def test_nan_metric_is_refused(store):
    with avcs.run(manifest(), store=store):

        @avcs.step("a")
        def f():
            avcs.current_step().metric("m", float("nan"))

        with pytest.raises(ValueError):
            f()
