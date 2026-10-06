# ADR-0002 — Protocol first

- Status: accepted (2026-10-06)

## Decision

The asset is the protocol — `HarnessManifest`, `StepRecord`, `PatchRecord`,
`GateResult`, `RunLedger` — not the implementation. The spec lives in `spec/` as
JSON Schema plus prose rules, and is versioned (`protocol: "agentvcs/0.1"` in
every object). Any harness can emit a conforming ledger without our code; the
`verify` command checks a ledger file regardless of who wrote it.

## Consequences

- Every behaviour a consumer can observe (ids, diffs, verification verdicts,
  blame segments) is pinned by a golden case before an implementation exists.
- Changes to object shapes bump the protocol version; implementations must
  reject versions they do not know (`E_PROTOCOL_VERSION`).
- `agentvcs-supervisor` and `agentvcs-bench` are consumers of the protocol and
  never extend it privately.
