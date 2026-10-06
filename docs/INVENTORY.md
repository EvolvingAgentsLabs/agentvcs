# agentvcs (Python) — inventory before the Rust / protocol v0.1 migration

Snapshot of branch `chore/revive-from-monorepo`, taken 2026-10-06. Every claim is tagged:
**[read]** means inferred from source or docs, and **[ran]** means observed by executing it. "v0.1" means the
planned protocol: HarnessManifest, StepRecord, PatchRecord, GateResult and RunLedger, BLAKE3 over RFC 8785.

## 1. Language, size, dependencies

- Python ≥ 3.10, built with hatchling. Package `src/agentvcs`. Entry points are `agentvcs`, `avcs` and `agentvcs-mcp` [read].
- **There are no runtime dependencies (stdlib only).** `pytest>=8` is a dev-only dependency. A test (`tests/test_zero_dependencies.py`) enforces the stdlib-only rule [read].
- The version numbers disagree: `pyproject.toml` and the installed metadata say `0.3.0`, while `agentvcs.__version__` is `0.4.0` [ran].
- Totals: src 7,783 Python LOC, tests 3,544, examples about 2,700 (py/sh/ts/mjs), and `src/agentvcs/ui/index.html` 376 [ran, `wc -l`].
- Non-Python parts: `packages/eve` (an npm hook and CLI for Vercel eve, 246 LOC) and `selftest/selftest.sh` (192) [ran].

| src module | LOC | | src module | LOC |
|---|---:|---|---|---:|
| cli.py | 1377 | | traces/anthropic_managed.py | 416 |
| merge.py | 760 | | traces/vercel_eve.py | 292 |
| dynamics.py | 635 | | traces/claude_code.py | 260 |
| repository.py | 596 | | traces/qwen_code.py | 222 |
| corporate.py | 410 | | traces/odyssey.py | 117 |
| mcp_server.py | 324 | | traces/__init__.py | 72 |
| monitor.py | 214 | | runtime/frame.py | 206 |
| soul.py | 191 | | ui/server.py | 102 |
| swarm.py | 191 | | ui/api.py | 72 |
| _ed25519.py (vendored) | 185 | | eval.py | 140 |
| scaffold.py | 161 | | crystallize.py | 128 |
| sbt.py | 153 | | plural.py | 104 |
| views.py | 102 | | recall.py | 95 |
| diff.py | 74 | | objects.py | 74 |
| replay.py | 57 | | `__init__`s | 53 |

| test file | LOC | tests | | test file | LOC | tests |
|---|---:|---:|---|---|---:|---:|
| test_merge | 491 | 18 | | test_ui | 142 | 10 |
| test_dynamics | 271 | 21 | | test_modes_and_recall | 131 | 8 |
| test_soul | 238 | 20 | | test_eval | 122 | 11 |
| test_reasoning_log | 227 | 11 | | test_qwen_provider | 116 | 7 |
| test_corporate | 206 | 14 | | test_packaging | 115 | 6 |
| test_swarm | 191 | 10 | | test_runtime_frame | 107 | 7 |
| test_trace_providers | 185 | 12 | | test_repository | 98 | 5 |
| test_agent_mode | 168 | 13 | | test_odyssey_provider | 94 | 5 |
| test_eve_provider | 168 | 9 | | test_monitor | 86 | 7 |
| test_anthropic_managed | 160 | 12 | | test_plural | 56 | 6 |
| test_zero_dependencies | 57 | 2 | | test_replay | 55 | 4 |
| test_crystallize | 50 | 2 | | conftest | 10 | – |

## 2. What it does today

### CLI commands (`cli.py`, one argparse subcommand each) [read]
All commands share `--json`, `-C DIR` and `--mode vcs|runtime`. Errors are emitted as `{"ok":false,"error":{"code",...}}`, with stable codes taken from `RepoError` [read]. I exercised init, commit, diff, eval, freeze, rollback and log end to end in a scratch repo [ran].

