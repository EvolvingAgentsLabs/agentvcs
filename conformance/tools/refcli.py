#!/usr/bin/env python3
"""Positive control for run.py: the conformance commands, backed by ref.py.

It passes by construction on values (gen.py used the same functions), so a
pass here proves only that the runner's plumbing — argv, exit codes, JSON
matching — works. It is not an implementation of agentvcs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ref  # noqa: E402

SLUG = __import__("re").compile(r"^[a-z0-9][a-z0-9_.\-/]*$")
REQ = {"prompt": ("template",), "model": ("provider", "id"), "tool": ("name", "signature", "code_hash"),
       "adapter": ("adapter_id", "weights_hash")}


def out(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    return code


def fail(code, exit_):
    return out({"ok": False, "error": {"code": code, "message": code}}, exit_)


def load(path):
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
        ref.jcs(v)
        return v, None
    except ref.CanonicalError:
        return None, "E_CANONICAL"
    except ValueError:
        return None, "E_SCHEMA"


def manifest(m):
    if m.get("protocol") != ref.PROTOCOL:
        raise ValueError("E_PROTOCOL_VERSION")
    for name, d in m.get("dimensions", {}).items():
        if d.get("kind") not in ref.KINDS:
            raise ValueError("E_UNKNOWN_KIND")
        if not SLUG.match(name) or any(k not in d["content"] for k in REQ.get(d["kind"], ())):
            raise ValueError("E_SCHEMA")
    return ref.normalize_manifest(m)


def bisect(args):
    """Runs the probe exactly as the contract says (spec/cli/COMMANDS.md): `sh -c <exec>` in the cwd, the
    candidate in AGENTVCS_* variables, stdout one JSON value — a number, or an object holding the metric
    (top level or under `metrics`)."""
    import os
    import subprocess
    import tempfile

    def opt(name):
        return args[args.index(name) + 1]
    b, err = load(args[1])
    if err:
        return fail(err, 3)
    bad = opt("--bad")
    op = next(o for o in ("<=", ">=", "==", "!=", "<", ">") if bad.startswith(o))
    metric, cmd = opt("--metric"), opt("--exec")
    plan = ref.bisect_plan(b) or {"from_step": 0, "checkpoint_ref": None}
    scratch = tempfile.mkdtemp(prefix="refcli-bisect-")

    def probe(mid):
        f = Path(scratch) / (mid.split(":", 1)[1] + ".json")
        f.write_text(json.dumps(b["manifests"][mid]), encoding="utf-8")
        env = {**os.environ, "AGENTVCS_RUN": b["run_id"], "AGENTVCS_MANIFEST": mid, "AGENTVCS_MANIFEST_FILE": str(f),
               "AGENTVCS_FROM_STEP": str(plan["from_step"]), "AGENTVCS_CHECKPOINT_REF": plan["checkpoint_ref"] or "",
               "AGENTVCS_METRIC": metric, "AGENTVCS_STORE": str(Path(".agentvcs").resolve())}
        p = subprocess.run(["sh", "-c", cmd], env=env, capture_output=True, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise ValueError("E_GATE_COMMAND")
        try:
            v = json.loads(p.stdout)
        except ValueError:
            raise ValueError("E_GATE_COMMAND")
        if isinstance(v, dict):
            v = (v["metrics"] if isinstance(v.get("metrics"), dict) else v).get(metric)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("E_GATE_COMMAND")
        return float(v)
    r = ref.bisect(b, op, float(bad[len(op):]), probe)
    return out(r, 0 if r["ok"] else {"E_NOT_FOUND": 4}.get(r["error"]["code"], 3))


def main(argv):
    args = [a for a in argv if a != "--json"]
    cmd = args[0] if args else ""
    if cmd == "init":
        return out({"ok": True, "store": ".agentvcs"}, 0)
    if cmd == "hash":
        canonical = "--canonical" in args
        path = [a for a in args[1:] if a != "--canonical"][0]
        if not canonical:
            return out({"ok": True, "hash": ref.b3_bytes(Path(path).read_bytes())}, 0)
        v, err = load(path)
        if err:
            return fail(err, 3)
        c = ref.jcs(v)
        return out({"ok": True, "hash": ref.b3_bytes(c.encode()), "canonical": c}, 0)
    if cmd == "snapshot":
        v, err = load(args[1])
        if err:
            return fail(err, 3)
        try:
            n = manifest(v)
        except ValueError as ex:
            return fail(str(ex), 3)
        return out({"ok": True, "manifest_id": n["manifest_id"],
                    "dimensions": {k: d["content_hash"] for k, d in n["dimensions"].items()}}, 0)
    if cmd == "diff":
        a, _ = load(args[1])
        b, _ = load(args[2])
        return out({"ok": True, **ref.diff(a, b)}, 0)
    if cmd == "verify":
        b, err = load(args[1])
        if err:
            return fail(err, 3)
        r = ref.verify(b)
        return out(r, 0 if r["valid"] else 1)
    if cmd == "blame":
        b, err = load(args[1])
        r = ref.blame(b, args[args.index("--metric") + 1])
        return out(r, 0 if r["ok"] else 3)
    if cmd == "bisect":
        return bisect(args)
    if cmd == "merge":
        def opt(name):
            return args[args.index(name) + 1] if name in args else None
        base, ours, theirs = (load(opt(n))[0] for n in ("--base", "--ours", "--theirs"))
        if args[1] == "prepare":
            ob = load(opt("--ours-run"))[0] if opt("--ours-run") else None
            tb = load(opt("--theirs-run"))[0] if opt("--theirs-run") else None
            metrics = [args[i + 1] for i, a in enumerate(args) if a == "--metric"]
            return out(ref.merge_prepare(base, ours, theirs, ob, tb, metrics=metrics), 0)
        if args[1] == "commit":
            code, o = ref.merge_commit(base, ours, theirs, load(opt("--resolution"))[0])
            return out(o, code)
    return fail("E_USAGE", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
