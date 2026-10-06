# ADR-0004 — Local-first store

- Status: accepted (2026-10-06)

## Decision

- The store is `.agentvcs/` inside the project. No server.
- Objects are content-addressed with BLAKE3 over their canonical bytes (RFC 8785
  for JSON, raw bytes for blobs). Identifiers are written `b3:<64 lowercase hex>`.
- Each run's ledger is append-only and hash-chained: every entry carries the
  `entry_hash` of the previous one.
- A SQLite index accelerates lookups; it is derived data and can be rebuilt from
  objects and ledgers. Nothing is true only in the index.
- Remotes, sync and multi-user access are out of scope (`LATER.md`).

## Consequences

- BLAKE3 is not in the Python standard library, so the current stdlib-only
  implementation (SHA-256 over `json.dumps(sort_keys=True)` today, `src/agentvcs/objects.py:25`) cannot produce v0.1 ids
  without a dependency. That divergence is recorded in the conformance result
  rather than papered over.
