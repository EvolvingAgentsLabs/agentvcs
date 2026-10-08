#!/usr/bin/env python3
"""Rebuild tests/fixture/lk — the minimal subset of a lora-kernel checkout the tests need.

    python make_fixture.py --lk ~/evolvingagents/lora-kernel [--out tests/fixture/lk]

It runs the importer and every imported gate against the real checkout through a
recording Reader, then writes only what was read: JSON files cut down to the keys
read, Python files reduced to the constants and argparse defaults read (plus matched
lines as comments), Markdown files reduced to the matched lines and quotes. The
prompt's text is NOT copied: the fixture's prompt is a placeholder, so its sha256
differs from the real one by design. Nothing is written inside the checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import history  # noqa: E402
import import_lk as ilk  # noqa: E402
from lkread import Reader  # noqa: E402

PLACEHOLDER = "fixture placeholder: the real prompt text stays in lora-kernel (memory/prompt.py)"


def setpath(d: dict, keys, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lk", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "tests", "fixture", "lk"))
    a = ap.parse_args(argv)
    r = Reader(a.lk)
    f = ilk.extract(r)
    for c in history.changes(f):
        history.read_change(r, c)

    files: dict[str, dict] = {}
    for e in r.log:
        files.setdefault(e["file"], {"json": {}, "const": [], "arg": [], "lines": []})
        x = files[e["file"]]
        k = e["kind"]
        if k == "json":
            setpath(x["json"], e["keys"], e["value"]) if e["keys"] else None
        elif k == "const":
            x["const"].append((e["name"], e["value"]))
        elif k == "prompt":
            x["const"].append((e["name"], PLACEHOLDER))
        elif k == "arg":
            x["arg"].append((e["flag"], e["value"]))
        elif k in ("regex", "quote"):
            x["lines"].append(e.get("match") or e.get("quote"))
    if os.path.isdir(a.out):
        shutil.rmtree(a.out)
    for rel, x in sorted(files.items()):
        p = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if rel.endswith(".json"):
            text = json.dumps(x["json"], indent=1, ensure_ascii=False) + "\n"
        elif rel.endswith(".py"):
            out = [f'"""Fixture: values extracted from lora-kernel {rel} by make_fixture.py."""']
            seen = set()
            for name, value in x["const"]:
                if name not in seen:
                    seen.add(name)
                    out.append(f"{name} = {value!r}")
            for flag, value in dict(x["arg"]).items():
                out.append(f"ap.add_argument({flag!r}, default={value!r})")
            out += [f"# {line}" for line in dict.fromkeys(x["lines"])]
            text = "\n".join(out) + "\n"
        else:
            out = [f"<!-- Fixture: lines extracted from lora-kernel {rel} by make_fixture.py -->"]
            out += list(dict.fromkeys(x["lines"]))
            text = "\n\n".join(out) + "\n"
        with open(p, "w") as fh:
            fh.write(text)
    print(f"wrote {len(files)} files under {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
