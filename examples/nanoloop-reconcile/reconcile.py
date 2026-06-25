#!/usr/bin/env python
"""nanoLoop-powered reconciliation brain for `agentvcs merge --reconcile`.

agentvcs core never calls an LLM. When two branches diverge, `merge` writes a
*reconciliation bundle* (base/ours/theirs goals + traces + code diffs + conflicts)
to this process's stdin and reads back `{goal, trace, notes}` on stdout. That seam
is identical in spirit to `replay --exec`.

This script is the "smart" half: it uses **nanoLoop's own model factory**
(`nanoloop.model.make_model`, OpenRouter via HARNESS_MODEL) to synthesize a
single, non-fragmented *Consolidated Knowledge Trace* — the merged working memory
an agent should resume from after the merge, instead of two raw, contradictory
chat logs concatenated together.

Run it with nanoLoop's venv python so its deps + .env are in scope:
    agentvcs merge <branch> --reconcile \
      "/path/nanoLoop/.venv/bin/python /path/reconcile.py /path/nanoLoop/.env"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv


SYSTEM = """You reconcile two divergent agent branches into ONE working memory
AND resolve their code conflicts.

You are given a merge bundle: a common-ancestor (base) goal+trace, and two
branches (ours/theirs) that evolved from it — each with its own goal, message
trace (the agent's reasoning), code diff, and recorded metrics (eval_score,
eval_ok, cost_usd). The branches may have explored different, even contradictory,
approaches. The bundle may also carry:
  * target_goal — if non-null, the merge is DIRECTED: keep only what serves this
    objective and DISCARD learnings/optimizations that fight it (e.g. drop a
    cost-cutting branch's lessons if the target prioritizes quality at any cost).
  * conflict_files — files the textual merge could not resolve, each with full
    base/ours/theirs text. You MUST rewrite each into one clean, conflict-free
    file (no <<<<<<< markers), combining the best of both, weighted by the
    metrics (favor the side with the higher verified eval_score).
  * autoselected — conflicts already resolved by eval score; do not revisit them.

Do NOT concatenate the two traces. Synthesize. Produce a single Consolidated
Knowledge Trace that an agent resuming on the merged branch can read as coherent
working memory: what each branch tried, what it learned, which decision won and
why, and what dead-ends to avoid re-exploring.

Return STRICT JSON, nothing else:
{
  "goal": "<the merged goal, one line — equal to target_goal if one was given>",
  "trace": [ {"role": "system"|"assistant", "content": "<one synthesized step>"}, ... ],
  "resolved_files": { "<path>": "<full final file content, no conflict markers>" },
  "notes": "<one-line summary of how you reconciled>"
}
Include resolved_files ONLY for paths present in conflict_files; omit the key
(or pass {}) when there are none. The trace should be 2-5 messages."""


def build_user_prompt(bundle: dict) -> str:
    def _flatten(msgs):
        # tolerate traces stored as a list-of-lists (e.g. a .jsonl line that is
        # itself a JSON array) — normalize to a flat list of message dicts.
        for m in msgs or []:
            if isinstance(m, list):
                yield from _flatten(m)
            elif isinstance(m, dict):
                yield m

    def fmt_trace(msgs):
        out = []
        for m in _flatten(msgs):
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(str(x) for x in c)
            out.append(f"  [{m.get('role','?')}] {c}")
        return "\n".join(out) or "  (none)"

    b, o, t = bundle["base"], bundle["ours"], bundle["theirs"]
    target = bundle.get("target_goal")
    cfiles = bundle.get("conflict_files", [])
    return f"""TARGET GOAL (directed merge; null = "best of both"): {json.dumps(target)}

BASE goal: {b.get('goal','')}
BASE trace:
{fmt_trace(b.get('trace_messages'))}

OURS branch '{o.get('branch','')}' goal: {o.get('goal','')}
OURS metrics: {json.dumps(o.get('metrics', {}))}
OURS code diff: {json.dumps(o.get('code_diff', {}))}
OURS trace:
{fmt_trace(o.get('trace_messages'))}

THEIRS branch '{t.get('branch','')}' goal: {t.get('goal','')}
THEIRS metrics: {json.dumps(t.get('metrics', {}))}
THEIRS code diff: {json.dumps(t.get('code_diff', {}))}
THEIRS trace:
{fmt_trace(t.get('trace_messages'))}

AUTO-SELECTED (already resolved by eval score — do not revisit):
{json.dumps(bundle.get('autoselected', []))}

CONFLICT FILES (rewrite each into one clean file → resolved_files):
{json.dumps(cfiles)}

CONFLICTS: {json.dumps(bundle.get('conflicts', []))}

Reconcile into one Consolidated Knowledge Trace and resolve every conflict file.
Return the strict JSON."""


def main() -> int:
    # load nanoLoop's .env (OPENROUTER_API_KEY, HARNESS_MODEL) if a path is given
    if len(sys.argv) > 1:
        load_dotenv(Path(sys.argv[1]))
    else:
        load_dotenv()

    bundle = json.load(sys.stdin)

    from nanoloop.model import make_model  # nanoLoop's OpenRouter model factory

    model = make_model(temperature=0.0)
    resp = model.invoke([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(bundle)},
    ])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)

    # tolerate models that wrap JSON in prose / code fences
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    parsed = json.loads(text[start:end + 1])

    # agentvcs validates {goal:str, trace:list}; resolved_files is optional.
    out = {
        "goal": parsed["goal"],
        "trace": parsed["trace"],
        "notes": parsed.get("notes", "reconciled by nanoLoop"),
    }
    rf = parsed.get("resolved_files")
    if isinstance(rf, dict) and rf:
        out["resolved_files"] = rf
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
