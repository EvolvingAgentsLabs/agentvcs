#!/usr/bin/env python3
"""A tiny, deterministic reconciler for `agentvcs merge --reconcile` — offline, no LLM.

agentvcs core never calls a model. When two branches diverge it writes a
*reconciliation bundle* to this process's stdin and reads back
`{goal, trace, notes, resolved_files?}` on stdout. This reference reconciler is
deliberately dumb-but-deterministic so the demo runs anywhere:

  * **resolved_files** — for every still-unresolved conflict it is handed the full
    base/ours/theirs text (`bundle["conflict_files"]`). For our markdown skills it
    synthesizes a clean, marker-free file by taking the **union of the policy
    bullets from both sides** (ours first, then any new ones from theirs). That is
    the whole point: the merged agent keeps *both* lines' learned rules.
  * **goal** — the union of both goals, or `target_goal` verbatim when the merge was
    directed with `--target-goal`.
  * **trace** — a short Consolidated Knowledge Trace summarizing what each side
    contributed (not the two raw traces concatenated).

In production you would swap this for a real brain — e.g.
`--reconcile "claude -p 'reconcile this agentvcs merge bundle'"` or the bundled
nanoLoop reconciler in ../nanoloop-reconcile/. The contract (stdin bundle → stdout
JSON) is identical; only the intelligence changes.
"""
from __future__ import annotations

import json
import sys


def _is_bullet(line: str) -> bool:
    return line.lstrip().startswith(("- ", "* "))


def merge_markdown(base: str, ours: str, theirs: str) -> str:
    """Union the bullet lines of two evolved markdown policies, preserving the
    non-bullet prose from `ours` (header, intro). ours' bullets come first; theirs'
    new bullets are appended. Deterministic and order-stable."""
    ours_lines = ours.splitlines()
    bullets, seen = [], set()
    for ln in ours_lines:
        if _is_bullet(ln):
            key = ln.strip()
            if key not in seen:
                seen.add(key)
                bullets.append(ln)
    for ln in theirs.splitlines():
        if _is_bullet(ln):
            key = ln.strip()
            if key not in seen:
                seen.add(key)
                bullets.append(ln)

    # rebuild: ours' lines, but replace its bullet block with the unioned bullets
    out, wrote_bullets = [], False
    for ln in ours_lines:
        if _is_bullet(ln):
            if not wrote_bullets:
                out.extend(bullets)
                wrote_bullets = True
            # skip ours' individual bullets — already emitted as the union block
        else:
            out.append(ln)
    if not wrote_bullets:          # ours had no bullets at all → append the union
        out.extend(bullets)
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    bundle = json.load(sys.stdin)
    ours, theirs = bundle.get("ours", {}), bundle.get("theirs", {})

    resolved = {}
    for cf in bundle.get("conflict_files", []):
        resolved[cf["path"]] = merge_markdown(
            cf.get("base", ""), cf.get("ours", ""), cf.get("theirs", ""))

    target = bundle.get("target_goal")
    og, tg = ours.get("goal", ""), theirs.get("goal", "")
    if target:
        goal = target
    elif og == tg:                      # both lines kept the same goal → keep it once
        goal = og
    else:                               # genuinely divergent goals → union
        goal = f"{og} + {tg}".strip(" +")

    trace = [
        {"role": "system",
         "content": "Reconciled two divergent RefundBot lines into one working memory."},
        {"role": "assistant",
         "content": f"From the run-time line (ours): {ours.get('goal','')}. "
                    "Kept its autonomously-added fraud rule + the fraud-screener sub-agent."},
        {"role": "assistant",
         "content": f"From the design-time line (theirs): {theirs.get('goal','')}. "
                    "Kept its refund-window rule + the evolved verifier. "
                    "Skill conflicts were merged as the union of both policies."},
    ]

    out = {"goal": goal, "trace": trace,
           "notes": f"unioned {len(resolved)} skill conflict(s); kept both sides' rules"}
    if resolved:
        out["resolved_files"] = resolved
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
