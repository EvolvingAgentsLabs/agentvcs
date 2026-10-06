#!/usr/bin/env python3
"""Run the agentvcs conformance suite against any CLI.

    python conformance/run.py --cli "agentvcs"            # whatever is on PATH
    python conformance/run.py --cli "./target/release/agentvcs" --group verify

The runner only uses argv, the exit code and stdout JSON (ADR-0003). Each case
runs in a fresh temporary directory: `<cli> init --json`, then the case's argv
with `--json` appended. One result line per case is printed as it finishes, and
appended to --out if given, so a run's position is always visible.

Matching: every key in the expected JSON must be present and equal in the
actual output (extra keys are allowed); lists must have the same length and
match element-wise; numbers match within 1e-9. `first_violation` is compared
against `violations[0]` only (spec/LEDGER.md). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def match(exp, act, path="$"):
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return f"{path}: expected object, got {type(act).__name__}"
        for k, v in exp.items():
            if k not in act:
                return f"{path}.{k}: missing"
            err = match(v, act[k], f"{path}.{k}")
            if err:
                return err
        return None
    if isinstance(exp, list):
        if not isinstance(act, list) or len(act) != len(exp):
            return f"{path}: expected list of {len(exp)}, got {act if not isinstance(act, list) else len(act)}"
        for i, (e, a) in enumerate(zip(exp, act)):
            err = match(e, a, f"{path}[{i}]")
            if err:
                return err
        return None
    if isinstance(exp, bool) or exp is None or isinstance(act, bool):
        return None if exp is act or exp == act and type(exp) is type(act) else f"{path}: expected {exp!r}, got {act!r}"
    if isinstance(exp, (int, float)) and isinstance(act, (int, float)):
        return None if abs(exp - act) <= 1e-9 else f"{path}: expected {exp!r}, got {act!r}"
    return None if exp == act else f"{path}: expected {exp!r}, got {act!r}"


def run_case(cli: list[str], case_dir: Path, timeout: float) -> dict:
    spec = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    res = {"id": spec["id"], "group": spec["group"], "pass": False}
    with tempfile.TemporaryDirectory(prefix="avcs-conf-") as tmp:
        for f in case_dir.iterdir():
            if f.name != "case.json":
                shutil.copy(f, tmp)
        try:
            subprocess.run(cli + ["init", "--json"], cwd=tmp, capture_output=True, timeout=timeout)
            p = subprocess.run(cli + spec["argv"] + ["--json"], cwd=tmp, capture_output=True, timeout=timeout)
        except FileNotFoundError as ex:
            res["reason"] = f"cli not found: {ex}"
            return res
        except subprocess.TimeoutExpired:
            res["reason"] = f"timeout after {timeout}s"
            return res
    exp = spec["expect"]
    if p.returncode != exp["exit"]:
        res["reason"] = f"exit {p.returncode}, expected {exp['exit']}"
        res["stderr"] = p.stderr.decode(errors="replace")[-300:]
        return res
    try:
        out = json.loads(p.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        res["reason"] = "stdout is not one JSON object"
        res["stdout"] = p.stdout.decode(errors="replace")[:300]
        return res
    err = match(exp["json"], out)
    if not err and "first_violation" in exp:
        vs = out.get("violations") or []
        err = "no violations reported" if not vs else match(exp["first_violation"], vs[0], "$.violations[0]")
    if err:
        res["reason"] = err
        return res
    res["pass"] = True
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cli", required=True, help="command line of the implementation, e.g. 'agentvcs'")
    ap.add_argument("--cases", default=str(HERE / "cases"))
    ap.add_argument("--group", action="append", help="only these groups (repeatable)")
    ap.add_argument("--out", help="append one JSON line per case to this file")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args(argv)
    cli = shlex.split(a.cli)
    dirs = sorted(d for d in Path(a.cases).iterdir() if (d / "case.json").is_file())
    if a.group:
        dirs = [d for d in dirs if json.loads((d / "case.json").read_text())["group"] in a.group]
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    by: dict[str, list[int]] = {}
    for i, d in enumerate(dirs, 1):
        r = run_case(cli, d, a.timeout)
        g = by.setdefault(r["group"], [0, 0])
        g[0] += r["pass"]
        g[1] += 1
        line = json.dumps(r, ensure_ascii=False)
        print(f"[{i}/{len(dirs)}] {'PASS' if r['pass'] else 'FAIL'} {r['id']}" + ("" if r["pass"] else f" — {r['reason']}"),
              flush=True)
        if out:
            out.write(line + "\n")
            out.flush()
    total = sum(v[0] for v in by.values())
    summary = {"passed": total, "total": len(dirs), "by_group": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}}
    print(json.dumps(summary), flush=True)
    return 0 if total == len(dirs) else 1


if __name__ == "__main__":
    sys.exit(main())
