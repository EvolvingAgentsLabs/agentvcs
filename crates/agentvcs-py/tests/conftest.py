import json
import os
import subprocess
import sys

import pytest

import agentvcs as avcs

PASSING_SUITE = 'name: smoke\ncommand: "echo \'{\\"metrics\\": {\\"ok\\": 1}}\'"\nthresholds:\n  ok: {op: ">=", value: 1}\n'


def manifest(template="Extract {doc}", model="m-1", temperature=0.2, name="t"):
    return {
        "protocol": "agentvcs/0.1",
        "type": "harness_manifest",
        "name": name,
        "dimensions": {
            "x.prompt": {"kind": "prompt", "content": {"template": template, "variables": ["doc"], "system": "be brief"}},
            "x.model": {"kind": "model", "content": {"provider": "llama.cpp", "id": model}},
            "x.sampling": {"kind": "sampling", "content": {"temperature": temperature, "max_tokens": 64, "grammar": None, "seed": 7}},
        },
    }


def agentvcs_cli(store, *args, stdin=None):
    """The CLI as a separate process (python -m agentvcs), like a supervisor."""
    p = subprocess.run(
        [sys.executable, "-m", "agentvcs", "-C", str(store), "--json", *args],
        input=stdin, capture_output=True, text=True,
    )
    out = json.loads(p.stdout)
    return p.returncode, out


def supervise(store, run_id, to_manifest: dict, rationale="tighten prompt"):
    """propose -> gate -> apply from another process; returns the patch id."""
    to_path = os.path.join(str(store), f"to-{avcs.hash_json(to_manifest)[3:11]}.json")
    with open(to_path, "w") as f:
        json.dump(to_manifest, f)
    suite = os.path.join(str(store), "suite.yaml")
    with open(suite, "w") as f:
        f.write(PASSING_SUITE)
    code, st = agentvcs_cli(store, "log", run_id)
    active = None
    for e in st["entries"]:
        b = e["body"]
        active = b.get("to_manifest") or b.get("manifest_id") or active
    code, out = agentvcs_cli(store, "patch", "propose", run_id, "--from", active, "--to", to_path,
                             "--rationale", rationale, "--author", "agent:supervisor")
    assert out["ok"], out
    pid = out["patch_id"]
    code, out = agentvcs_cli(store, "gate", "run", pid, "--suite", suite)
    assert out["ok"] and out["gate_result"]["passed"], out
    code, out = agentvcs_cli(store, "patch", "apply", pid)
    assert out["ok"], out
    return pid


@pytest.fixture
def store(tmp_path):
    return tmp_path
