# SkillOS × Gemma × agentvcs — a meta-agent that builds and versions agents

A **meta-agent**: an agent whose job is to *plan, generate, execute and version
other agents*. It is the full marriage of three layers:

```
   SkillOS runs the cognitive pipeline (ingress→routing→planning→execution→memory→egress)
            on Gemma 4 31b (local via Ollama) → Gemini (hosted alternative)
                              │  each iteration builds + evals a sub-agent
                              ▼
   agentvcs commit  →  snapshot { code, goal, models(=the model that ran), trace(=SkillOS session) }
                              │
        eval failed? → rollback        goal changed? → diff shows the goal moved
                              │
                  trusted (eval passes)
                              ▼
   agentvcs freeze  →  models pinned to temp 0 + SkillOS trace compiled to a recipe
                       = a deterministic, cheap, replayable agent
```

* **[SkillOS](https://github.com/EvolvingAgentsLabs/skillos)** is the "markdown OS":
  agents/tools/skills are markdown (`skills/**.md` here). Its cognitive pipeline +
  context isolation let a mid-tier model behave like a frontier one.
* **Gemma 4 31b** is the engine — local via **Ollama** (`gemma4:31b`), the primary
  model. **Gemini** is an optional hosted alternative (`GEMINI_API_KEY`); an
  offline deterministic backend runs when neither is configured, so the demo is
  reproducible anywhere.
* **agentvcs** versions the *evolving* meta-agent across all four dimensions and
  freezes the trusted result.

## Run it

```bash
bash run.sh                                               # offline, fully reproducible
OLLAMA_BASE_URL=http://localhost:11434/v1 \
GEMMA_MODEL=gemma4:31b             bash run.sh            # Gemma 4 31b — the primary engine
GEMINI_API_KEY=AI...               bash run.sh            # Gemini — optional hosted alternative
```

With no credentials the planning rationale comes from a deterministic offline
backend (you'll see a `[meta-agent] ... using offline deterministic backend`
line — that's the Gemma→Gemini→offline fallback chain working). The generated
code, the eval, and the captured SkillOS trace are produced either way, so the
version-control story is identical.

## What you'll see

`run.sh` drives a five-iteration evolution, every command in `--json`:

| Step | What happens | agentvcs |
|---|---|---|
| v1 | Build a naive top-keywords sub-agent. Eval passes. | `commit` (fluid) — trace auto-captured |
| v2 | **Goal evolves**: ignore stop-words. Rebuild. Eval passes. | `commit` + `diff` shows the **goal** moved, not just code |
| v3 | A "smart optimization" that overfits. Eval **fails**. | `commit` the experiment |
| v3 ↩ | The regression is bad. | `rollback` restores code + goal + trace in one move |
| v4 | Proper stop-word-aware rebuild. Eval passes. | `commit` |
| ❄ | The meta-agent is trusted. | `freeze` → deterministic recipe under `crystal/` |

Then see it as a chat:

```bash
PYTHONPATH=../../src python3 -m agentvcs.cli -C workdir ui
```

A split view: the commit graph, and per commit its dimensional diff plus the
meta-agent's SkillOS reasoning (the ingress→…→egress phases) rendered as a
conversation — the exact pipeline that produced those lines of code.

## How the trace capture works (zero trace files)

`agent.json` declares:

```json
"trace": { "provider": "skillos", "auto": true }
```

`meta_agent.py` writes each pipeline phase to `.skillos/sessions/<stage>.jsonl`.
At commit time, agentvcs's **`skillos` trace provider**
(`src/agentvcs/traces/skillos.py`) vacuums the newest session log — the real
`planning` / `execution` events, with the model that actually ran — and pins the
model from it. You maintain no trace file by hand. `.skillos/` is kept out of the
*code* dimension via `.agentvcsignore`, so it shows up only as the **trace**.

## Files

| File | Role |
|---|---|
| `agent.json` | the four dimensions (goal, models, trace, state) |
| `meta_agent.py` | the SkillOS pipeline: backends (Gemma/Ollama → Gemini → offline) → plan → generate → execute → eval → session log |
| `skills/**.md` | the meta-agent's own skills, defined in markdown (SkillOS style) |
| `run.sh` | the end-to-end driver (commit / diff / rollback / freeze) |
| `AGENTS.md` | operating manual for the next agent that opens this project |

## Wire it into your own repo

```bash
agentvcs init --skillos        # scaffolds agent.json with the skillos trace provider
```

See [`docs/DEMO_GEMMA_SKILLOS.md`](../../docs/DEMO_GEMMA_SKILLOS.md) for the full
architecture analysis.