| command | does |
|---|---|
| `new <dir>` | Scaffolds a project: agent.json, AGENTS.md, skill, `.mcp.json`, a starter trace, and a first commit. |
| `init` | Creates `.agentvcs/` and template `agent.json`/`AGENTS.md`. Flags: `--claude-code`, `--qwen-code`, `--eve`, `--anthropic-managed`, `--runtime`, `--with-soul`, `--corporate`. |
| `trace` | Shows which trace source (file or provider) a commit would capture, and how many messages it holds. |
| `commit -m` | Snapshots tree + goal + models + trace (+ runtime frame, + swarm) into a commit object. |
| `log [--reasoning]` | First-parent history. `--reasoning` adds goal transitions, eval verdicts and rollback events, with an optional `--explain CMD`. |
| `status` | Uncommitted changes per dimension (a dry-run snapshot that hashes without writing). |
| `show [ref]` | One commit across all dimensions. `--trace` renders the messages. |
| `diff [a] [b]` | Dimensional diff: code add/rm/mod, goal from→to, model labels, trace message count delta, state. |
| `branch` / `checkout` | Git-like refs. Checkout rewrites the working tree. Detached HEAD is allowed. |
| `merge <branch>` | Three-way merge over code, models, goal+trace and swarm. Options: `--reconcile CMD`, `--target-goal`, `--force`. |
| `rollback [ref] [--reason]` | Restores the tree to the parent (or a ref), moves the branch, writes `ROLLBACK_HEAD`, and appends to `rollbacks.jsonl`. |
| `eval [ref]` | Runs `agent.json` `eval.command` N times and stores the result in the `.agentvcs/evals/<oid>.json` side-table. |
| `freeze` / `crystallize` | Eval-gated crystallization into a recipe plus a new `crystallized` commit (`--force` skips the gate). |
| `replay [ref] [--exec CMD]` | Emits a crystal recipe's steps, or pipes each step as JSON to CMD. |
| `recall [goal]` | Jaccard token overlap over the goals of crystallized commits, verified first. |
| `runtime` / `budget` / `context` | Operational frame rebuilt from the session log: tokens, $, context pressure, routing, tools, subagents. |
| `watch` / `statusline` | Live terminal panel and one-line status built from the runtime frame. |
| `ui` | Loopback HTTP dashboard (read-only JSON API plus a single-page app). |
| `soul` / `verify [--all]` | Ed25519 identity and SBT list; verifies commit signatures. |
| `audit` / `approve` | Corporate "Libro de Actas": checks commits against the mandate; a human representative signs approvals. |
| `fleet` | Diverse-fleet selection by correlation-discounted SBT skill profiles. |
| `price` / `health` / `infobits` / `contain` | Evolutionary diagnostics over the commit DAG and the eval side-table. |

### Object model and hashing [read, verified by ran]

- **Store.** `.agentvcs/objects/<aa>/<rest>`, git-style loose objects, zlib-compressed on disk (`objects.py:ObjectStore._store`) [read].
- **Hash.** SHA-256 hex (`objects.py:hash_bytes`). I recomputed `sha256(zlib.decompress(file)) == oid` for a commit [ran].
  - JSON objects are hashed over `canonical(obj)` with no type prefix.
  - Blobs are hashed over `b"blob\0" + bytes`, with no length field [read].
- **Canonicalization.** `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` encoded as UTF-8. **This is not RFC 8785**:
  - The float `1.0` serializes as `1.0`, while JCS gives `1`. I observed `{"temperature":1.0}` in a stored modelpin [ran].
  - Keys sort by Python code point, while JCS sorts by UTF-16 code unit.
  - NaN and Infinity are not rejected [read].
- **Object types** (`repository.py:snapshot`, `commit`) [read]:
  - `tree {entries: path→blob_oid}`, a flat map with no subtrees and no file modes.
  - `goal {text, parent}`.
  - `modelpin {provider, model, version, params}`, one per model.
  - `trace {messages:[...]}`: the whole message list as one object, re-stored on every commit.
  - `runtime {...frame}`, only in runtime mode.
  - `swarm`, only if declared.
  - `crystal {source_commit, goal, models, steps, verified, eval}`.
  - `commit {type, parents[], tree, goal, models[], trace, state, metrics, message, author, timestamp, [runtime], [swarm], [crystal], [soul, signature]}`.
- **The manifest is a file, not an object.** `agent.json` is read at commit time and is also itself a tracked file in the tree. Rollback and checkout restore goal and models by restoring that file, not by rehydrating from the goal and modelpin objects (`_restore_tree`) [read].
- **Refs** are `HEAD` plus `refs/heads/<name>` text files. **No SQLite index exists**; SQLite only appears as the odyssey trace *source* [read].
- **Side tables outside the content-addressed store** [read, ran]:
  - `evals/<oid>.json`, mutable and overwritable.
  - `rollbacks.jsonl`, append-only but **not hash-chained**.
  - `ROLLBACK_HEAD`.
  - The corporate approvals.
