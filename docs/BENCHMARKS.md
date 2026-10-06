# Benchmarks — Rust core v0.1 (Gate F1 item 4)

Instrument: `crates/agentvcs-cli/examples/bench.rs`, release build, wall-clock
`Instant` per call. Reproduce:

```bash
cargo run --release -p agentvcs-cli --example bench -- "$PWD/target/release/agentvcs"
```

## Machine

Apple M4 (10 cores), 16 GB, macOS 15.7.9, rustc 1.95.0, native
`aarch64-apple-darwin` build. (The local default toolchain on this machine is
`x86_64-apple-darwin` running under Rosetta; the numbers below come from the
native arm64 target, added with `rustup target add aarch64-apple-darwin`.)
Other sessions were using the machine; that is visible in run 1's spawn baseline.

## Results [ran], 2026-10-06, two runs

| measurement | target | run 1 | run 2 | verdict |
|---|---|---|---|---|
| `step record`, library path (store held open; 10,000 steps) | p99 < 2 ms | p50 0.072 / **p99 0.732** / max 6.1 ms | p50 0.065 / **p99 0.178** / max 0.95 ms | **meets** |
| process spawn alone (`/usr/bin/true`, 500×) | — | p50 6.0 / p99 16.2 ms | p50 0.85 / p99 1.58 ms | baseline |
| `step record`, CLI (one process per step, 500×) | p99 < 2 ms | p50 2.07 / **p99 7.79** ms | p50 1.95 / **p99 5.66** ms | **does not meet** |
| `verify`, 100,000-step ledger (72.3 MB bundle), library parse + verify | < 5 s | **0.677 s** | **0.662 s** | **meets** |
| `verify`, same bundle through the CLI | < 5 s | **1.075 s** | **1.336 s** | **meets** |

## Reading

- **The 2 ms `step record` target is met by the library/SDK path, not by the CLI.**
  Spawning a process that does nothing already costs ~0.85 ms p50 / ~1.6 ms p99 on
  a quiet machine (and far more on a loaded one), and a CLI invocation adds
  opening the store, the SQLite index and reading the ledger tail. The CLI's p50
  is ~2 ms and its p99 5–8 ms. A harness on the hot path should use the in-process
  path (`agentvcs_cli::commands::record_step`, exposed to Python as
  `agentvcs_py.step_record`), or a long-lived process (`agentvcs mcp`).
- Library-path cost per step: read the ledger tail (one seek), validate the body,
  canonicalize and BLAKE3 the entry, append one line, upsert one SQLite row
  (WAL, `synchronous=NORMAL`). No fsync of the ledger unless `AGENTVCS_FSYNC` is
  set — with it, every step pays a disk flush; not measured here.
- Not measured: concurrent writers, fsync, Linux. CI runs the suite on
  ubuntu-latest but does not run the benchmark.
