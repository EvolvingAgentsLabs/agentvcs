# agentvcs protocol v0.1

Status: **draft for review** (Gate F0). Protocol tag: `agentvcs/0.1`.

This document is normative. Where it and an implementation disagree, the
implementation is wrong. Where it and a golden case in `conformance/` disagree,
the spec is fixed first and the case regenerated in the same commit.

The protocol has five objects:

| Object | What it is | Schema |
|---|---|---|
| `HarnessManifest` | a complete snapshot of an agent system's configuration | `schemas/harness_manifest.schema.json` |
| `StepRecord` | one execution step, stamped with the manifest that produced it | `schemas/ledger_entry.schema.json` (`kind: "step"`) |
| `PatchRecord` | a change applied to a running system | `schemas/ledger_entry.schema.json` (`kind: "patch"`) |
| `GateResult` | the eval gate a patch passed (or did not) | `schemas/gate_result.schema.json` |
| `RunLedger` | the hash-chained sequence of one run's entries | `schemas/ledger_entry.schema.json`, `schemas/audit_bundle.schema.json` |

Semantic diff rules are in [`SEMANTIC_DIFF.md`](SEMANTIC_DIFF.md), ledger
verification in [`LEDGER.md`](LEDGER.md), blame in [`BLAME.md`](BLAME.md), the CLI
contract in [`cli/COMMANDS.md`](cli/COMMANDS.md).

---

## 1. Canonical form and hashing

