# LATER

Ideas that came up and are not in the revival plan. One line of motive each.
Nothing here is implemented until it moves into the plan.

- **lora-kernel integration** (adapters as a hot-swappable dimension) — Phase 7, after Gate F3, on a frozen lora-kernel base.
- **Remotes, sync, multi-user store** — ADR-0004 keeps v0.1 local-first.
- **Supervisor web dashboard** — not needed for E2.
- **Pricing, commercial landing, service brand** — after F3 says there is a product.
- **FSL licence for the supervisor** — evaluate by ADR later.
- **LangSmith / Langfuse / W&B integrations** — consumers of the ledger, not v0.1.
- **Version skew 0.3.0 (pyproject) vs 0.4.0 (`__version__`)** — moot once Rust replaces the package; fix only if a Python release happens first.
- **Bisect golden cases** — need the toy pipeline's hooks (Gate F2). The Phase 2 toy pipeline records `checkpoint_ref`s but does not yet implement a `bisect --exec` probe.
- **Legacy distribution rename** — at the `legacy/` move, rename the root distribution to `agentvcs-legacy` and point `release.yml` at the SDK wheel (ADR-0007 §2).
- **Async SDK API** — `async with avcs.run(...)`; not needed by the toy pipeline.
- **`blob put` command** — steps reference blobs by hash; the store has `put_blob` but no CLI verb yet (the Phase 2 SDK calls `put_blob` natively; a CLI-only harness still needs the verb).
- **Spec fix for large-double canonical form** — ADR-0006 §1; needs a spec revision and a golden case once accepted.
- **Native arm64 Rust toolchain on the dev Mac** — the default rustup here is x86_64 under Rosetta; benchmarks used the aarch64 target and `crates/agentvcs-py/dev.sh` builds with `--target aarch64-apple-darwin`. Switching the default toolchain is the owner's call (it affects other projects on the machine).
