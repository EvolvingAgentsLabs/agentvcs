"""merge_prepare / merge_commit: thin wrappers over the CLI (spec/MERGE.md, v0.2 draft)."""

import json

import pytest

import agentvcs as avcs
from conftest import PASSING_SUITE, manifest, supervise

FAILING_SUITE = 'command: "echo \'{\\"ok\\": 0}\'"\nthresholds:\n  ok: {op: ">=", value: 1}\n'


def write(path, value):
    with open(path, "w") as f:
        f.write(value if isinstance(value, str) else json.dumps(value))
    return path


def diverged(store):
    """A run patched (gated) from base to ours; theirs edits the same prompt."""
    base = manifest()
    with avcs.run(base, store=store, run_id="r") as run:

        @avcs.step("x")
        def work(f1):
            avcs.current_step().metric("f1", f1)

        work(0.3)
        work(0.3)
        base_id = run.manifest.id
        pid = supervise(store, "r", manifest(template="Extract {doc} incl. cap"))
        work(0.7)
        work(0.7)
        ours_id = run.manifest.id
    theirs = write(store / "theirs.json", manifest(template="Extract {doc} and cite", temperature=0.1))
    return base_id, ours_id, theirs, pid


def test_prepare_shows_the_gated_patch_as_evidence(store):
    base, ours, theirs, pid = diverged(store)
    out = avcs.merge_prepare(base, ours, theirs, ours_run="r", metrics=["f1"], store=store)
    assert out["ok"] and out["ours"] == ours
    assert {a["dimension"]: a["resolution"] for a in out["auto"]} == {
        "x.model": "same", "x.sampling": "theirs"}
    (c,) = out["conflicts"]
    assert (c["dimension"], c["type"]) == ("x.prompt", "modify/modify")
    (ev,) = c["evidence"]["ours"]
    assert ev["patch_id"] == pid and ev["gate"]["passed"] is True
    assert ev["blame"]["f1"] == pytest.approx(0.4)
    assert c["evidence"]["theirs"] == []
    # the same JSON as the CLI
    assert out == avcs.cli("merge", "prepare", "--base", base, "--ours", ours, "--theirs", str(theirs),
                           "--ours-run", "r", "--metric", "f1", store=store)


def test_commit_gates_and_records(store):
    base, ours, theirs, _ = diverged(store)
    prep = avcs.merge_prepare(base, ours, theirs, store=store)
    res = write(store / "res.json", {
        "protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": prep["merge_id"],
        "resolutions": {"x.prompt": {"kind": "prompt", "content": {
            "template": "Extract {doc} incl. cap and cite", "variables": ["doc"], "system": "be brief"}}},
        "rationale": "kept both", "author": {"type": "agent", "id": "claude-code"}})
    failed = avcs.merge_commit(base, ours, theirs, res, suite=write(store / "f.yaml", FAILING_SUITE), store=store)
    assert failed["ok"] and failed["gate"]["passed"] is False
    out = avcs.merge_commit(base, ours, theirs, res, suite=write(store / "s.yaml", PASSING_SUITE), store=store)
    assert out["gate"]["passed"] is True and out["merge_id"] == prep["merge_id"]
    assert out["record"] != failed["record"]
    s = avcs.open_store(store, init=False)
    record = json.loads(s.get_object(out["record"]))
    assert record["type"] == "merge_record" and record["merged"] == out["merged"]
    merged = s.get_manifest(out["merged"])
    assert merged["parent_ids"] == [ours, prep["theirs"]]
    assert merged["dimensions"]["x.sampling"]["content"]["temperature"] == 0.1


def test_commit_errors_carry_the_protocol_code(store):
    base, ours, theirs, _ = diverged(store)
    res = write(store / "res.json", {
        "protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": "b3:" + "0" * 64,
        "resolutions": {"x.prompt": {"take": "ours"}}, "rationale": "r",
        "author": {"type": "agent", "id": "t"}})
    with pytest.raises(avcs.AgentvcsError) as e:
        avcs.merge_commit(base, ours, theirs, res, store=store)
    assert e.value.code == "E_MERGE_STALE"
