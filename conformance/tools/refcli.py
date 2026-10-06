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
    return fail("E_USAGE", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
