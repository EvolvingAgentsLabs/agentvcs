# ADR-0005 — A manifest's identity is what runs, not how it was reached

- Status: proposed (2026-10-06) — needs Matias's review with the spec

## Context

The plan gives `HarnessManifest` a `parent_ids` field (zero, one or more parents).
Git hashes parents into a commit's id. If agentvcs did the same, two runs of the
same harness reached by different paths — including a rollback that restores the
exact previous configuration — would carry different `manifest_id`s.

## Decision

`manifest_id` = BLAKE3 over the canonical form of `{protocol, dimensions}` only.
`name` and `parent_ids` are annotations, stored with the manifest but excluded
from its id. Lineage is carried by `PatchRecord` (`from_manifest` → `to_manifest`),
which is where it is needed for attribution.

## Consequences

- `blame` groups steps by what actually executed: a rollback returns to the same
  id, so the steps before the patch and after the rollback land on the same
  manifest and are directly comparable.
- Two manifests with identical dimensions but different `parent_ids` are the
  same object. The store does not merge their annotations:
  the first stored annotation wins and is informational only.
- Merge history is reconstructed from patch records, not from manifests.
