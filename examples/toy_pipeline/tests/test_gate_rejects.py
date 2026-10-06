"""The paired gate must be able to fail: a candidate equal to its from_manifest gains 0."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import pipeline  # noqa: E402


def _cli(cwd, *args):
    p = subprocess.run([sys.executable, "-m", "agentvcs", *args, "--json"], cwd=cwd,
                       capture_output=True, text=True)
    return json.loads(p.stdout)


def test_paired_gate_reports_zero_gain_for_an_unchanged_manifest(tmp_path):
    _cli(tmp_path, "init")
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps(pipeline.base_manifest()))
    mid = _cli(tmp_path, "snapshot", str(v1))["manifest_id"]
    store = tmp_path / ".agentvcs"
    mfile = store / "manifests" / (mid.split(":", 1)[1] + ".json")
    assert mfile.exists()
    env = {**os.environ, "AGENTVCS_FROM_MANIFEST": mid, "AGENTVCS_MANIFEST_FILE": str(mfile),
           "AGENTVCS_STORE": str(store)}
    out = subprocess.run([sys.executable, os.path.join(HERE, "gate_eval.py"), "--backend", "fake", "--paired"],
                         env=env, capture_output=True, text=True, check=True)
    m = json.loads(out.stdout)["metrics"]
    assert m["extract.recall.gain"] < 0.10      # the supervisor's threshold: this candidate is refused
    assert m["extract.recall.gain"] == 0.0
