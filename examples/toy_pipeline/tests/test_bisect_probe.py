"""bisect with a real probe (Gate F2's bisect half): on a run whose regression landed back to back with a
harmless patch, blame can only credit the pair; bisect re-executes each candidate from the run's checkpoint
on the same documents and names the regression. The control run, with the regressing edit removed, has
nothing to find — so the answer comes from the manifest, not from the probe or the documents."""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import regression  # noqa: E402

PROBE = f'"{sys.executable}" "{os.path.join(HERE, "probe.py")}"'


def cli(*args, cwd):
    p = subprocess.run([sys.executable, "-m", "agentvcs", *args, "--json"], cwd=cwd, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def test_blame_credits_the_pair_and_bisect_names_the_regression(tmp_path):
    r = regression.build(str(tmp_path))
    rc, blame = cli("blame", r["audit"], "--metric", "extract.recall", cwd=tmp_path)
    assert rc == 0, blame
    drops = [a for a in blame["attributions"] if a["delta"] is not None and a["delta"] < -0.1]
    assert len(drops) == 1 and drops[0]["patches"] == r["patches"][2:4]       # joint: the regression and its neighbour
    rc, b = cli("bisect", r["audit"], "--metric", "extract.recall", "--bad", "<0.9", "--exec", PROBE, cwd=tmp_path)
    assert rc == 0, b
    assert b["first_bad_patch"] == r["regression"], b
    assert b["checkpoint_ref"] == "doc:2" and b["from_step"] == 2
    assert len(b["probes"]) <= 4                                              # 5 candidates: 2 ends + ⌈log2 4⌉
    assert [p["bad"] for p in b["probes"] if p["patch_id"] in r["patches"][:2]] == [False] * len(
        [p for p in b["probes"] if p["patch_id"] in r["patches"][:2]])


def test_the_control_run_has_nothing_to_find(tmp_path):
    r = regression.build(str(tmp_path), regress=False)
    rc, b = cli("bisect", r["audit"], "--metric", "extract.recall", "--bad", "<0.9", "--exec", PROBE, cwd=tmp_path)
    assert rc == 0, b
    assert b["first_bad_patch"] is None and b["reason"] == "the last manifest is not bad"
    assert all(p["metric"] == 1.0 for p in b["probes"])
