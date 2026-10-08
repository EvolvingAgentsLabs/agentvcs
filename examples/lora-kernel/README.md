# LK0 — agentvcs versioning the harness of lora-kernel's Mac/edge stack

[lora-kernel](https://github.com/EvolvingAgentsLabs/lora-kernel) serves small local models — a Gemma 4 12B
with a LoRA expert and Gemma's MTP drafter on MLX, an E4B library member on llama.cpp, a proxy that routes
between members — and changes their configuration one measured experiment at a time. This example puts that
configuration under agentvcs:

1. **import** — `import_lk.py` reads a lora-kernel checkout (read only: code is parsed with `ast`, never
   imported or run) and builds a typed `HarnessManifest` of the stack, every value with its source.
2. **history** — `history.py` turns nine measured configuration changes into patches in agentvcs run ledgers.
   Each patch's gate reads its numbers from lora-kernel's committed results files; the steps around it carry
   the before/after values, so `blame` attributes each delta to the patch that brought it.
3. **branches** — two lines diverge from a common fork point: `domain` keeps the expert LoRA on and aligns the
   drafter to it; `speed` keeps the expert resident but inactive and drafts two tokens a round. They conflict.
4. **merge** — `agentvcs merge prepare` shows what merges mechanically and hands each conflict over with its
   evidence; `agentvcs merge resolve` asks **Claude Code** to decide, audits the session, gates the merged
   manifest with a static check (`suite.yaml` → `check_manifest.py`) and records the decision.

## The principle

agentvcs has no model of its own. **Its only LLM is Claude Code**, invoked by `merge resolve` with two MCP tools
and `Read` confined to a workspace (spec/MERGE.md §6). The local models are **the controlled system**, never
part of agentvcs: nothing in this example loads or runs Gemma, MLX or llama.cpp. lora-kernel's numbers enter
only as values read from its committed results files.

**Imported, not live.** Every step and patch in these ledgers is an imported measurement: step `agent_id` and
patch `author.id` are `imported:<results dir>`, timestamps are the experiments' own, and nothing was re-run.
The two branches are **constructed for this demo** from measured numbers; neither is a serving decision
lora-kernel has made.

## Run it

```bash
crates/agentvcs-py/dev.sh                                  # once: the SDK into a venv
examples/lora-kernel/demo.sh --dry-run                     # import → history → prepare; stops before resolve
examples/lora-kernel/demo.sh                               # ... and `merge resolve` with the real `claude`
examples/lora-kernel/demo.sh --dry-run --lk examples/lora-kernel/tests/fixture/lk   # without a lora-kernel checkout
```

`--lk` (or `$LK`) defaults to `~/evolvingagents/lora-kernel`. Without `claude` on `PATH` (or `CLAUDE=…`), the
demo prints a note, writes the resolver's workspace with `merge resolve --dry-run`, and prints the exact
command to run. `RESOLVE_MODEL` and `RESOLVE_BUDGET_USD` pass `--model` / `--budget-usd` through.

## The manifest (fork point, 2026-10-06)

| dimension | kind | what | source in lora-kernel |
|---|---|---|---|
| `serve.model` | model | `mlx-community/gemma-4-12B-it-4bit` on mlx-vlm 0.7.3 | `examples/mac/mlx_spec_lora.py:BASE`; engine from MLXK0's BRIEF |
| `spec.drafter` | model | `google/gemma-4-12B-it-assistant`, method `mtp` | `examples/mac/mlx_spec_lora.py:DRAFTER` |
| `serve.adapter` | adapter | expert `wiki12b-walks-s0`, `active: true` | `results/B3-…/train_12b.json#/members/withlib-s0/adapter_sha256` |
| `spec.sampling` | sampling | temperature 0, greedy, `max_tokens` 160, `draft_tokens` null (the drafter's default) | the runner's `--max-tokens` / `--block-sizes` defaults and its `"temperature": 0.0` |
| `library.model` | model | `gemma-4-E4B-it-Q8_0.gguf` on llama.cpp, context 12,288 | `docs/SERVING.md` (the library's `llama-server` line), `serve.py --tokenizer` |
| `library.adapter` | adapter | `real-none-s0` (+ its GGUF file name) | `results/REAL4-…/train_none_s0.json#/members/withlib-s0/adapter_sha256` |
| `library.config` | config | `cite_gate` true, `page_top` 8, `page_budget` 2,500, `guard` strict | `examples/library/serve.py` argparse defaults |
| `route.router` | router | `factored`, `role_confirmed`, tracker member `tracker-out-s0` | `training/harness/openai_proxy.py` defaults; `results/ROUTE1-…/train_tr_out.json` |
| `member.prompt` | prompt | **a reference**: `@ref memory/prompt.py:SYSTEM_WIKI` + sha256 + length | sha256 of the constant's UTF-8 (role.toml's convention); the text is never copied |
| `member.sampling` | sampling | `max_tokens` 256, thinking off | `openai_proxy.py:MEMBER_MAX_TOKENS`, `setdefault("enable_thinking", False)` |

**What is hashed for `weights_hash`.** The protocol requires a `b3:` hash for an adapter, and agentvcs never sees
the weights. `weights_hash = hash({"sha256": <hex>})` — BLAKE3 over the JCS of the sha256 lora-kernel recorded for
the adapter's files when it trained them (`adapter_sha256`); the hex itself is kept beside it as `sha256`, with
`source`. The DRAFT0 drafter adapter has no recorded `adapter_sha256`, so its `<hex>` is the sha256 of the bytes
of `results/DRAFT0-aligned-drafter-20261006/draft0.json`, the record that describes it, and `sha256_of` says so.

## The imported history: change → source → value

Every value below is read at gate time by `history.py gate-metrics <CHANGE>` from the file named; none is typed.
One (context overflows) exists only in a BRIEF.md and is parsed from it; its source is marked so in the ledger.

| change (results dir) | run | dimensions | metric | before → after | read from |
|---|---|---|---|---|---|
| LIVE-library2 | lk-trunk | `library.config` | `library.live_right` | 36/52 → 37/52 | `LIVE-library-20261001/live.json` → `LIVE-library2-20261002/live.json` (`right`/`n`) |
| LIVE-library2 | lk-trunk | `library.config` | `library.context_overflows` | 4 → 0 | `LIVE-library2-20261002/BRIEF.md` (parsed: "llama-server logged 0 context overflows (4 before)") |
| GATE0 | lk-trunk | `library.config` | `library.delivered_precision` | 0.625 → 0.777 | `GATE0-cite-gate-20261002/gate0.json#/precision_before`, `/precision_after` |
| PAGE0 | lk-trunk | `library.config` | `library.page_answerable` | 30/44 → 34/44 | `PAGE0-page-top-20261002/verdict.json#/answerable/…` |
| ROUTE0 | lk-trunk | `route.router` | `route.foreign_served_locally` | 294/600 → 0/600 | `ROUTE0-factored-router-20261002/verdict.json` |
| ROUTE1 | lk-trunk | `route.router` | `route.tracker_abstained_out` | 0/30 → 27/30 | `ROUTE1-tracker-abstain-20261003/route1.json#/reading/arms/…/abstained_out` |
| SPECK0 | lk-trunk | `serve.model`, `spec.drafter`, `spec.sampling` | `mac.spec_speedup_base_general` | 0.57× → 1.25× | `SPECK0-…/speck0.json` (llama.cpp, k = 3) → `MAC-mlx-12b-lora-mtp-20260927/mac.json` (MLX) |
| MLXK0 | lk-domain | `spec.sampling` | `mlx.speedup_lora_domain` | 0.92× → 1.08× | `MAC-…/mac.json` (drafter default) → `MLXK0-…/mlxk0.json` (k = 1) |
| DRAFT0 | lk-domain | `spec.drafter_adapter`, `serve.adapter` | `spec.alpha_domain` | 0.6574 → 0.9644 | `DRAFT0-aligned-drafter-20261006/draft0.json#/alpha/{stock,aligned}/domain` |
| DRAFT0 | lk-domain | (same) | `mlx.speedup_projected_k1_domain` | 1.322× → 1.567× **projected** | `draft0.json#/projected_speedup_k1/domain/…` |
| HOTL0 | lk-speed | `serve.adapter`, `spec.sampling` | `mlx.speedup_general` | 1.23× → 1.43× | `HOTL0-mac-hotlora-cost-20261006/h1_wrapped.json` (`wiki12b/general/mtp_b2` → `base/general/mtp_b3`) |

Each patch's gate thresholds are the pre-registered bar of its BRIEF where there is one (GATE0: ≤ 1 % of right
answers blocked and ≥ 15 % of not-right; ROUTE1: ≥ 27/30 abstained, ≤ 3 dependent lost; DRAFT0: α ≥ 0.85 and
+0.15; HOTL0: wrapper cost < 0.08; LIVE-library2: 0 overflows), otherwise a positive gain. Config values that are
not metrics (the "before" of a flag, e.g. `page_budget` 0 or the `dictionary` router) are checked as quotes in the
file that states them (`config_sources` in `history.py`).

Caveats carried in the patch rationales: MLXK0's before/after come from two sittings (HOTL0 later found MLXK0's
sitting slow); HOTL0's "before" is the expert active at its best measured k (k = 1), its "after" the expert
resident with 328 inactive wrappers at k = 2 (the base with nothing attached reaches 1.47×); DRAFT0's α is
offline on Colab and its speed-up is a projection never measured on the Mac.

