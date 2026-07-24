"""Knowledge + code reconciliation for `agentvcs merge --reconcile`.

When two agent branches diverge, agentvcs hands the *reasoning and the unresolved
code* — a bundle of {base, ours, theirs} goals + message traces + code diffs +
recorded metrics + conflicts — to an external process on stdin, expecting
``{goal, trace, notes, resolved_files?}`` back on stdout. That seam keeps
agentvcs's core free of any LLM dependency.

This module is nanoLoop's implementation of that seam. It does both halves of a
multidimensional merge in one shot:

  * **reasoning** — synthesizes a single, non-fragmented *Consolidated Knowledge
    Trace* (the merged working memory an agent resumes from) instead of two raw,
    contradictory chat logs concatenated together;
  * **code** — for every file the textual merge could not resolve, rewrites one
    clean, conflict-free file (no ``<<<<<<<`` markers), weighted by each side's
    recorded ``eval_score`` and steered by an optional ``target_goal``.

This is the single source of truth: ``nanoloop reconcile`` (the CLI) and the
``examples/nanoloop-reconcile/reconcile.py`` shim in the agentvcs repo both call
``reconcile_bundle`` here, so there is one prompt and one contract.

Exposed on the CLI as ``nanoloop reconcile [path/to/.env]`` (reads stdin, writes
stdout), so it drops straight into ``agentvcs merge <branch> --reconcile``.
"""
from __future__ import annotations

import json
import os
import urllib.request



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
(or pass {}) when there are none. The trace should be 2-5 messages: a system
summary of the reconciliation, then assistant notes capturing the retained
learning from each side."""


def _flatten(msgs):
    """Tolerate traces stored as a list-of-lists (e.g. a .jsonl line that is
    itself a JSON array) — normalize to a flat stream of message dicts."""
    for m in msgs or []:
        if isinstance(m, list):
            yield from _flatten(m)
        elif isinstance(m, dict):
            yield m


def _fmt_trace(msgs) -> str:
    out = []
    for m in _flatten(msgs):
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(str(x) for x in c)
        out.append(f"  [{m.get('role', '?')}] {c}")
    return "\n".join(out) or "  (none)"


def build_user_prompt(bundle: dict) -> str:
    b, o, t = bundle["base"], bundle["ours"], bundle["theirs"]
    target = bundle.get("target_goal")
    cfiles = bundle.get("conflict_files", [])
    return f"""TARGET GOAL (directed merge; null = "best of both"): {json.dumps(target)}

BASE goal: {b.get('goal', '')}
BASE trace:
{_fmt_trace(b.get('trace_messages'))}

OURS branch '{o.get('branch', '')}' goal: {o.get('goal', '')}
OURS metrics: {json.dumps(o.get('metrics', {}))}
OURS code diff: {json.dumps(o.get('code_diff', {}))}
OURS trace:
{_fmt_trace(o.get('trace_messages'))}

THEIRS branch '{t.get('branch', '')}' goal: {t.get('goal', '')}
THEIRS metrics: {json.dumps(t.get('metrics', {}))}
THEIRS code diff: {json.dumps(t.get('code_diff', {}))}
THEIRS trace:
{_fmt_trace(t.get('trace_messages'))}

AUTO-SELECTED (already resolved by eval score — do not revisit):
{json.dumps(bundle.get('autoselected', []))}

CONFLICT FILES (rewrite each into one clean file → resolved_files):
{json.dumps(cfiles)}

CONFLICTS: {json.dumps(bundle.get('conflicts', []))}

Reconcile into one Consolidated Knowledge Trace and resolve every conflict file.
Return the strict JSON."""



def _call_model(system: str, user: str) -> str:
    """Call an OpenAI-compatible chat endpoint using only the standard library.

    agentvcs core has zero runtime dependencies and this example keeps that
    property: no SDK, no LangChain. Point it anywhere that speaks the OpenAI
    chat schema -- OpenRouter, an ollama server, vLLM -- via RECONCILE_BASE_URL.

        RECONCILE_BASE_URL   default https://openrouter.ai/api/v1
        RECONCILE_API_KEY    required unless the server ignores it
        RECONCILE_MODEL      default anthropic/claude-sonnet-4
    """
    base = os.environ.get("RECONCILE_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    key = os.environ.get("RECONCILE_API_KEY", os.environ.get("OPENROUTER_API_KEY", "local"))
    model = os.environ.get("RECONCILE_MODEL", "anthropic/claude-sonnet-4")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 8000,
    }).encode()

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())

    msg = (body.get("choices") or [{}])[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    if not content:
        # Reasoning models write their chain to a separate field and only then
        # fill content. An empty content here means the token budget was spent
        # thinking -- fail loudly rather than returning an empty reconciliation.
        hint = " (model reasoned but never answered; raise max_tokens)" if msg.get("reasoning") else ""
        raise RuntimeError(f"reconciler model returned empty content{hint}")
    return content


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, tolerating code fences/prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1])


def reconcile_bundle(bundle: dict) -> dict:
    """Synthesize a Consolidated Knowledge Trace and resolve code conflicts from a
    merge bundle.

    Returns ``{goal, trace, notes}`` plus ``resolved_files`` when the bundle
    carried conflict files — exactly the shape ``agentvcs merge --reconcile``
    validates and writes into the merge commit.
    """
    text = _call_model(SYSTEM, build_user_prompt(bundle))
    parsed = _extract_json(text)
    out = {
        "goal": parsed["goal"],
        "trace": parsed["trace"],
        "notes": parsed.get("notes", "reconciled"),
    }
    # resolved_files is optional: include it only when the model returned a
    # non-empty mapping (agentvcs validates {goal:str, trace:list}; files are extra).
    rf = parsed.get("resolved_files")
    if isinstance(rf, dict) and rf:
        out["resolved_files"] = rf
    return out