- **Reads do not check integrity.** `read_obj` decompresses and parses without re-hashing. There is no `fsck` [read].

### Eval-gated freeze [read, ran]
`crystallize.py:crystallize` works in five steps:
1. It refuses if the working tree contains conflict markers.
2. If `agent.json` declares `eval` and `--force` is not given, it calls `eval.ensure_passing`, which auto-runs the eval when none is recorded. All N runs must exit with `passing`.
3. It re-pins every model to `temperature=0, top_p=1` as new modelpin objects.
4. It writes a `crystal` recipe whose steps are the raw trace messages, and stamps it with `verified` and the eval summary. It also writes `crystal/<oid12>.json` into the **working tree**, so that file becomes code in the next commit.
5. It writes a new `state:"crystallized"` commit with the fluid commit as parent, copies the eval record forward, and mints an SBT if a Soul exists (best-effort).

With no `eval` declared, the gate is skipped entirely. "Multidimensional" here means the frozen recipe carries goal, models and steps together. The gate itself is a single shell command against the whole working tree; it is not per-dimension. I observed `freeze` return `verified:true` after `eval` passed [ran].

### Rollback [read, ran]
`Repository.rollback`:
- Restores the full tree to the target: HEAD's first parent by default.
- Sets the branch ref, writes the old head to `ROLLBACK_HEAD`, and appends `{from,to,timestamp,reason}` to `rollbacks.jsonl`.
- Is reversible because objects are never deleted.

It is a **ref move**: no new commit and no inverse-patch record. I observed this after a freeze [ran].

### Merge [read]
`merge.py:merge`:
- Finds the merge base by BFS LCA (lowest common ancestor) over the parent DAG.
- Merges code three-way, line by line with `difflib`, writing conflict markers.
- Resolves overlapping hunks with a "metric winner": eval ok/fail, or a score delta ≥ threshold.
- Merges model pins as a union keyed by (provider, model); on a params clash it keeps ours and records a conflict.
- Reconciles goal and trace either through an external `--reconcile CMD`, which receives a JSON bundle on stdin and returns `{goal, trace, resolved_files?}`, or mechanically (`"[merge] A + B"` plus one system message).
- Merges the swarm node by node, then writes a two-parent commit.

### Runtime mode [read]
Set with `"mode":"runtime"` in `agent.json` or `--mode runtime`. At commit time `runtime/frame.py:build_frame`, or the provider's `pull_runtime`, rebuilds an aggregate frame from the native session log: turns, tokens in/out/cache, cost against `budget.ceiling_usd`, context window and compactions, per-model routing, tool counts and subagent fan-out. The frame is stored as a `runtime` object on the commit. The aggregation is per commit, never per step.

Five trace providers normalize into the same `trace` object: `claude-code`, `qwen-code`, `vercel-eve`, `anthropic-managed` and `odyssey` (SQLite).

### MCP server [read]
`mcp_server.py` is stdio JSON-RPC 2.0 with `protocolVersion` 2025-06-18 and is stdlib only. It exposes 21 tools:
- History and inspection: `avcs_log`, `avcs_show`, `avcs_trace`, `avcs_diff`, `avcs_status`.
- Write and control: `avcs_commit`, `avcs_freeze`, `avcs_replay`, `avcs_rollback`, `avcs_branch`, `avcs_checkout`, `avcs_eval`, `avcs_merge`.
- Runtime and recall: `avcs_runtime`, `avcs_budget`, `avcs_context`, `avcs_recall`.
- Diagnostics: `avcs_price`, `avcs_health`, `avcs_infobits`, `avcs_contain`.

There are no soul, corporate or fleet tools.

## 3. Tests

- **220 tests, 220 passed in 2.6 s** under the scratchpad venv with `pytest -q -p no:cacheprovider` [ran]. Per-file counts are in the table above [ran, grep].
- CI runs on Python 3.10–3.13 with `pytest` plus the `examples/agent-loop-demo` smoke run and its scorecard [read, `.github/workflows`].
- **Covered** [read]:
  - Init, commit and dimensional diff, branch/checkout, freeze/replay/eval gate, recall ranking.
  - Merge: 18 tests, covering fast-forward, conflicts, reconcile, metric winner, target goal and swarm.
  - The rollback ledger and `log --reasoning`.
  - All five trace providers and the runtime frame.
  - Soul: the Ed25519 RFC 8032 vector, tamper detection, keeping the seed out of the repo.
  - SBT, corporate audit and approvals, plural, dynamics.
  - The UI API, monitor and MCP: `initialize`, `tools/list` and one success/error call.
  - Packaging and the zero-dependency rule.
