# SkillOS × Gemma × agentvcs — meta-agent operating manual

This project is a **meta-agent**: an agent whose job is to *plan, generate,
execute and version other agents*. It is built on three layers:

| Layer | Tech | Role |
|---|---|---|
| Brain / OS | **[SkillOS](https://github.com/EvolvingAgentsLabs/skillos)** | Skills/agents defined in markdown. Runs the cognitive pipeline: ingress → routing → planning (HWM) → execution → memory → egress. |
| Engine | **Gemma 4 31b via Google AI Studio** (Gemini API, `gemma-4-31b-it`) → **local Gemma 4 31b via Ollama** (fallback) | The model that does the reasoning. Mid-tier + SkillOS's context isolation ≈ frontier behaviour, 50–100× cheaper. |
| VCS | **agentvcs** (this repo) | Versions the evolving meta-agent across **code + goal + models + trace**, rolls back mistakes, and **freezes** the trusted result into a deterministic recipe. |

## The four dimensions live in `agent.json`
- **goal** — what the meta-agent is currently trying to build.
- **models** — Gemma 4 31b via Google AI Studio (option 1), local Ollama Gemma as
  fallback. Marked `auto`, so each commit pins *whatever model actually ran*.
- **trace** — `{ "provider": "skillos", "auto": true }`. You maintain **no** trace
  file: `agentvcs commit` vacuums the SkillOS session log written to
  `.skillos/sessions/*.jsonl` (the real pipeline phases).
- **state** — `fluid` while exploring; `crystallized` once frozen.

## The loop (what `run.sh` automates)
1. The meta-agent runs a SkillOS pipeline (`meta_agent.py`) to **plan → generate
   → execute → evaluate** a sub-agent. This writes the sub-agent under
   `subagent/` and a session log under `.skillos/sessions/`.
2. `agentvcs commit -m "..."` snapshots all four dimensions. The trace + model pin
   are captured automatically.
3. `agentvcs diff` shows *which dimension moved* (goal vs code vs trace).
4. A bad iteration is undone with `agentvcs rollback` (the panic button).
5. When the sub-agent's eval passes and is trusted, `agentvcs freeze` crystallizes
   it: models pinned to temperature 0, the SkillOS trace compiled into a
   replayable recipe under `crystal/`.

## Always drive agentvcs in `--json`
Branch on `error.code`, never on prose. See `docs/AGENT_MODE.md` in the repo root.

## Run it
```bash
bash run.sh                 # full end-to-end demo (offline-safe; uses a model if configured)
GEMINI_API_KEY=AI... bash run.sh                                              # Gemma 4 31b via AI Studio (option 1)
OLLAMA_BASE_URL=http://localhost:11434/v1 GEMMA_MODEL=gemma4:31b bash run.sh  # Gemma 4 31b via local Ollama (fallback)
```
With no credentials it still runs end-to-end on a deterministic offline backend,
so the version-control story (commit / diff / rollback / freeze) is fully
reproducible in CI.
