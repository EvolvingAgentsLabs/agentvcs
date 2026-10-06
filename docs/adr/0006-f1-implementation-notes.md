# ADR-0006 — F1 implementation notes: ambiguities resolved and one spec bug

- Status: accepted (2026-10-06) — §1 folded into spec/PROTOCOL.md §1 (2026-10-06) — needs Matias's review together with the spec
- Context: Phase 1 (Rust core, CLI, MCP). The spec is normative; where it was
  silent the Rust implementation chose as below. No golden case was changed.

## 1. Spec bug: the canonical form of a large double is not re-parseable

`PROTOCOL.md §1` says an integer literal above 2^53 − 1 is `E_CANONICAL`. But the
JCS serialization of a large double *is* an integer literal: `1e20` canonicalizes
to `100000000000000000000` (golden `hash-005`), `2.9514790517935283e20` to
`295147905179352830000` (golden `hash-008`). Read back under the rule as written,
canonical bytes are refused — so a ledger line whose metric is `1e20`, written
canonically, cannot be re-read, and `canon(parse(canon(x))) == canon(x)` fails.
The property test found it on the first run (`5.48562758454321e16`).
`conformance/tools/ref.py` has the same behaviour (`_num` rejects any Python
`int` above 2^53 − 1).

**What the implementation does** (`crates/agentvcs-core/src/json.rs`, `Mode`):

- *Input* (`hash --canonical`, `snapshot`, `verify`/`blame` bundle files, stdin
  bodies) is parsed `Strict`: exactly the spec's rule. All 83 goldens pass.
- *Bytes we wrote ourselves* (objects, `runs/*.jsonl`, manifests in the store) are
  read with `Mode::CanonicalForm`: an integer literal above 2^53 − 1 is also
  accepted **iff it is exactly the JCS serialization of the double nearest to it**.
  `9007199254740993` is still refused (it would be silently rounded).
- `export audit` writes bundles with ordinary JSON float syntax (`1e20` stays
  `1e20`), so exported bundles re-parse strictly and verify.

**Proposed spec fix:** replace the rule with "an integer literal with magnitude
above 2^53 − 1 is invalid unless it is the canonical serialization of a double"
(the `CanonicalForm` rule). It keeps hash-015 failing, keeps every other golden
unchanged, and makes the canonical form closed under parsing. Test:
`canonical_form_of_large_doubles_is_not_strictly_reparseable` documents the bug.

## 2. Bundle schema vs. per-manifest checks in `verify`

`audit_bundle.schema.json` `$ref`s the manifest schema, which contains the
`protocol` const and the `kind` enum — so a literal reading would report a
manifest with an unknown kind as bundle-level `E_SCHEMA`, contradicting
`LEDGER.md` step 2 (which lists `E_UNKNOWN_KIND` per manifest). Resolved: step 1
checks only the bundle's own shape (required keys, `type`, `run_id` string,
`manifests` object, `ledger` array); each manifest goes through the full manifest
validation order in step 2, reported with its key. Likewise the entry schema
check in step 3 omits the `protocol` const, which has its own code (check 2).

A bundle that is not JSON at all is an *input* error (exit 3, `E_SCHEMA` /
`E_CANONICAL`); a bundle that is JSON but fails step 1 is a *verdict*
(`valid: false`, violation `{"code": "E_SCHEMA", "seq": null}`, exit 1).

## 3. Error codes and exit codes not in EXIT_CODES.md