- **Canonical JSON** is RFC 8785 (JCS): object keys sorted by UTF-16 code units,
  no insignificant whitespace, strings escaped minimally (`"`, `\`, and control
  characters below U+0020 — `\b \t \n \f \r` by name, the rest as `\u00xx` with
  lowercase hex), numbers serialized as ECMAScript `Number.prototype.toString`.
- **Numbers are IEEE-754 doubles.** An integer literal with magnitude above
  2^53 − 1 is invalid (`E_CANONICAL`) rather than silently rounded — a rounded
  `seed` inside a hash is a bug nobody would see — **unless the literal is exactly
  the canonical form of the double nearest to it** (e.g. `100000000000000000000`,
  which is how `1e20` canonicalizes). Without that exception canonical bytes could
  not be read back (ADR-0006 §1). `NaN` and infinities are invalid
  anywhere in the protocol.
  `1` and `1.0` are the same value and canonicalize to `1`.
- **Strings** must be valid Unicode. Lone surrogates are invalid.
- **Hash** is BLAKE3-256 over the canonical UTF-8 bytes (JSON) or the raw bytes
  (blobs). It is written `b3:` followed by 64 lowercase hex digits.
- `hash(x)` below means `"b3:" + hex(BLAKE3(JCS(x)))`.

## 2. HarnessManifest

```json
{
  "protocol": "agentvcs/0.1",
  "type": "harness_manifest",
  "name": "due-diligence v3",
  "parent_ids": ["b3:…"],
  "dimensions": {
    "extract.prompt":   {"kind": "prompt",   "content": {"template": "…", "variables": ["clause"]}, "content_hash": "b3:…"},
    "extract.model":    {"kind": "model",    "content": {"provider": "llama.cpp", "id": "gemma-4-12b", "quantization": "Q4_K_M"}, "content_hash": "b3:…"},
    "extract.sampling": {"kind": "sampling", "content": {"temperature": 0.2, "max_tokens": 512, "grammar": null}, "content_hash": "b3:…"}
  },
  "manifest_id": "b3:…"
}
```

- **Dimension names** match `^[a-z0-9][a-z0-9_.\-/]*$` and are unique by
  construction (object keys).
- **`content_hash`** = `hash(content)`. It may be omitted in the authoring form; an
  implementation computes it on `snapshot`. If present and wrong, the manifest is
  invalid (`E_CONTENT_HASH`).
- **`manifest_id`** = `hash({"protocol": …, "dimensions": D'})` where `D'` is
  `dimensions` with every `content_hash` filled in. `name` and `parent_ids` are
  annotations and are **not** part of the id (ADR-0005). If present and wrong, the
  manifest is invalid (`E_MANIFEST_ID`).
- A manifest with zero dimensions is valid.
- Validation order, so every implementation reports the same first error:
  canonicalizable input (`E_CANONICAL`), `protocol` (`E_PROTOCOL_VERSION`),
  each dimension's `kind` (`E_UNKNOWN_KIND`), schema (`E_SCHEMA`), content hashes
  (`E_CONTENT_HASH`), `manifest_id` (`E_MANIFEST_ID`).

### 2.1 Dimension kinds and their `content`

| kind | required content fields | notes |
|---|---|---|
| `prompt` | `template` (string) | `variables` (array of unique strings, default `[]`); any other fields allowed |
| `model` | `provider`, `id` (strings) | `quantization`, `revision` optional |
| `sampling` | — | `temperature`, `top_p`, `top_k`, `min_p`, `max_tokens`, `seed`, `stop`, `grammar` (GBNF text or `null`), any others |
| `tool` | `name` (string), `signature` (object, JSON Schema of the arguments), `code_hash` (`b3:…`) | the code itself lives in the store as a blob |
| `adapter` | `adapter_id` (string), `weights_hash` (`b3:…`) | weights are never inlined or diffed |
| `router` | — | free object: rules or a model reference |
| `config` | — | free object; may carry `schema` (a JSON Schema the user validates against) |

An unknown `kind` is invalid (`E_UNKNOWN_KIND`). Extending the set of kinds bumps
the protocol version.

## 3. Ledger entries

A run's ledger is a sequence of entries. Every entry has this envelope:

```json
{
  "protocol": "agentvcs/0.1",
  "type": "ledger_entry",
  "run_id": "run-2026-10-06-a",
  "seq": 0,
  "prev_hash": null,
  "kind": "run_start",
  "body": { … },
  "entry_hash": "b3:…"
}
```

- `seq` is the 0-based position in the ledger.
- `prev_hash` is `null` for `seq == 0` and the previous entry's `entry_hash`
  otherwise.
- `entry_hash` = `hash(entry without "entry_hash")`.
- `run_id` is a string chosen by the creator, identical across a ledger.

### 3.1 `kind: "run_start"`

```json
{"manifest_id": "b3:…", "started_at": "2026-10-06T12:00:00Z", "parent": null}
```

`parent` is `null` or `{"run_id": "…", "from_step": n, "checkpoint_ref": "…"}` when
the run was created by `resume`. A resumed run's first step has
`step_index == from_step`.

### 3.2 `kind: "step"` — StepRecord

```json
{
  "step_index": 0,
  "manifest_id": "b3:…",
  "agent_id": "extractor",
  "inputs":  ["b3:…"],
  "outputs": ["b3:…"],
  "started_at": "…", "ended_at": "…",
  "tokens": {"in": 812, "out": 133},
  "latency_ms": 1840,
  "metrics": {"f1.indemnification": 0.5},
  "checkpoint_ref": null
}
```

- `inputs`/`outputs` are hashes of blobs in the store; the ledger never inlines them.
- `metrics` is optional; values are numbers. `blame` reads them.
- `checkpoint_ref` is opaque to agentvcs: a pointer the harness's `checkpoint`
  hook produced and its `restore` hook can consume (e.g. serialized KV state).

### 3.3 `kind: "patch"` — PatchRecord

```json
{
  "patch_id": "b3:…",
  "from_manifest": "b3:…",
  "to_manifest": "b3:…",
  "semantic_diff": [ … SEMANTIC_DIFF.md changes … ],
  "rationale": "extraction prompt never asks for the cap amount",
  "evidence": [12, 13, 17],
  "author": {"type": "agent", "id": "supervisor-v0"},
  "applied_at_step": 18,
  "rollback_of": null,
  "gate_result": { … GateResult … }
}
```

- `patch_id` = `hash({"protocol", "from_manifest", "to_manifest", "rationale",
  "evidence", "author", "rollback_of"})` — the proposal, not its application.
- `evidence` are step indexes of this run.
- `applied_at_step` is the `step_index` of the first step that runs under
  `to_manifest`.
- `rollback_of` is `null`, or the `patch_id` of an earlier patch in the same ledger
  that this one reverts. A rollback has `from_manifest` = the reverted patch's
  `to_manifest` and `to_manifest` = its `from_manifest`. Rollbacks are exempt from
  the gate requirement (`gate_result` may be `null`): the safety policy must be
  able to retreat without asking permission.

### 3.4 GateResult

```json
{
  "suite": "cuad-smoke",
  "suite_hash": "b3:…",
  "metrics": {"f1.macro": 0.71},
  "thresholds": {"f1.macro": {"op": ">=", "value": 0.65}},
  "passed": true,
  "evidence": ["b3:…"]
}
```

`passed` must equal the conjunction of every threshold evaluated on `metrics`
(`op` ∈ `>= > <= < ==`). A threshold whose metric is missing evaluates false.
A gate with no thresholds has `passed: false` — an empty gate gates nothing.

### 3.5 `kind: "run_end"`

```json
{"ended_at": "…", "status": "completed"}
```

`status` ∈ `completed`, `aborted`, `failed`. A ledger without `run_end` is an
open run and is valid.

## 4. Audit bundle

`export audit` writes, and `verify` / `blame` read, one JSON file:

```json
{
  "protocol": "agentvcs/0.1",
  "type": "audit_bundle",
  "run_id": "…",
  "manifests": {"b3:…": { HarnessManifest }, …},
  "ledger": [ entry, entry, … ]
}
```

`manifests` must contain every manifest the ledger references.

## 5. What v0.1 leaves out

- `bisect` re-executes from checkpoints through harness hooks; its CLI shape is in
  `cli/COMMANDS.md`, but it has no golden cases in v0.1 because its result depends
  on the harness. Its cases arrive with the toy pipeline (Gate F2).
- Merges of manifests (more than one parent) are representable but have no merge
  semantics yet.
- Remotes, signatures, multi-user stores: `LATER.md`.
