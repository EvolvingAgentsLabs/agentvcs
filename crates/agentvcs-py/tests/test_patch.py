import pytest

import agentvcs as avcs
from conftest import PASSING_SUITE, manifest, supervise


def step_manifests(run):
    return [(e["body"]["step_index"], e["body"]["manifest_id"]) for e in run.log() if e["kind"] == "step"]


def test_patch_from_another_process_is_seen_at_the_next_step(store):
    events = []
    with avcs.run(manifest(), store=store, run_id="r") as run:
        run.on_patch(events.append)
        seen = []

        @avcs.step("x")
        def work():
            seen.append(run.manifest["x.prompt"]["template"])

        work()
        m1 = run.manifest.id
        pid = supervise(store, "r", manifest(template="Extract {doc} incl. cap"))
        assert events == []  # nothing polls between steps on its own
        work()
        work()
    assert seen == ["Extract {doc}", "Extract {doc} incl. cap", "Extract {doc} incl. cap"]
    (ev,) = events
    assert ev.patch_id == pid and ev.from_manifest == m1 and ev.applied_at_step == 1
    assert ev.manifest.id == ev.to_manifest == run.manifest.id
    assert ev.author == {"type": "agent", "id": "supervisor"}
    assert "x.prompt" in ev.changed_dimensions
    assert step_manifests(run) == [(0, m1), (1, ev.to_manifest), (2, ev.to_manifest)]
    assert avcs.cli("verify", "r", store=store)["valid"]


def test_sync_polls_without_a_step(store):
    with avcs.run(manifest(), store=store, run_id="r") as run:
        supervise(store, "r", manifest(model="m-2"))
        (ev,) = run.sync()
        assert run.manifest["x.model"]["id"] == "m-2"
        assert run.sync() == []


def test_patch_landing_mid_step_reruns_the_step_under_the_new_manifest(store):
    calls = []
    with avcs.run(manifest(), store=store, run_id="r") as run:
        reloads = []
        run.on_patch(lambda ev: reloads.append(ev.to_manifest))

        @avcs.step("x")
        def work():
            calls.append(run.manifest["x.model"]["id"])
            if len(calls) == 1:  # the supervisor applies a patch while we run
                supervise(store, "r", manifest(model="m-2"))
            return calls[-1]

        assert work() == "m-2"
    assert calls == ["m-1", "m-2"]
    assert run.stats["reruns"] == 1 and len(reloads) == 1
    (only,) = step_manifests(run)
    assert only == (0, reloads[0])


def test_on_race_raise_does_not_rerun(store):
    with avcs.run(manifest(), store=store, run_id="r") as run:

        @avcs.step("x", on_race="raise")
        def work():
            supervise(store, "r", manifest(model="m-2"))

        with pytest.raises(avcs.StepRace):
            work()
    assert step_manifests(run) == []


def test_in_process_apply_and_rollback_fire_on_patch(store, tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text(PASSING_SUITE)
    with avcs.run(manifest(), store=store, run_id="r") as run:
        events = []
        run.on_patch(events.append)
        m1 = run.manifest.id
        pid = run.propose_patch(manifest(temperature=0.0), "greedy", evidence=[])
        with pytest.raises(avcs.AgentvcsError) as ei:
            run.apply_patch(pid)
        assert ei.value.code == "E_PATCH_UNGATED"
        assert run.gate(pid, suite)["passed"] is True
        run.apply_patch(pid)
        assert run.manifest["x.sampling"]["temperature"] == 0.0
        run.rollback(pid)
        assert run.manifest.id == m1
    assert [e.rollback_of for e in events] == [None, pid]


def test_patch_after_run_end_is_refused(store):
    with avcs.run(manifest(), store=store, run_id="r"):
        pass
    with pytest.raises(AssertionError):
        supervise(store, "r", manifest(model="m-2"))
