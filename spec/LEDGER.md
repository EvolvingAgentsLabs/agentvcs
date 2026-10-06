# Ledger verification (v0.1)

`verify` takes an audit bundle and returns

```json
{"ok": true, "valid": false, "entries": 7, "open": true,
 "violations": [{"code": "E_PREV_HASH", "seq": 3}]}
```

- `violations` is in the order found. Conformance compares **the first violation
  only** (code and `seq`, or `manifest_id` for manifest-level violations):
  after the first break, what an implementation reports is not specified.
- `open` is `true` when the ledger has no `run_end`.

## Order of checks

1. **Bundle.** Bundle fails its schema → `E_SCHEMA` (seq `null`). Unknown
   `protocol` → `E_PROTOCOL_VERSION`.
2. **Manifests**, in key order of `manifests`: each one's `content_hash` values
   (`E_CONTENT_HASH`), its `manifest_id` (`E_MANIFEST_ID`), and its key equal to
   its `manifest_id` (`E_MANIFEST_KEY`). Unknown kinds: `E_UNKNOWN_KIND`.
3. **Entries**, in ledger order. For the entry at position `i`:

| # | check | code |
|---|---|---|
| 1 | entry matches its schema | `E_SCHEMA` |
| 2 | `protocol` is `agentvcs/0.1` | `E_PROTOCOL_VERSION` |
| 3 | `run_id` equals the bundle's `run_id` | `E_RUN_ID` |
| 4 | `seq == i` | `E_SEQ` |
| 5 | `prev_hash` is `null` at `i == 0`, else the previous `entry_hash` | `E_PREV_HASH` |
| 6 | `entry_hash` recomputes | `E_ENTRY_HASH` |
| 7 | `i == 0` ⇔ `kind == "run_start"` | `E_FIRST_NOT_RUN_START` / `E_DUPLICATE_RUN_START` |
| 8 | no entry after a `run_end` | `E_AFTER_RUN_END` |
| 9 | every manifest id the entry names is in the bundle | `E_UNKNOWN_MANIFEST` |
| 10 | kind-specific checks below | |

**Step.** `step_index` equals the expected next index (`0`, or the parent's
`from_step` for a resumed run, then +1 per step) → `E_STEP_INDEX`.
`manifest_id` equals the active manifest → `E_STEP_MANIFEST`.

**Patch**, in this order:
- `from_manifest` differs from `to_manifest` → `E_PATCH_NOOP` (a patch that changes
  nothing would split a blame segment for no reason);
- `patch_id` recomputes → `E_PATCH_ID`;
- `from_manifest` equals the active manifest → `E_PATCH_FROM`;
- `applied_at_step` equals the expected next step index → `E_PATCH_STEP`;
- if `rollback_of` is set: it names an earlier patch in this ledger
  (`E_ROLLBACK_UNKNOWN`) and swaps that patch's manifests (`E_ROLLBACK_TARGET`);
- otherwise `gate_result` is present and `passed` (`E_PATCH_UNGATED`);
- when `gate_result` is present, `passed` equals its thresholds evaluated on its
  metrics (`E_GATE_INCONSISTENT`);
- `semantic_diff` equals `diff(from_manifest, to_manifest).changes` in its
  normative fields (`E_PATCH_DIFF`).

After a valid patch, the active manifest is `to_manifest`. The active manifest
starts as `run_start.body.manifest_id`.