- **Notable gaps** [read]:
  - No golden test pinning canonical bytes or object ids, which a cross-implementation port needs first.
  - No test that a corrupted or tampered object is detected outside the Soul path, and no fsck.
  - Only 5 core repository tests and 2 crystallize tests. Rollback restoring goal and models is not asserted separately from the tree.
  - No concurrency or locking test: refs and the jsonl ledger have unguarded writes.
  - MCP has 2 tests, and not every tool is called.
  - No test that `replay --exec` reproduces outputs; it only checks that steps are piped.
  - The version mismatch (0.3.0 vs 0.4.0) is not caught.

## 4. Mapping to protocol v0.1

| v0.1 concept / command | Closest existing mechanism | Gap |
|---|---|---|
| HarnessManifest | `agent.json` read in `repository.py:Repository.snapshot`, split into `goal` + `modelpin[]` + `trace` objects referenced by `commit` | No typed dimensions for prompt, sampling (only inside modelpin `params`), tool, adapter, router or config. No per-dimension `content_hash`. No standalone manifest object. |
| manifest_id (BLAKE3 of JCS) | `objects.py:ObjectStore.hash_obj` (SHA-256 of sorted-keys JSON) | Different hash, different canonicalization. |
| parent_ids | `commit.parents` (`Repository.commit`, `merge.merge`) | Exists, but on commits rather than manifests. |
| StepRecord | none. The closest is `trace.messages[]` (raw, unhashed per message) and the aggregate frame from `runtime/frame.py:build_frame` | No run_id, step_index, per-step manifest_id, input/output hashes, per-step tokens/latency, checkpoint_ref or prev_hash. |
| PatchRecord | none. The closest are `diff.py:diff_commits` (computed, not stored) and the merge `--reconcile` bundle | No stored from→to manifest record carrying rationale, evidence, author, applied_at_step or gate_result. |
| GateResult | `eval.py:run_eval` → `.agentvcs/evals/<oid>.json` | Mutable side-table, not content-addressed. It holds command, runs, passed/total, score, ok and tails. |
| RunLedger (hash-chained) | `rollbacks.jsonl` (`Repository.rollback`) and the commit parent chain | jsonl is unchained. The commit DAG is a Merkle chain, but per commit, not per step. |
| `init` | `Repository.init`, `cli.cmd_init` | Close. |
| `snapshot` | `Repository.snapshot` (+ `commit`) | Close, but hashes a whole file tree rather than a typed manifest. |
| `run start/end` | none | – |
| `step record` | none. Traces are vacuumed at commit time by `traces/*.pull` | – |
| `diff` | `diff.py:diff_commits` | Diffs code, goal, models, trace count and state. No semantic diff per typed dimension. |
| `patch propose` | none. `merge --reconcile CMD` is the only external proposer seam | – |
| `patch apply` | `Repository.commit` / `merge.merge` | Unrecorded as a patch. |
| `patch rollback` | `Repository.rollback` | A ref move plus a ledger line, not an inverse patch. |
| `gate run` | `eval.py:run_eval` / `ensure_passing` | Close. Gates whole commits only. |
| `resume --from-step` | none. `replay.py:replay` re-emits crystal steps from step 0 | No checkpoints. |
| `log` | `Repository.log`, `cli._cmd_log_reasoning` | Close. |
| `blame --metric` | none. `dynamics.py:price` attributes trait change to selection vs. within-lineage edits | Aggregate, not per dimension. |
| `bisect` | none | – |
| `freeze` | `crystallize.py:crystallize` | Close: eval-gated, temperature 0 pins. |
| `export audit` | `corporate.py:audit` (corporate repos only), `cli.cmd_verify` | Domain-specific; no generic export. |
| `verify` | `soul.py:verify_commit` (signatures only) | No re-hash and no chain check of objects or ledger. |
| `mcp` | `mcp_server.py` (21 tools) | Transport reusable; tool set must change. |
| store: BLAKE3 content-addressed objects | `objects.py:ObjectStore` (SHA-256, zlib loose objects) | Layout reusable, hash not. |
| store: SQLite index | none | – |

