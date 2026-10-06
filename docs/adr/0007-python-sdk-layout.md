# ADR-0007 — Python SDK: layout, the `agentvcs` name, and how a harness learns about patches

- Status: proposed (2026-10-06) — Phase 2 (F2); needs Matias's review
- Context: ADR-0001 makes the Python SDK a thin PyO3/maturin binding with no
  protocol logic. Phase 1 left a skeleton (`crates/agentvcs-py`, module
  `agentvcs_py`). Phase 2 needs a usable SDK — run/step recording, live patches,
  checkpoint hooks, model wrappers — and a toy pipeline that exercises it.

## 1. Layout: a mixed maturin project inside the crate

```text
crates/agentvcs-py/
  Cargo.toml            cdylib `agentvcs_native`, exported as `agentvcs._native`
  pyproject.toml        maturin, python-source = "python", abi3 (CPython >= 3.10)
  src/lib.rs            the native module: forwards to agentvcs-core / agentvcs-cli
  python/agentvcs/      the Python layer (run, step, hooks, integrations, testing)
  tests/                pytest
  dev.sh                venv + maturin develop (+ pytest)
```

Chosen over a top-level `python/` directory: the Rust and Python halves of one
package version together and are reviewed together, and the repository root
already holds the legacy package's `pyproject.toml` (§2). One abi3 wheel per
platform covers every CPython from 3.10.

**No protocol logic in Python.** Canonical JSON, hashing, manifest validation,
the ledger chain and every writer invariant (`E_STEP_MANIFEST`, `E_STEP_INDEX`,
`E_PATCH_UNGATED`, …) are the core's. The Python layer only shapes calls:
`step_record` gets the body the harness produced, the core fills or refuses it.
`python -m agentvcs` (the wheel's `agentvcs` script) is `agentvcs_cli::main_with`,
the same function the release binary's `main` calls; it passes 83/83.

The native module exposes a `NativeStore` holding the store open (and its SQLite
index), because re-opening per step costs more than the 2 ms `step record`
target (docs/BENCHMARKS.md: the library path meets it, the CLI does not).

## 2. The `agentvcs` name

The legacy pure-Python implementation (`src/agentvcs`, root `pyproject.toml`,
distribution `agentvcs`, 0.3/0.4 on PyPI) also imports as `agentvcs`.

- **The new SDK takes the name**: distribution `agentvcs`, import `agentvcs`,
  version `0.5.0.dev0` (above the legacy releases, so an upgrade replaces it).
- **The legacy package stays importable, untouched**, until ADR-0001's step 4
  moves it to `legacy/`. Its root `pyproject.toml` and `release.yml` are not
  changed in this PR: renaming its distribution would change what a `v*` tag
  publishes, which is the legacy move's decision, not this one.
- Consequence: the two cannot share a virtualenv (last install wins the files).
  CI installs them in separate jobs; `dev.sh` uses its own venv. The legacy
  suite stays green (220 passed, run in its own venv).
- At the legacy move: rename the root distribution to `agentvcs-legacy` (or drop
  it) and switch `release.yml` to building this crate's wheels.

## 3. How a harness learns that a patch was applied

A supervisor applies patches with `agentvcs patch apply` from another process (or
the harness calls `run.apply_patch` in-process). The harness learns about it by
**polling the ledger tail at every step boundary**: `Run.sync()` reads the run's
last line (`run_state`, one seek) and, only when `next_seq` moved past what it has
seen, reads the new entries; every `patch` entry fires the `on_patch` callbacks
with a `PatchEvent` (ids, rationale, author, semantic diff, the new `Manifest`)
and makes `run.manifest` the new manifest. `@step` calls `sync()` before running.

Chosen over a file watcher, a socket or a signal: no new surface, no platform
code, and the ledger is already the single source of truth. Cost: one tail read
per step. Latency: a patch takes effect at the next step boundary — exactly the
protocol's `applied_at_step` semantics.

**A patch that lands while a step runs.** The step ran under the old manifest,
but the ledger's next step must run under the new one; the core refuses the
record (`E_STEP_MANIFEST`). Default policy `on_race="rerun"`: fire `on_patch`,
execute the step again under the new manifest, record that. The ledger therefore
never claims a step ran under a manifest it did not run under. `on_race="raise"`
raises `StepRace` instead, for steps with side effects that must not repeat. The
toy pipeline hits this path in practice (`stats.reruns`).

The SDK cannot stop a harness from caching configuration and ignoring patches
(the toy pipeline's `--no-reload` control does exactly that). Blame then shows
the patch at the boundary with a zero delta, which is the honest reading.

## 4. Two writers on one run: advisory lock in the core

The harness (steps) and the supervisor (patches) append to the same ledger from
different processes. Phase 1 refused a stale writer but took no lock, so two
appends could both read seq *n* and both write seq *n* — a forked chain.
`Store::append` now builds the entry, takes an exclusive advisory lock on the
ledger file (`File::lock`, flock on Unix; Rust ≥ 1.89, so `rust-version` moves
from 1.80 to 1.89), re-reads the tail, compares, appends, and releases. The
loser gets `E_STALE_STATE`; the SDK retries the record, the toy supervisor
retries `patch apply`. Test: `concurrent_writers_never_fork_the_chain`
(4 threads × 50 appends) — fails 3/3 with the lock removed, passes with it
[ran]. A refused entry no longer leaves an empty ledger file behind
(`a_refused_entry_leaves_no_ledger_file`). This supersedes the "concurrent writers
are not locked" sentence of ADR-0006 §5.

## 5. Hooks and resume

- `run.checkpoint(fn)`: `fn(step) -> str | None` runs after each step; the string
  is that step's `checkpoint_ref`, opaque to agentvcs.
- `run.restore(fn)`: `fn(checkpoint_ref)` runs once, when a resumed run is
  entered (or at registration, if it already was).
- `run.resume(from_step, manifest)` / `agentvcs.resume(parent, from_step,
  manifest)`: the CLI's `resume` creates the child (with `parent` and the
  `checkpoint_ref` of step `from_step - 1`, ADR-0006 §5); hooks are inherited;
  the child's first step has `step_index == from_step`.

## 6. Model integrations

`agentvcs.integrations.openai_compat` (stdlib HTTP; llama.cpp server, vLLM,
Ollama `/v1`) and `agentvcs.integrations.anthropic` (the official `anthropic`
SDK, optional dependency) read `{agent}.model`, `{agent}.sampling` and
`{agent}.prompt` from the active manifest **on every call**, so a patch to any of
them changes the next call. Inside a `@step` they add tokens, the request and the
response to that step; inside a run but outside a step they record a step of
their own; outside a run they need `manifest=` and record nothing (gate suites).
Tests use local HTTP fakes only (`agentvcs.testing`); no real model or API is
called. For Claude, only fields the Messages API accepts are forwarded; current
Claude models reject `temperature`/`top_p`/`top_k`, and the wrapper forwards them
only if the manifest sets them — the manifest is the configuration, the SDK does
not second-guess it.

## Consequences

- `cargo build` at the root no longer builds the binding (`default-members`); it
  linked libpython and failed on the dev Mac. `--workspace` commands still check it.
- CI builds the wheel on macos-14 (arm64) and ubuntu-latest (x86_64), runs the SDK
  tests, the toy pipeline (fake backend, both arms) and conformance through
  `python -m agentvcs`.
- Not done here: bisect golden cases with the toy pipeline's hooks (LATER.md),
  a `blob put` CLI verb (the SDK uses the native `put_blob`), async APIs.
