"""The supervisor: a separate process that watches the run's ledger through the
agentvcs CLI, diagnoses the extractor, and proposes -> gates -> applies a patch.
It never talks to the harness; the only channel between them is the ledger."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class Cli:
    def __init__(self, cmd: str, store: str):
        self.cmd = shlex.split(cmd) if cmd else [sys.executable, "-m", "agentvcs"]
        self.store = store

    def __call__(self, *args: str) -> tuple[int, dict]:
        p = subprocess.run([*self.cmd, "-C", self.store, "--json", *args], capture_output=True, text=True)
        try:
            return p.returncode, json.loads(p.stdout)
        except json.JSONDecodeError:
            raise SystemExit(f"[supervisor] CLI printed no JSON: {p.stdout!r} {p.stderr!r}")


def active_manifest(entries: list) -> str:
    active = None
    for e in entries:
        b = e["body"]
        if e["kind"] == "run_start":
            active = b["manifest_id"]
        elif e["kind"] == "patch":
            active = b["to_manifest"]
    return active


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--run-id", default="toy")
    ap.add_argument("--manifest-file", required=True, help="the run's v1 manifest (authoring form)")
    ap.add_argument("--after-docs", type=int, default=4, help="extractor steps to observe first")
    ap.add_argument("--backend", choices=["fake", "openai"], default="fake")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--cli", default=os.environ.get("AGENTVCS_CLI", ""))
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args(argv)
    cli = Cli(a.cli, a.store)
    deadline = time.time() + a.timeout

    # 1. watch
    while True:
        if time.time() > deadline:
            raise SystemExit("[supervisor] timed out waiting for evidence")
        code, out = cli("log", a.run_id)
        if out.get("ok"):
            entries = out["entries"]
            if any(e["kind"] == "run_end" for e in entries):
                raise SystemExit("[supervisor] run ended before a patch could be applied")
            ex = [e["body"] for e in entries if e["kind"] == "step" and e["body"]["agent_id"] == "extractor"]
            if len(ex) >= a.after_docs:
                break
        time.sleep(0.05)
    checks = [e["body"] for e in entries if e["kind"] == "step" and e["body"]["agent_id"] == "checker"]
    evidence = [b["step_index"] for b in checks if b.get("metrics", {}).get("check.ok") == 0][:8]
    mean = sum(b["metrics"]["extract.recall"] for b in ex) / len(ex)
    print(f"[supervisor] {len(ex)} extractions, mean recall {mean:.3f}; checker flagged steps {evidence}", flush=True)

    # 2. propose
    with open(a.manifest_file) as f:
        v2 = pipeline.add_cap_field(json.load(f))
    v2_path = os.path.join(a.store, "manifest.v2.json")
    with open(v2_path, "w") as f:
        json.dump(v2, f, indent=2)
    code, out = cli("patch", "propose", a.run_id, "--from", active_manifest(entries), "--to", v2_path,
                    "--rationale", "extraction prompt never asks for the cap amount",
                    "--evidence", ",".join(map(str, evidence)), "--author", "agent:supervisor-v0")
    if not out.get("ok"):
        raise SystemExit(f"[supervisor] propose failed: {out}")
    pid = out["patch_id"]
    print(f"[supervisor] proposed {pid[:15]}…: {[c.get('dimension') for c in out['semantic_diff']]}", flush=True)

    # 3. gate (held-out documents, same backend)
    # Relative gate (2026-10-06, after the first real run): the candidate must beat the
    # active manifest by 0.10 recall on the same held-out documents. An absolute 0.9 over
    # 12 docs scored in thirds flipped on one field's run-to-run noise (RUN_REAL.md).
    gate_cmd = [sys.executable, os.path.join(HERE, "gate_eval.py"), "--backend", a.backend, "--paired"]
    if a.base_url:
        gate_cmd += ["--base-url", a.base_url]
    suite = os.path.join(a.store, "suite.yaml")
    with open(suite, "w") as f:
        f.write("name: toy-holdout\n")
        f.write(f"command: {json.dumps(shlex.join(gate_cmd))}\n")
        f.write('thresholds:\n  extract.recall.gain: {op: ">=", value: 0.1}\n')
    code, out = cli("gate", "run", pid, "--suite", suite)
    if not out.get("ok"):
        raise SystemExit(f"[supervisor] gate could not run: {out}")
    g = out["gate_result"]
    print(f"[supervisor] gate {g['suite']}: {g['metrics']} passed={g['passed']}", flush=True)
    if not g["passed"]:
        print(json.dumps({"patch_id": pid, "applied": False, "gate_result": g}))
        return 1

    # 4. apply (the harness may append concurrently: retry a stale writer)
    for _ in range(50):
        code, out = cli("patch", "apply", pid)
        if out.get("ok") or out.get("error", {}).get("code") != "E_STALE_STATE":
            break
        time.sleep(0.01)
    if not out.get("ok"):
        raise SystemExit(f"[supervisor] apply failed: {out}")
    print(f"[supervisor] applied {pid[:15]}… at seq {out['seq']}", flush=True)
    print(json.dumps({"patch_id": pid, "applied": True, "seq": out["seq"], "gate_result": g}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
