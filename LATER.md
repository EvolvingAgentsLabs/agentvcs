# LATER

Ideas that came up and are not in the revival plan. One line of motive each.
Nothing here is implemented until it moves into the plan.

- **lora-kernel integration** (adapters as a hot-swappable dimension) — Phase 7, after Gate F3, on a frozen lora-kernel base.
- **Remotes, sync, multi-user store** — ADR-0004 keeps v0.1 local-first.
- **Supervisor web dashboard** — not needed for E2.
- **Pricing, commercial landing, service brand** — after F3 says there is a product.
- **FSL licence for the supervisor** — evaluate by ADR later.
- **LangSmith / Langfuse / W&B integrations** — consumers of the ledger, not v0.1.
- **Pointer from `evolving-agents/packages/agentvcs` to this repo** — the monorepo copy now diverges (2026-10-06); out of this plan's scope.
- **Version skew 0.3.0 (pyproject) vs 0.4.0 (`__version__`)** — moot once Rust replaces the package; fix only if a Python release happens first.
- **Manifest merge semantics** — v0.1 represents multiple parents but defines no merge.
- **Bisect golden cases** — need the toy pipeline's hooks (Gate F2).
- **Concurrent writers on one run** — v0.1 refuses a stale writer but takes no lock; add an advisory lock if two processes ever share a run.
- **`blob put` command** — steps reference blobs by hash; the store has `put_blob` but no CLI verb yet (the SDK in Phase 2 needs it).
- **Spec fix for large-double canonical form** — ADR-0006 §1; needs a spec revision and a golden case once accepted.
- **Native arm64 Rust toolchain on the dev Mac** — the default rustup here is x86_64 under Rosetta; benchmarks used the aarch64 target.
