# Conformance — Rust core 0.1.0

**83/83** [ran] on 2026-10-06 — hash 15/15, manifest 13/13, diff 16/16, verify 31/31, blame 8/8.

```bash
cargo build --release
python3 conformance/run.py --cli "$PWD/target/release/agentvcs" --out conformance/results/rust-0.1.0.jsonl
```

- `rust-0.1.0.jsonl` (one line per case) is the run of `target/release/agentvcs` built
  with the machine's default toolchain (`x86_64-apple-darwin`, under Rosetta on an
  Apple M4). The native `aarch64-apple-darwin` build was run through the same suite
  the same day: also 83/83.
- No golden was edited. One spec bug surfaced outside the suite (canonical form of
  doubles ≥ 2^53 is not re-parseable under §1's integer rule):
  [ADR-0006 §1](../../docs/adr/0006-f1-implementation-notes.md).
- CI (`.github/workflows/rust.yml`) reruns the suite on macos-14 (arm64) and
  ubuntu-latest (x86_64).
