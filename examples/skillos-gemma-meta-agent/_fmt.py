"""Pretty-print one agentvcs --json result as a readable line.

Reads the JSON object an agent would consume on stdin and prints a concise,
human-friendly summary, so the demo reads like a narrated agent session.
"""
import json
import sys

d = json.load(sys.stdin)

if not d.get("ok"):
    e = d["error"]
    print(f"  ✗ {e['code']}: {e['message']}")
    sys.exit(0)

cmd = d.get("command")


def s(oid):
    return oid[:10] if oid else "-"


def show_diff(diff):
    code = diff["code"]
    for p in code["added"]:
        print(f"      + {p}")
    for p in code["removed"]:
        print(f"      - {p}")
    for p in code["modified"]:
        print(f"      ~ {p}")
    if diff["goal"]:
        print(f"      goal: {diff['goal']['from']!r} -> {diff['goal']['to']!r}")
    if diff["models"]:
        print(f"      models: {diff['models']['from']} -> {diff['models']['to']}")
    if diff["trace"]:
        t = diff["trace"]
        print(f"      trace: {t['from']} -> {t['to']} ({t['delta']:+d})")
    if diff["state"]:
        print(f"      state: {diff['state']['from']} -> {diff['state']['to']}")
    if not any([code["added"], code["removed"], code["modified"],
                diff["goal"], diff["models"], diff["trace"], diff["state"]]):
        print("      (no changes)")


if cmd == "init":
    print(f"  ✓ initialized {d['repository']} (+ {d['manifest']}, {d['agents_md']})")
elif cmd == "commit":
    print(f"  ✓ commit {s(d['commit'])} [{d['state']}] on {d['branch']}: {d['message']}")
elif cmd == "diff":
    print(f"  diff {s(d['a'])}..{s(d['b'])}")
    show_diff(d["diff"])
elif cmd == "status":
    print(f"  status on {d['branch']} @ {s(d['head'])}")
    show_diff(d["diff"])
elif cmd == "rollback":
    print(f"  ↩ rolled back to {s(d['restored_to'])} (was {s(d['previous_head'])})")
    print(f"      goal now: {d['goal']!r}")
elif cmd == "freeze":
    print(f"  ❄ crystallized {s(d['commit'])} from {s(d['source'])}")
    print(f"      deterministic recipe: {d['recipe_path']}")
elif cmd == "log":
    for c in d["commits"]:
        print(f"  {s(c['commit'])} [{c['state']:>12}] {c['message']}")
elif cmd == "show":
    print(f"  commit {s(d['commit'])} [{d['state']}]: {d['message']}")
    print(f"      goal: {d['goal']!r}")
    for m in d["models"]:
        print(f"      model: {m['provider']}/{m['model']} params={m['params']}")
    print(f"      trace: {d['trace_messages']} messages")
elif cmd == "branch":
    if "branch" in d:
        print(f"  ✓ branch {d['branch']} @ {s(d['commit'])}")
    else:
        for b in d["branches"]:
            mark = "*" if b["name"] == d["current"] else " "
            print(f"  {mark} {b['name']} {s(b['commit'])}")
elif cmd == "checkout":
    print(f"  ✓ checked out {d['ref']} ({s(d['commit'])})")
else:
    print("  " + json.dumps({k: v for k, v in d.items() if k not in ("ok", "command")}))