Not imported, and why: **F0** (the MTP drafter beats EAGLE-3) was measured on vLLM on an L4, not on this stack;
**E6** (a LoRA on layers 21–41 loses nothing) is the E4B `school` member, not the 12B expert — writing it into
`serve.adapter` would invent a measurement.

## The conflict, and why it needs judgment

| dimension | base (fork) | ours = `domain` | theirs = `speed` |
|---|---|---|---|
| `serve.adapter` | expert active | `switch_with: spec.drafter_adapter` (DRAFT0) | `active: false` (HOTL0) |
| `spec.sampling` | `draft_tokens` null | `draft_tokens` 1 (MLXK0, DRAFT0 is k = 1) | `draft_tokens` 2 (HOTL0's best on the base) |
| `spec.drafter_adapter` | — | added (DRAFT0) | — → merges mechanically as `ours` |

`speed` has the faster **measured** number on the Mac — 1.43× with the expert resident but inactive — but with
the expert off the 12B answers as the base, so domain quality is given up for it. `domain` keeps the expert and
its drafter's acceptance on the expert's prompts went 0.66 → 0.96 (measured), but its 1.57× is a **projection**
that has never run on the Mac. Choosing between a measured speed-up that drops the expert and a projected one
that keeps it is a product judgment the runtime cannot make.

The static gate (`check_manifest.py`, no model) passes either coherent choice and refuses the incoherent one:

| `serve.adapter` | `spec.sampling` | gate | why |
|---|---|---|---|
| ours | ours | pass | expert on + aligned drafter at k = 1 |
| theirs | theirs | pass | expert inactive, k = 2 (measured on the base) |
| theirs | ours | pass | expert inactive, k = 1 |
| ours | theirs | **fail** (`k_in_measured_range` 0) | an aligned drafter at k = 2 was never measured: DRAFT0 did not train the chained drafts (k > 1) |

It also checks that every adapter is hashed (`weights_hash == hash({"sha256": …})`), that a drafter adapter
names the drafter it was trained on, is aligned to the expert being served and switches with it, and that
sampling is greedy.

## Tests

`tests/test_lk0.py` runs against `tests/fixture/lk`, a minimal subset of a lora-kernel checkout rebuilt by
`make_fixture.py --lk <checkout>` from exactly what the importer and the gates read (the prompt's text is
replaced by a placeholder). It covers the importer, ledgers that `verify` and `blame`, the intended conflict,
`merge resolve` end to end with the fake `claude` (`crates/agentvcs-cli/tests/fake_claude/claude`; the real
Claude Code is never invoked in tests), the four gate outcomes above, and `demo.sh --dry-run`. CI runs it in the
Python SDK workflow beside the toy pipeline.

## Files

| file | does |
|---|---|
| `lkread.py` | read-only access to a checkout; every read returns its value and its source |
| `import_lk.py` | the fork-point manifest (`--facts` writes every extracted value with its source) |
| `history.py` | the nine changes, the three ledgers, and `gate-metrics` (the imported gates' suite command) |
| `check_manifest.py`, `suite.yaml` | the static gate for the merged manifest |
| `demo.sh` | the whole flow |
| `make_fixture.py`, `tests/` | the fixture and the tests |
