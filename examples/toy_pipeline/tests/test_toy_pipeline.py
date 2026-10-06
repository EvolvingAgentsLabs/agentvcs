"""Gate F2 (offline half): the toy pipeline, patched mid-run by a supervisor
process through the CLI, hot-reloads through on_patch, and blame attributes the
improvement to that patch. The --no-reload control shows the metric moves only
through the reload channel — so the attribution is not produced by the fake
backend or the scorer on their own."""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_pipeline(workdir, *extra):
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, "run_pipeline.py"), "--backend", "fake",
         "--docs", "16", "--patch-after", "3", "--workdir", str(workdir), *extra],
        capture_output=True, text=True, timeout=300,
    )
    result_path = os.path.join(str(workdir), "result.json")
    assert os.path.exists(result_path), p.stdout[-3000:] + p.stderr[-3000:]
    with open(result_path) as f:
        return p.returncode, json.load(f), p.stdout


def ledger(workdir):
    with open(os.path.join(str(workdir), "toy.audit.json")) as f:
        return json.load(f)["ledger"]


def test_blame_attributes_the_improvement_to_the_supervisors_patch(tmp_path):
    rc, r, out = run_pipeline(tmp_path)
    assert rc == 0, out
    patches = [e["body"] for e in ledger(tmp_path) if e["kind"] == "patch"]
    assert len(patches) == 1
    p = patches[0]
    assert p["patch_id"] == r["patch_id"]
    assert p["author"] == {"type": "agent", "id": "supervisor-v0"}
    assert p["gate_result"]["passed"] is True and p["evidence"]
    assert r["verify"] is True
    # the harness learned about the patch through on_patch, at the step it applies to
    assert [x["patch_id"] for x in r["harness"]["reloads"]] == [p["patch_id"]]
    assert r["applied_at_step"] == p["applied_at_step"]

    b = r["blame"]["extract.recall"]
    first, second = b["segments"]
    assert first["from_step"] == 0 and second["from_step"] == p["applied_at_step"]
    assert first["n"] >= 1 and second["n"] >= 1
    assert first["mean"] == pytest.approx(2 / 3) and second["mean"] == pytest.approx(1.0)
    (attr,) = b["attributions"]
    assert attr["patches"] == [p["patch_id"]]
    assert attr["delta"] == pytest.approx(1 / 3)
    # Downstream agents improve under the same patch, but not by exactly 1: the
    # patch lands between steps, so a document extracted under v1 can be checked
    # or summarized under v2 and is credited to the patch anyway. That is the
    # confound BLAME.md warns about (blame names the boundary, not the cause).
    assert 0.5 < b_delta(r, "summary.mentions_cap") <= 1.0
    assert 0.5 < b_delta(r, "check.ok") <= 1.0


def b_delta(r, metric):
    (attr,) = r["blame"][metric]["attributions"]
    return attr["delta"]


def test_control_harness_that_ignores_patches_gets_no_credit(tmp_path):
    rc, r, out = run_pipeline(tmp_path, "--no-reload")
    assert rc == 0, out
    (attr,) = r["blame"]["extract.recall"]["attributions"]
    assert attr["patches"] == [r["patch_id"]]  # the patch sits at the boundary...
    assert attr["delta"] == pytest.approx(0.0, abs=1e-9)  # ...but moved nothing
