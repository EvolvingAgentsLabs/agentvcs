"""Run the toy pipeline end to end and ask blame who moved the metric.

    python run_pipeline.py --backend fake                       # offline, ~5 s
    python run_pipeline.py --backend openai --base-url http://127.0.0.1:8080/v1 \
        --model qwen2.5-1.5b-instruct --docs 400 --patch-after 100   # RUN_REAL.md

Three processes: this orchestrator, the harness (agents), the supervisor (patches
through the CLI). Afterwards: export audit, verify, and blame on
``extract.recall``. Exit code 0 iff blame attributes the change to the patch the
supervisor applied (with ``--no-reload``: iff it attributes *no* change to it).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pipeline  # noqa: E402

METRICS = ("extract.recall", "check.ok", "summary.mentions_cap")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["fake", "openai"], default="fake")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None, help="model id for --backend openai")
    ap.add_argument("--docs", type=int, default=30)
    ap.add_argument("--patch-after", type=int, default=4, help="extractions the supervisor observes first")
    ap.add_argument("--step-delay", type=float, default=None, help="default: 0.03 fake, 0 openai")
    ap.add_argument("--workdir", default=os.path.join(HERE, "workdir"))
    ap.add_argument("--no-reload", action="store_true", help="control arm: harness ignores patches")
    ap.add_argument("--cli", default=os.environ.get("AGENTVCS_CLI", ""),
                    help="agentvcs CLI command (default: python -m agentvcs)")
    ap.add_argument("--timeout", type=float, default=3600)
    a = ap.parse_args(argv)
    if a.backend == "openai" and not (a.base_url and a.model):
        ap.error("--backend openai needs --base-url and --model")
    delay = a.step_delay if a.step_delay is not None else (0.03 if a.backend == "fake" else 0.0)
    cli_cmd = shlex.split(a.cli) if a.cli else [sys.executable, "-m", "agentvcs"]
    w = os.path.abspath(a.workdir)

    def cli(*args):
        p = subprocess.run([*cli_cmd, "-C", w, "--json", *args], capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    shutil.rmtree(w, ignore_errors=True)
    os.makedirs(w)
    cli("init")
    v1 = pipeline.base_manifest(*(("openai-compat", a.model) if a.backend == "openai" else ("fake", "toy-fake")))
    v1_path = os.path.join(w, "manifest.v1.json")
    with open(v1_path, "w") as f:
        json.dump(v1, f, indent=2)
    _, snap = cli("snapshot", v1_path)
    m1 = snap["manifest_id"]
    print(f"[run] workdir {w}\n[run] manifest v1 {m1}", flush=True)

    backend = ["--backend", a.backend] + (["--base-url", a.base_url] if a.base_url else [])
    harness = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "harness.py"), "--store", w, "--manifest", m1,
         "--run-id", "toy", "--docs", str(a.docs), "--step-delay", str(delay),
         "--status-file", os.path.join(w, "harness.status.json"), *backend]
        + (["--no-reload"] if a.no_reload else []))
    supervisor = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "supervisor.py"), "--store", w, "--run-id", "toy",
         "--manifest-file", v1_path, "--after-docs", str(a.patch_after), "--timeout", str(a.timeout),
         *backend] + (["--cli", a.cli] if a.cli else []),
        stdout=subprocess.PIPE, text=True)
    sup_lines = []
    for line in supervisor.stdout:  # stream: the position of a run is always visible
        sys.stdout.write(line)
        sys.stdout.flush()
        sup_lines.append(line)
    sup_rc = supervisor.wait()
    h_rc = harness.wait(timeout=a.timeout)
    if sup_rc != 0 or h_rc != 0:
        print(f"[run] FAILED: supervisor exit {sup_rc}, harness exit {h_rc}", flush=True)
        return 2
    sup = json.loads(sup_lines[-1])
    pid = sup["patch_id"]

    _, exp = cli("export", "audit", "toy", "-o", "toy.audit.json", "--yes")
    _, ver = cli("verify", "toy.audit.json")
    blames = {m: cli("blame", "toy.audit.json", "--metric", m)[1] for m in METRICS}
    with open(os.path.join(w, "harness.status.json")) as f:
        status = json.load(f)

    b = blames["extract.recall"]
    attr = b.get("attributions", [])
    ok_struct = ver.get("valid") is True and len(b.get("segments", [])) == 2 and len(attr) == 1 \
        and attr[0]["patches"] == [pid]
    delta = attr[0]["delta"] if attr else None
    if a.no_reload:
        verdict = ok_struct and delta is not None and abs(delta) < 1e-9
    else:
        verdict = ok_struct and delta is not None and delta > 0
    result = {
        "ok": bool(verdict),
        "backend": a.backend,
        "no_reload": a.no_reload,
        "patch_id": pid,
        "gate": sup["gate_result"]["metrics"],
        "verify": ver.get("valid"),
        "entries": exp.get("entries"),
        "harness": status,
        "blame": {m: {"segments": [{k: s[k] for k in ("from_step", "to_step", "n", "mean")}
                                   for s in v.get("segments", [])],
                      "attributions": v.get("attributions", [])} for m, v in blames.items()},
    }
    result["applied_at_step"] = status["reloads"][0]["at_step"] if status["reloads"] else None
    with open(os.path.join(w, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    seg = b.get("segments", [])
    print("[run] blame extract.recall: " + " | ".join(
        f"steps {s['from_step']}-{s['to_step']} mean {s['mean']:.3f} (n={s['n']})" for s in seg), flush=True)
    if attr:
        print(f"[run] attribution: delta {delta:+.3f} -> patches {[p[:15] + '…' for p in attr[0]['patches']]}"
              f" (supervisor's patch {pid[:15]}…)", flush=True)
    print(f"[run] {'OK' if verdict else 'UNEXPECTED'}: result in {os.path.join(w, 'result.json')}", flush=True)
    return 0 if verdict else 1


if __name__ == "__main__":
    t = time.time()
    rc = main()
    print(f"[run] {time.time() - t:.1f}s", flush=True)
    sys.exit(rc)
