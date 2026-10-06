# toy_pipeline — a patch applied mid-run, hot-reloaded, and blamed

Three agents over a stream of synthetic contracts:

```text
extractor ──► checker ──► summarizer          (one step each per document)
  metric extract.recall   check.ok   summary.mentions_cap
```

Everything an agent does is read from the run's manifest (`extract.prompt`,
`extract.model`, `extract.sampling`, …). Version 1 of the extraction prompt asks
for `party, term` and never for the liability cap, so recall sits at 2/3.

Three processes, one channel (the ledger):

| process | file | does |
|---|---|---|
| orchestrator | `run_pipeline.py` | init store, snapshot v1, start the other two, then `export audit` → `verify` → `blame` |
| harness | `harness.py` | `with avcs.run(...)`, three `@avcs.step` agents, `run.on_patch` |
| supervisor | `supervisor.py` | watches `agentvcs log`, cites the checker's flags as evidence, writes v2, `patch propose` → `gate run` (held-out docs, `gate_eval.py`) → `patch apply` |

```bash
crates/agentvcs-py/dev.sh                       # once: build the SDK into a venv
crates/agentvcs-py/.venv/bin/python examples/toy_pipeline/run_pipeline.py --backend fake
```

Typical output [ran, 2026-10-06, Apple M4, ~4.5 s]:

```text
[supervisor] 4 extractions, mean recall 0.667; checker flagged steps [1, 4, 7, 10]
[supervisor] gate toy-holdout: {'extract.recall': 1.0, 'n': 12} passed=True
[supervisor] applied b3:409355a8673d… at seq 29
[harness] patch b3:409355a8673d… at step 28: extract.prompt reloaded
[run] blame extract.recall: steps 0-27 mean 0.667 (n=10) | steps 28-89 mean 1.000 (n=20)
[run] attribution: delta +0.333 -> patches ['b3:409355a8673d…'] (supervisor's patch b3:409355a8673d…)
```

Where the patch lands depends on timing (the supervisor runs a gate first), so
step numbers vary between runs; the segment means and the attribution do not.
The harness's `stats.reruns` counts steps that a patch overtook mid-step and that
were re-executed under the new manifest (ADR-0007 §3).

## The control arm

`--no-reload` makes the harness pin the manifest it started with and ignore
patches. The ledger still records the active manifest, so blame places the patch
at the same boundary — with **delta 0**. The improvement is therefore carried by
the reload channel, not produced by the fake backend or the scorer on their own.
Both arms are asserted in `tests/test_toy_pipeline.py`.

What blame does not show (BLAME.md): `check.ok` and `summary.mentions_cap` also
jump at the boundary, but by less than 1 when the patch lands mid-document — a
document extracted under v1 and summarized under v2 is credited to the patch.

## Backends

- `--backend fake` (default): an in-process OpenAI-compatible HTTP server
  (`agentvcs.testing.FakeOpenAIServer`) answering deterministically from the
  prompt it receives — it sees only what a real server would see.
- `--backend openai --base-url URL --model ID`: any OpenAI-compatible server
  (llama.cpp `llama-server`, vLLM, Ollama `/v1`). See [RUN_REAL.md](RUN_REAL.md).

The supervisor's CLI defaults to `python -m agentvcs` (the Rust CLI in-process);
`--cli /path/to/agentvcs` uses the release binary instead.
