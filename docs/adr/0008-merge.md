# ADR-0008 — Merge (spec v0.2 draft): where it lives, and what the spec left open

- Status: proposed (2026-10-06) — needs Matias's review together with `spec/MERGE.md`
- Context: `spec/MERGE.md` (v0.2 draft) adds a three-way manifest merge whose
  conflicts are resolved by an agent with the evidence a run observed. The spec,
  `spec/cli/COMMANDS.md` (merge rows), 19 goldens (`conformance/cases/merge-*`) and
  `conformance/tools/ref.py` (`merge_prepare`, `merge_commit`) are the contract.
  No golden was changed; the Rust CLI passes 102/102.

## 1. A new crate, `agentvcs-merge`

Evidence needs `blame` and `verify` (`agentvcs-query`), and `agentvcs-query`
already depends on `agentvcs-diff` — so merge cannot be a module of
`agentvcs-diff` without a dependency cycle, and putting it in `agentvcs-query`
would make the ledger-query crate own a manifest operation. `agentvcs-merge`
depends on core, diff and query and holds only pure functions:

- `prepare(base, ours, theirs, ours_run, theirs_run, metrics) -> Prepared`
- `commit(base, ours, theirs, resolution) -> Committed { merged, record }` —
  the record with `gate: null`
- `merge_id`, `record_id`, `resolution_ok`

It never touches a store and never runs a command. `agentvcs-cli` loads inputs
(ids or files, runs by id or audit-bundle path, as `verify`/`blame` do), stores
the manifests and the record, and runs the suite. MCP tools (`merge_prepare`,
`merge_commit`) come from the command table like every other tool, so their JSON
is the CLI's byte for byte. The Python SDK's `merge_prepare` / `merge_commit` are
argv builders over the in-process CLI (ADR-0007: no logic in Python).

## 2. Ambiguities, and what the implementation chose

None of these is exercised by a golden; each has a unit test in
`crates/agentvcs-merge/tests/unit.rs`.

1. **A kind change with equal content.** §1 compares `content_hash` and adds that
   "a kind change counts as a content change (it changes the hash)". The
   parenthesis is false when the content is equal (`config {"x":1}` →
   `router {"x":1}` has the same `content_hash`); `ref.py` compares the hash only
   and would call that dimension `same`. The implementation follows the sentence,
   not the parenthesis: a side is identified by `(kind, content_hash)`, so a kind
   change is always a change — the same resolution as ADR-0006 §4 for `diff`, and
   consistent with the manifest id, which includes the kind. **Proposed spec fix:**
   "with `b`, `o`, `t` the `(kind, content_hash)` of `d` on each side".
2. **Check order of `merge commit`.** The spec's table checks every `take` before
   any `content`; `ref.py` walks dimensions in order and checks each one's `take`
   or `content` in turn. They differ only when one resolution has a bad `take` and
   a dimension sorted before it has invalid content. The spec wins: all
   `E_MERGE_TAKE` first, then `E_UNKNOWN_KIND` / `E_SCHEMA` per dimension in
   code-unit order.
3. **The resolution's schema** (no schema file exists). `E_SCHEMA` when: not an
   object; a key other than `protocol, type, merge_id, resolutions, rationale,
   author`, or one of them missing; `type != "merge_resolution"`; `merge_id` not a
   hash; `rationale` not a string; `author` not `{type: human|agent, id}`; a
   resolution that is not exactly `{take}` with `take ∈ {ours, theirs, base,
   delete}` or exactly `{content, kind}` with a string `kind`. A `protocol` other
   than `agentvcs/0.1` is `E_PROTOCOL_VERSION`, right after the schema, as for
   manifests. `ref.py` is looser on two points that only reorder errors: an
   unknown `take` value is `E_MERGE_TAKE` there (after the staleness check), and it
   does not check `protocol`, `merge_id`'s form or `author`'s shape.
4. **Content validation** uses the same per-kind constraints as manifests
   (`schema::content_ok`, PROTOCOL §2.1). `ref.py` checks required keys only, so
   e.g. `sampling {"temperature": "hot"}` passes there and is `E_SCHEMA` here. The
   spec says "validate as their kind (spec/PROTOCOL.md §2.1)"; the stricter check
   is the spec's. Content that cannot be canonicalized is `E_CANONICAL`.
5. **Evidence from a ledger that does not verify** is refused with
   `E_INVALID_LEDGER` (exit 3), as `blame` and `bisect` refuse it. The spec is
   silent; `ref.py` would list the patches anyway and give every `blame` delta as
   `null` when `--metric` is passed (and not look at validity at all without it).
   Evidence is "what the runtime observed"; a ledger whose chain does not verify is
   not that. The bundle is checked even when there are no conflicts.
6. **Joint attribution.** `blame` delta is the `delta` of the one attribution
   whose `patches` are exactly `[patch_id]`; a patch attributed together with
   others, a metric absent from the segments, or a patch with no step after it
   gives `null`. Repeated `--metric` names are counted once.
7. **The gate in the output and the record** is the full `gate_result` object
   (`suite, suite_hash, metrics, thresholds, passed, evidence`) — a superset of
   the spec's `{"passed", "metrics"}`, and the same object `gate run` returns. The
   record is stored with it, so `record = hash(merge record with its gate)`.
8. **Suite environment** (`merge commit --suite`): `AGENTVCS_MANIFEST_FILE` (the
   merged manifest's file in the store), `AGENTVCS_FROM_MANIFEST` (= ours),
   `AGENTVCS_TO_MANIFEST` and `AGENTVCS_MANIFEST` (= merged), `AGENTVCS_STORE`,
   plus `AGENTVCS_MERGE_ID`. Like `gate run`, a suite command that exits non-zero
   or prints no JSON is `E_GATE_COMMAND` (exit 3) and **no record is stored** —
   infrastructure failure is not a rejected merge (ADR-0006 §3). A gate that runs
   and does not pass is exit 1 with the record stored.
9. **What `merge commit` stores:** the merged manifest first, then base, ours and
   theirs (so a later `patch propose --from <ours>` finds them). If the merged id
   equals a stored manifest's id — e.g. `take: ours` on the only conflict gives
   `merged == ours`, since `parent_ids` is an annotation outside the id — the
   first stored annotation wins (ADR-0005) and the store's copy may not carry
   `parent_ids`. The merge record always carries the lineage.
10. **A merge gate does not count for `freeze`.** `freeze` still requires a passed
    *patch* gate naming the manifest; applying the merge to a run (§5 of the spec)
    produces one. Whether a merge gate should be enough is left for the spec.
11. **Repeatable flags.** `--metric` is the CLI's first repeatable flag: the
    command table gained `multi`; over MCP it is an array (a single string is also
    accepted). Every other flag still refuses being given twice.

## 3. Verification

- `crates/agentvcs-merge/tests/goldens.rs`: the 19 merge goldens in-process.
- `crates/agentvcs-cli/tests/merge.rs`: two lines diverge from a base, ours
  through a gated patch in run `r1`; `merge prepare --ours-run r1` (and the
  exported bundle) lists that patch with its gate and blame delta; a failing
  `--suite` exits 1 with the record stored; a synthesised resolution commits with
  a suite that reads `AGENTVCS_MANIFEST_FILE`; the merged manifest is applied to
  `r1` as a patch whose rationale cites `merge:<record>`; `verify` is clean and
  `blame` attributes the last segment to that patch.
- `crates/agentvcs-cli/tests/mcp_stdio.rs`: `merge_prepare` / `merge_commit` over
  stdio return the CLI's JSON byte for byte.
- `crates/agentvcs-py/tests/test_merge.py`: the SDK wrappers.
