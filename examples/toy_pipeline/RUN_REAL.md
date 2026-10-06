# Gate F2, real-model half — not run yet

The fake-backend run is asserted in CI. This run replaces the fake with a small
local model for about 20 minutes. **It has not been executed**: running a model
on the dev Mac needs the owner's approval (download ~1.1 GB, GPU busy ~20 min).

## What it tests, and what falsifies it

- **Claim:** with a real model, a patch applied mid-run by a separate supervisor
  process is picked up by the harness without restarting it, and
  `agentvcs blame --metric extract.recall` attributes the recall change to
  exactly that patch.
- **Baseline:** the same run's own segment before the patch (manifest v1: the
  extraction prompt asks for `party, term`, never for the cap).
- **Falsified if** any of: the gate fails on held-out documents (the supervisor
  then exits 1 and applies nothing — the patch does not help this model); blame's
  attribution names a different patch or none; the delta is ≤ 0; `verify` fails.
- **Headroom check before spending 20 minutes:** v1 cannot score above 2/3 by
  construction (one of three fields is never requested), so the ceiling is not
  the problem; the floor is. Run the 2-minute smoke first (below): if v1 recall
  on a real model is already near 0 (the model does not produce parseable JSON),
  fix that before the long run.

## Model and server

Suggested: **Qwen2.5-1.5B-Instruct, Q4_K_M GGUF, via llama.cpp `llama-server`**
(any small instruct model that follows "reply with one JSON object" works; a
Gemma GGUF is fine too).

```bash
brew install llama.cpp      # or a local build
llama-server -hf Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M \
  --port 8080 -c 4096 --parallel 1
# wait for "server is listening on http://127.0.0.1:8080"
```

## Commands

From the repository root, after `crates/agentvcs-py/dev.sh`:

```bash
PY=crates/agentvcs-py/.venv/bin/python

# 1. smoke, ~2 min: proves JSON parses and the patch path works on this model
$PY examples/toy_pipeline/run_pipeline.py --backend openai \
  --base-url http://127.0.0.1:8080/v1 --model qwen2.5-1.5b-instruct-q4_k_m \
  --docs 60 --patch-after 15 --workdir examples/toy_pipeline/workdir-smoke

# 2. Gate F2 run, ~20 min
$PY examples/toy_pipeline/run_pipeline.py --backend openai \
  --base-url http://127.0.0.1:8080/v1 --model qwen2.5-1.5b-instruct-q4_k_m \
  --docs 800 --patch-after 200 --workdir examples/toy_pipeline/workdir-real \
  2>&1 | tee examples/toy_pipeline/workdir-real.log
```

Progress is streamed (one `[harness] doc i/N` line per document), so the run's
position is always visible and it can be stopped early with Ctrl-C (the harness
then writes `run_end` with status `aborted`; the ledger up to that point still
verifies and can be blamed).

**Duration estimate [read, not measured]:** three calls per document (~150-token
prompts; ~40, ~5 and ~40 output tokens). A 1.5B Q4 model on an M-series GPU
generates on the order of 80-100 tokens/s, so ≈1.2-1.6 s per document → 800
documents ≈ 16-21 minutes, plus the gate (12 held-out documents, ~15 s) when the
supervisor fires after document 200. Use the smoke run's `seconds` (in
`workdir-smoke/result.json` → `harness.seconds`) to rescale `--docs`.

## What blame should show

`workdir-real/result.json` → `blame["extract.recall"]`:

- two segments: steps `0 … k-1` under v1 and `k … 2399` under v2, where `k` is the
  patch's `applied_at_step` (around step 600-620; it depends on when the gate
  finishes) and equals `harness.reloads[0].at_step`;
- segment 1 mean ≤ 0.667 (≈ 0.6-0.667 if the model copies party and term well);
- segment 2 mean higher — expected ≈ 0.85-1.0;
- one attribution, `patches == [<the supervisor's patch_id>]`, `delta` > 0
  (expected ≈ +0.2 to +0.33);
- `verify: true`; `harness.stats.reruns` small (0-2).

`check.ok` and `summary.mentions_cap` should move in the same direction; they are
noisier with a real model and are not part of the gate.

As BLAME.md warns, a positive delta is attribution at a boundary, not causation:
later documents could differ. The synthetic documents are i.i.d. from one
generator, which limits that confound here. If the effect shows up, the
attribution arm is the `--no-reload` control (same command plus `--no-reload`,
another ~20 min; expected delta ≈ 0). Buy it only after the first run shows an
effect.

## Run on Colab (briefed 2026-10-06, before running; approved by the owner)

Not on the Mac: on a Colab GPU VM, same model and server as above —
Qwen2.5-1.5B-Instruct Q4_K_M via a prebuilt CUDA `llama-server` (b11443), `-c 4096 --parallel 1`.
agentvcs is built from `main` on the VM (rustup ≥ 1.89, maturin wheel for Linux x86_64).
Order: the 2-minute smoke first; if v1 recall is near 0 (unparseable JSON), stop and report.
Then the Gate F2 run with `--docs` rescaled from the smoke's `harness.seconds` to ≈ 20 minutes,
`--patch-after` at a quarter of the docs. One Colab session (≤ 60 min); falsifiers as above.

## Result (2026-10-06, Colab T4; files in `runs/f2-real-2026-10-06/`)

Qwen2.5-1.5B-Instruct Q4_K_M (SHA-256 `6a1a2eb6…407e`), llama.cpp b11443, temperature 0, seed 7.

- **Smoke (60 docs):** gate 0.917 (n = 12) passed; patch applied at step 60 = `harness.reloads[0].at_step`;
  blame on `extract.recall`: 0.417 → 0.825, one attribution naming exactly that patch, **delta +0.408**;
  `verify` true.
- **Gate F2 run (600 docs, 262 s — `--docs` was rescaled from the smoke's warm-up-inflated rate, so it
  ran ~4.4 min instead of ~20):** the supervisor's gate scored **0.889 < 0.9** on the same 12 held-out
  docs → not applied → one segment (mean 0.426), no attribution; `verify` true (1802 entries).
- **Falsifier met: "the gate fails on held-out documents".** Gate F2 is **not passed**.

**Why, read from the files.** The threshold is absolute (`extract.recall ≥ 0.9`) over 12 docs whose
recall is in thirds, so the mean moves in steps of 1/36: 0.889 is one missed field below 0.917. And the
same 12 docs gave 0.917 in the smoke and 0.889 here at temperature 0 — llama.cpp is not reproducible
run to run, so the gate decided on one field's noise. Against v1's 0.40 the patch more than doubles
recall either way. The check can fail while the capability works (CLAUDE.md); redefining it after this
result is a change of instrument and needs the owner's sign-off before any rerun.

## Rerun with a relative gate (briefed 2026-10-06, before running; signed off by the owner)

**Change of instrument, made after the result above and logged as such.** The supervisor's gate now
scores the candidate *and* the patch's `from_manifest` on the same 12 held-out documents
(`gate_eval.py --paired`, base read from the store via `AGENTVCS_FROM_MANIFEST`) and requires
`extract.recall.gain ≥ 0.10`. Paired on the same documents, run-to-run noise mostly cancels; the
question becomes "does the patch help by at least 0.10", not "is the level above an arbitrary 0.9".

**Run.** Same model, server and Colab T4 recipe; `--docs` sized from the *steady* rate measured in the
first run (0.44 s/doc) for ≈ 20 min: `--docs 2700 --patch-after 675`. One session.

**Falsifiers (unchanged except the gate):** gate gain < 0.10 (nothing applied); blame names another
patch or none; delta ≤ 0; `verify` fails.
