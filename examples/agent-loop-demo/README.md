# The "fire test": an agent driving agentvcs end-to-end

This is the product-market-fit demo. It simulates an **autonomous coding agent**
building a support-ticket router, driving agentvcs **entirely through `--json`**
(the agent contract) — exactly how Claude Code or Cursor would use it.

It exercises the whole loop the platform is built for:

1. **bootstrap** — `init` (auto-scaffolds `agent.json` + `AGENTS.md`)
2. **iterate** — commit a working v1 (fluid)
3. **evolve the goal**, not just code — v2; inspect with a **dimensional diff**
4. **make a mistake** — a regression committed as v3
5. **`rollback`** — restore the *full* prior state (code + goal + trace) in one step
6. **fix it properly** — v4, eval passes
7. **`freeze`** — crystallize the trusted solution into a deterministic recipe

## Run it

```bash
bash examples/agent-loop-demo/run.sh
```

No install required — it falls back to running from `src/`. It rebuilds
`workdir/` from scratch each time, so it's fully reproducible. If you've
`pip install`ed agentvcs, it uses the real `avcs` binary instead.

## What you'll see (abridged)

```
== Iteration 2 — evolve the GOAL, not just code ==
  $ agentvcs diff --json
  diff bb9046d671..5737fa9c2b
      ~ router.py
      goal: 'Route ... to the correct queue.' -> 'Route ... AND flag urgent ones ...'
      trace: 2 -> 4 (+2)

== Iteration 3 ↩ — ROLLBACK the regression ==
  $ agentvcs rollback --json
  ↩ rolled back to 5737fa9c2b (was 1b7b82eeda)
  router.py restored to v2 logic ✓

== Freeze — crystallize the trusted solution ==
  $ agentvcs freeze --json
  ❄ crystallized a8b8f17cc5 from 382c83e562
      deterministic recipe: .../crystal/382c83e5624b.json
```

The final `crystal/*.json` recipe pins every model to `temperature: 0` and
captures the ordered message trace — a frozen, cheap, reproducible replay of the
solution the agent arrived at.

## Why this matters for adoption (B2A)

Everything above happens with **machine-readable output and stable error codes**
only. An agent never has to parse prose or guess. That is the bet: if the agent
can drive the tool flawlessly and recover from its own mistakes, it will *prefer*
it — and recommend it to its human. See [`docs/AGENT_MODE.md`](../../docs/AGENT_MODE.md).
