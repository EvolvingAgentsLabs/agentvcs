# Conformance — Rust core with merge (spec v0.2 draft)

**102/102** [ran] on 2026-10-06 — hash 15/15, manifest 13/13, diff 16/16, verify 31/31,
blame 8/8, merge 19/19.

```bash
cargo build --release
python3 conformance/run.py --cli "$PWD/target/release/agentvcs" --out conformance/results/rust-merge-v0.2.jsonl
```

- `rust-merge-v0.2.jsonl` is the run of `target/release/agentvcs` built with the
  machine's default toolchain (`x86_64-apple-darwin`, under Rosetta on an Apple M4).
  The SDK's `python -m agentvcs` (native `aarch64-apple-darwin` build, `dev.sh`) was
  run through the same suite the same day: also 102/102.
- No golden was edited. Where the spec is silent or its reference generator
  (`tools/ref.py`) reads it differently from its text, the choice is recorded in
  [ADR-0008](../../docs/adr/0008-merge.md); none of those cases is covered by a golden.