| code | exit | when |
|---|---|---|
| `E_STEP_INDEX`, `E_STEP_MANIFEST`, `E_PATCH_FROM`, `E_PATCH_STEP`, `E_PATCH_NOOP`, `E_PATCH_ID`, `E_ROLLBACK_UNKNOWN`, `E_AFTER_RUN_END`, `E_FIRST_NOT_RUN_START` | 3 | the writer refuses an entry `verify` would flag — the store never holds a ledger that does not verify (gate aside, which is exit 5) |
| `E_GATE_COMMAND` | 3 | the suite's command (or bisect's `--exec`) exited non-zero or printed no JSON metrics. Not recorded as a failed gate: infrastructure failure is not evidence against the patch |
| `E_STALE_STATE` | 3 | a library caller appended with a writer state behind the ledger on disk |
| `E_RUN_EXISTS`, `E_IO`, `E_INDEX` | 4 | store errors |
| `E_EXISTS` | 2 | `export audit -o` onto an existing file without `--yes` (the one destructive operation in v0.1) |

A missing input file is `E_NOT_FOUND` (exit 4).

## 4. Diff: kind change with equal content

`SEMANTIC_DIFF.md` says a dimension with equal `content_hash` on both sides
produces no change. If the *kind* differs, the manifest ids differ, and `identical`
must be false iff `from != to`. Resolved as `ref.py` does: a kind change is always
reported as `kind_changed`, even with equal content.

## 5. Command details the spec leaves open

- `step record` fills `step_index`, `manifest_id` and `checkpoint_ref` (null) when
  absent and refuses them when present and wrong. Output adds `step_index`.
- `run start --manifest` and `patch propose --to` take an id or a manifest file
  (the file is snapshotted). Run ids must match `[A-Za-z0-9._-]+` (they are file
  names); default ids are generated.
- `patch propose`: `--evidence` optional (default `[]`), `--author` default
  `human:cli`. The proposal is stored in `.agentvcs/patches/<hex>.json`, a mutable
  record (the gate result is attached later) — not a content-addressed object.
- `gate run`: suite = YAML/JSON with `command` (run with `sh -c` in the project
  directory), `thresholds` (`{metric: {op, value}}`) and optional `name` (default:
  file stem). Env: `AGENTVCS_PATCH`, `AGENTVCS_RUN`, `AGENTVCS_FROM_MANIFEST`,
  `AGENTVCS_TO_MANIFEST` (= `AGENTVCS_MANIFEST`), `AGENTVCS_MANIFEST_FILE`,
  `AGENTVCS_STORE`. Stdout is `{"metrics": {…}}` or a flat object of numbers.
  `suite_hash` = hash of the parsed suite; `evidence` = id of the stored stdout.
  Exit 1 when the gate does not pass.
- `patch apply --at-step` is optional (default: the run's next step); a wrong value
  is `E_PATCH_STEP`.
- `patch rollback` requires the patch to have been applied in its run and the run
  to be on its `to_manifest`; rationale default `rollback of <id>`.
- `resume --from-step n`: the child's `checkpoint_ref` is that of the parent's step
  `n − 1` (the state *after* the last step that is not re-executed); `null` for
  `n == 0`. `n` must lie in `[first step, next step]` of the parent.
- `freeze` looks for a stored patch whose gate passed and whose `to_manifest` is
  the manifest (through the index, which `rebuild_index` regenerates from files).
- `export audit` without `-o` returns the bundle inline under `bundle`.
- `bisect`: candidates are `M0` (run_start manifest) and each patch's
  `to_manifest`, in ledger order; monotonicity is assumed (like git bisect);
  probes are cached per manifest. Env for `--exec`: `AGENTVCS_RUN`,
  `AGENTVCS_MANIFEST`, `AGENTVCS_MANIFEST_FILE`, `AGENTVCS_FROM_STEP` (the first
  patch's `applied_at_step`), `AGENTVCS_CHECKPOINT_REF` (of the step before it, or
  empty), `AGENTVCS_METRIC`, `AGENTVCS_STORE`. Stdout: a JSON number or an object
  carrying the metric. Output adds `reason` when an endpoint check ends the search.
- Duplicate keys in input JSON: last wins (as Python's `json`).
- Ledger appends are not fsynced unless `AGENTVCS_FSYNC` is set; single writer per
  run is assumed (a stale writer is refused, concurrent writers are not locked —
  `LATER.md`).
