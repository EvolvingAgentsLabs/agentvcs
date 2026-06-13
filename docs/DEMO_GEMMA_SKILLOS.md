# Demo: a SkillOS × Gemma meta-agent, versioned with agentvcs

> A complete, runnable demo where **SkillOS** plans/generates/executes agent
> projects, **Gemma 4 31b** (via the Google AI Studio Gemini API, local Ollama
> fallback) is the engine, and **agentvcs** versions the whole evolving system
> and freezes the trusted result.
>
> Runnable code: [`examples/skillos-gemma-meta-agent/`](../examples/skillos-gemma-meta-agent/).

## 1. Why these three fit

Each layer solves a distinct part of "an agent that builds and operates other
agents":

| Layer | Piece | Role |
|---|---|---|
| Brain / OS | **[SkillOS](https://github.com/EvolvingAgentsLabs/skillos)** | Skills/agents/tools in *pure markdown*. Runs the cognitive pipeline ingress → routing → planning (HWM) → execution → memory → egress. Gives hierarchical planning and multi-agent execution. |
| Engine | **Gemma 4 31b** via Google AI Studio (Gemini API, `gemma-4-31b-it`) → local Ollama (fallback) | The reasoning model. SkillOS's Recursive Context Isolation gives a mid-tier model frontier-like executive function at 50–100× lower cost. |
| VCS | **agentvcs** | Versions the meta-agent across **code + goal + models + trace**, rolls back mistakes, and **freezes** the trusted result into a deterministic recipe. |

The conceptual fit is exact: **SkillOS provides the *fluid* side** (high-temperature
exploration on Gemma), and **agentvcs provides the *crystallized* side** (the
trusted recipe, frozen). That is precisely agentvcs's `fluid → crystallized`
lifecycle — now driven by a real agent runtime instead of a simulator.

```
   SkillOS runs FLUID on Gemma 4 (exploring) ──▶ agentvcs commit {code,goal,models,trace}
        mistake? rollback   |   alt strategy? branch              │
                                                       trusted ──▶ agentvcs freeze
                                          = Gemma pinned to temp 0 + trace → replayable recipe
```

## 2. What the meta-agent does (the loop)

Given a goal — *"build an agent that extracts the top keywords from text"* — the
meta-agent:

1. **PLANS** — SkillOS HWM: an L2 macro-planner decomposes into subgoals.
2. **GENERATES** — emits a sub-agent: a SkillOS markdown skill + a self-contained tool.
3. **EXECUTES** — runs the sub-agent in an isolated subprocess against eval cases.
4. **EVALUATES & ITERATES** — passes/fails; evolves goal or code.
5. **VERSIONS each iteration with agentvcs** — and freezes the trusted sub-agent.

"For agent projects **and for agents**" = the meta-agent is itself a versioned
SkillOS project, and it *produces* versioned agent projects. Clean recursion.

## 3. The integration: a SkillOS trace provider

agentvcs has **pluggable trace providers** (`src/agentvcs/traces/`; `claude-code`
was the first). This demo adds **`skillos`**:

* **`src/agentvcs/traces/skillos.py`** — reads a SkillOS agent-runtime session log
  (`.skillos/sessions/*.jsonl`), one JSONL event per pipeline phase, and
  normalizes it to the agentvcs trace shape. It does **not** import SkillOS — the
  core stays zero-dependency; it just reads the log off disk. Tolerant of the
  content-key shapes a SkillOS run emits (`content` / `text` / `message`).
* Declared in `agent.json` as `"trace": { "provider": "skillos", "auto": true }`,
  so **you maintain no trace file**: each `agentvcs commit` vacuums the newest
  session — the real `planning` / `execution` events — exactly like the Claude
  Code provider does for a live Claude session.
* **Model pin auto-detection**: with `"models": [{ "provider": "google", "model":
  "gemma-4-31b-it", "auto": true }]` the pin is filled from the model that actually
  ran (`gemma-4-31b-it` via AI Studio, or `gemma4:31b` if the local Ollama fallback
  is used) — agentvcs versions *the model that ran*, not a hand-typed guess.
* **`agentvcs init --skillos`** scaffolds this manifest in one command.

### The fluid → crystallized payoff

`agentvcs freeze` pins every model to `temperature: 0` and compiles the SkillOS
trace into `crystal/<commit>.json`. For Gemma this means the trusted sub-agent
becomes **reproducible and cheap**. It pairs naturally with SkillOS's *dialects*
(50–99% token compression): a crystallized recipe + dialects = a tiny,
deterministic production agent.

## 4. Configuring the engine

The demo's backend selection is **Gemma 4 31b via AI Studio → Gemma 4 31b via
Ollama → deterministic offline**:

```bash
# Option 1 — Gemma 4 31b via Google AI Studio (the Gemini API)
GEMINI_API_KEY=AI...   GEMMA_API_MODEL=gemma-4-31b-it   bash run.sh

# Fallback — local Gemma 4 31b via Ollama
OLLAMA_BASE_URL=http://localhost:11434/v1   GEMMA_MODEL=gemma4:31b   bash run.sh

# No credentials — offline deterministic backend (CI-reproducible)
bash run.sh
```

The offline backend produces the planning rationale deterministically; the
generated code, the eval, and the captured SkillOS trace are produced regardless,
so the version-control story is identical with or without a model.

## 5. The "wow" moment

Side by side, `agentvcs diff` reveals *which dimension moved* at each step — "here
the **goal** changed, here the generated **code**, here the planning **trace**, the
**model** was Gemma throughout" — and then `agentvcs freeze` turns that fluid,
expensive-to-explore meta-agent into a **deterministic recipe that runs Gemma at
temperature 0 for pennies**. agentvcs's thesis ("cultivated, not written") made
tangible with a real runtime and an open model.

## 6. Mapping to a full production demo

The runnable example covers the end-to-end story offline. To take it to a live
SkillOS install:

1. Point the provider at the real session log: `"trace": { "provider": "skillos",
   "dir": "<skillos>/.skillos/sessions" }` (or `path` for an exact file).
2. Replace `meta_agent.py`'s pipeline with calls into SkillOS's
   `agent_runtime.py` / `run_scenario.py` — the provider already reads whatever
   JSONL it writes; only the field names need to line up (see the schema in
   `src/agentvcs/traces/skillos.py`).
3. Keep the same agentvcs loop: `commit` per iteration, `diff` to inspect, `branch`
   for alternative strategies, `rollback` for regressions, `freeze` when trusted.

## 7. Risks / open questions

* **SkillOS session format.** SkillOS doesn't publicly pin an on-disk session path,
  so the provider targets a documented JSONL schema (mapped to the pipeline
  phases) and is tolerant of field-name variants. When SkillOS's persistence is
  confirmed, point `trace.dir`/`trace.path` at it — no provider change needed.
* **Zero-dependency invariant.** The provider and `meta_agent.py` are stdlib-only
  (AI Studio / Ollama are called via `urllib`, no SDKs), preserving agentvcs's core
  selling point.
* **Determinism at temp 0.** Gemma via Ollama is generally reproducible at
  `temperature: 0`; via a hosted API, also fix a `seed` for byte-stable replays.
