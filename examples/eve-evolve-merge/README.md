# agentvcs × Vercel eve — merging a self-evolving agent with its design-time release

This is the **core agentvcs scenario**, told end-to-end on a [Vercel **eve**](https://vercel.com/eve)
agent: an agent that **rewrites its own skills and sub-agents at run-time**, a team
that **evolves the same files in git**, and the **intelligent merge** that fuses both
without losing either.

```bash
bash examples/eve-evolve-merge/demo.sh      # offline, deterministic, no Vercel account, no LLM
```

## Why eve fits

eve builds a durable agent out of ordinary files — `instructions.md`, `skills/`,
`subagents/`, `tools/`, `hooks/`. That is exactly what agentvcs versions, so the two
line up dimension-for-dimension:

| agentvcs dimension | eve file(s) in this demo |
| --- | --- |
| `code` | `agent/skills/refund-policy.md`, `agent/subagents/*.md` |
| `swarm` | the sub-agent topology, declared in `agent.json` → `"swarm"` |
| `goal` | `agent.json` → `"goal"` (+ `agent/instructions.md`) |
| `trace` | the eve Workflow-SDK run, captured by `agent/hooks/agentvcs.ts` → `.eve/agentvcs/trace.jsonl`, read by the `vercel-eve` provider |

## The agent: RefundBot

A tiny eve agent defined as markdown — [`agent/instructions.md`](agent/instructions.md) —
with **one skill** ([`refund-policy.md`](agent/skills/refund-policy.md)) and **one
sub-agent** ([`refund-verifier.md`](agent/subagents/refund-verifier.md)). Its
instructions explicitly grant it the right to **evolve itself at run-time**: add a
rule to a skill, or spawn / edit a sub-agent, whenever a task needs a capability it
lacks.

## Two lines diverge from the same base

Both start from the base commit and evolve **the same skill and the sub-agents**,
slightly differently:

**① Run-time line (`runtime`) — the live agent evolves itself.**
Handed *"suspicious refunds are getting through — handle fraud,"* and having no fraud
capability, RefundBot autonomously:
- **edits its own skill** — appends a *fraud* rule to `refund-policy.md`;
- **spawns a new sub-agent** — writes `agent/subagents/fraud-screener.md` and
  registers it in its `swarm`.

The eve hook captures the agent's reasoning into the trace, so this run-time
evolution is a **versioned fact**.

**② Design-time line (`main`) — the team edits the files in git (e.g. with Claude Code).**
Independently, a developer:
- **edits the same skill differently** — adds a *30-day refund-window* rule to
  `refund-policy.md`;
- **updates the existing sub-agent** — adds a high-value approval cap to
  `refund-verifier.md`.

## The intelligent merge

```bash
agentvcs checkout runtime
agentvcs merge main --reconcile "<your agent>"
```

agentvcs reconciles **every dimension at once**:

| dimension | what happens here |
| --- | --- |
| **skill** (`refund-policy.md`) | both lines edited it → a true **conflict**. The `--reconcile` agent is handed the full base/ours/theirs text and returns `resolved_files` — a clean file with **both** rules (fraud **and** window). No `<<<<<<<` markers. |
| **swarm** | run-time **created** `fraud-screener`; design-time **evolved** `refund-verifier`. Merged **node-by-node** → the final agent has **both**. |
| **goal + trace** | the two divergent reasoning traces are reconciled into one Consolidated Knowledge Trace instead of being concatenated. |

The result is one merge commit whose RefundBot screens fraud (run-time) **and**
enforces the refund window + approval cap (design-time) — the best of both lines,
nothing lost.

## The reconciler

[`reconcile.py`](reconcile.py) is a deliberately tiny, **deterministic, offline**
reconciler (no LLM) so the demo runs anywhere: for each conflicting skill it returns
the **union of the policy bullets** from both sides. The `--reconcile` contract is
just *stdin bundle → stdout `{goal, trace, notes, resolved_files?}`*, so in production
you swap in a real brain without changing anything else:

```bash
# an LLM reconciler
agentvcs merge main --reconcile "claude -p 'reconcile this agentvcs merge bundle'"

# or the bundled nanoLoop reconciler (../nanoloop-reconcile/reconcile.py), which
# routes through OpenRouter — point HARNESS_MODEL at any model, e.g. Gemini:
OPENROUTER_API_KEY=… HARNESS_MODEL=google/gemini-3.5-flash \
AGENTVCS_RECONCILE="/path/to/nanoLoop/.venv/bin/python ../nanoloop-reconcile/reconcile.py" \
  bash demo.sh

# or Gemini's SDK directly (same nanoLoop prompt, GEMINI_API_KEY instead of OpenRouter):
GEMINI_API_KEY=… AGENTVCS_RECONCILE="python3.12 gemini_reconcile.py" bash demo.sh
```

> **Validated** with `google/gemini-3.5-flash` via nanoLoop + OpenRouter: Gemini read
> both branches' traces, synthesized the union skill (no markers), and wrote a
> Consolidated Knowledge Trace — `status: merged`, `0` conflicts, the swarm carrying
> both sub-agents.

### Variations to try

```bash
# Direct the merge toward an objective — keep only what serves it:
agentvcs merge main --target-goal "prioritize fraud safety even at higher cost"

# If you record evals (agentvcs eval), a clearly better-scoring side auto-resolves
# conflicting hunks per-hunk BEFORE the reconciler is even asked.
```

## How it maps to a real eve project

The demo replays a captured trace so it runs with no Vercel account. In a live eve
app the only difference is where the trace comes from: drop
[`agent/hooks/agentvcs.ts`](../eve/agent/hooks/agentvcs.ts) into your agent, run it,
and the hook appends real events to `.eve/agentvcs/trace.jsonl`. `.eve/` is in
`.agentvcsignore` so the live log is captured as the **trace** dimension, never
tracked as **code**. See [`examples/eve/`](../eve/) for the trace-capture and
time-travel-debugging side of the same integration.