## 5. Keep / discard / defer

**Keep conceptually**
- Content-addressed store with dedupe (`objects.py`). The layout is sound; swap the hash and the canonicalization.
- Dimension-aware diff (`diff.py`). It is the seed of `semantic_diff`.
- Eval as a measurement *about* an object, not part of its identity (`eval.py` docstring). It maps directly to GateResult referencing a manifest.
- The eval-gated freeze with temperature-0 pinning (`crystallize.py`). It is v0.1 `freeze` almost verbatim.
- Rollback that never deletes, with a reason ledger. Upgrade it to a hash-chained PatchRecord.
- Trace providers that vacuum native session logs (`traces/*`). They are the cheapest StepRecord source for existing runtimes.
- The runtime frame (`runtime/frame.py`). Its token, cost and routing extraction is reusable at per-step granularity.
- The stable error codes plus the `--json` / `-C` agent contract (`docs/AGENT_MODE.md`). It is proven to drive agents.
- The zero-dependency, stdlib-only MCP stdio server. Keep the pattern, not the tool list.

**Discard**
- `soul.py`, `_ed25519.py`, `sbt.py`: identity and reputation tokens are not in v0.1. Add signing to the ledger later if needed, using a real crypto crate.
- `plural.py` and `fleet`: they depend on SBT skill profiles and have no v0.1 object.
- `corporate.py`, `audit` and `approve`: a jurisdiction-specific governance layer. `export audit` should be generic.
- `recall.py` (Jaccard over goal text): a retrieval heuristic, not a protocol concern.
- The `crystal/` artifact written into the working tree: it pollutes the next commit's tree hash.

**Defer**
- `dynamics.py` (price, health, infobits, contain): analysis over a ledger that does not exist yet. Revisit once StepRecords and GateResults exist.
- `swarm.py` (sub-agent topology): could become a `router` or `config` dimension, but not in v0.1.
- `merge.py` (three-way merge plus reconcile): v0.1 has no merge command. Branch merge of manifests can come after patches.
- `monitor.py`, `ui/`, `watch`/`statusline`: presentation layers to rebuild over the new index.
- `scaffold.py` (`new`): an adoption aid, cheap to port last.
- `packages/eve` and the vercel-eve, anthropic-managed and odyssey providers: port only the providers a v0.1 conformance fixture needs.

## 6. Where the current implementation diverges from v0.1 (predicted conformance failures)

1. **Hash function.** SHA-256, not BLAKE3, so every id differs [read, ran].
2. **Canonicalization.** Sorted-keys `json.dumps`, not RFC 8785. Integer-valued floats (`1.0`), UTF-16 key ordering and NaN/Infinity handling all differ [ran for `1.0`].
3. **Blob framing.** `b"blob\0"` prefix with no length, which is git-like but not git-compatible, and is unspecified in v0.1 [read].
4. **No HarnessManifest.** Dimensions are goal, models, trace, tree, runtime and swarm. Prompt, sampling, tool, adapter, router and config are not typed, and there is no per-dimension `content_hash` [read].
5. **No per-step manifest stamping.** The trace is one blob per commit, with no `step_index`, `manifest_id`, `prev_hash`, `latency` or `checkpoint_ref` per step [read].
6. **No hash-chained ledger.** `rollbacks.jsonl` and `evals/*.json` are plain, mutable and unchained [read, ran].
7. **No PatchRecord.** Changes exist only as commit-to-commit diffs computed on demand. Rationale, evidence and gate_result are not linked to a patch [read].
8. **Gate granularity.** One shell command per commit, stored outside the object graph, so a GateResult is not content-addressed or referenced from anything [read].
9. **Identity includes volatile fields.** `timestamp`, `author` and `message` are inside the hashed commit, and Soul signatures, when enabled, are embedded in the hashed object [read].
10. **No resume, bisect, blame, run lifecycle or SQLite index** [read].
11. **`verify` checks signatures only.** Objects are never re-hashed on read [read].

Prediction: a v0.1 conformance suite would fail on every id-bearing vector (items 1–3), and on every StepRecord, PatchRecord and RunLedger case (items 4–7). What carries over is the semantics, not the bytes: content addressing, dimensional diff, the eval-gated freeze, non-destructive rollback, provider-based trace capture and the stdio MCP pattern.
