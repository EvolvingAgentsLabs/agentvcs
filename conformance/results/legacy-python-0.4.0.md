# Conformance result — current Python implementation (0.4.0)

- Date: 2026-10-06 · Suite: 83 cases (protocol v0.1 draft) · Command:
  `python conformance/run.py --cli agentvcs --out legacy.jsonl` [ran]
- **Result: 0 / 83.** This was predicted by `docs/INVENTORY.md` §6 before the run.

| group | passed | how it fails |
|---|---|---|
| hash | 0/15 | `hash` does not exist → exit 2 (usage) |
| manifest | 0/13 | `snapshot` does not exist → exit 2 |
| diff | 0/16 | `diff` exists but compares two *commits* in a repo, not two manifest files → exit 1 |
| verify | 0/31 | `verify` exists but checks Ed25519 commit signatures; it cannot read an audit bundle (`ok: false` on 25, exit 1 on 6) |
| blame | 0/8 | `blame` does not exist → exit 2 |

## Where it differs, beyond missing commands

- Hash function and canonical form: SHA-256 over `json.dumps(sort_keys=True)`
  (`src/agentvcs/objects.py:25`), blobs framed with `blob\0`; v0.1 is BLAKE3 over
  RFC 8785. Python's `sort_keys` orders by code point, JCS by UTF-16 code unit —
  they disagree exactly on the emoji-vs-U+FB33 case (`hash-003`). And `1.0` is
  stored as `1.0`, where JCS writes `1`.
- No per-step manifest stamping and no hash-chained run ledger: the closest
  object is a commit, which hashes `timestamp`, `author` and `message`.
- Version skew: `pyproject.toml` says 0.3.0, `agentvcs.__version__` says 0.4.0.

## Instrument controls (same day)

- Positive control: `conformance/tools/refcli.py` (backed by the generator's
  reference functions) → 83/83. Proves the runner's plumbing only; it passes on
  values by construction.
- Mutation control: four expectations altered (a diff line count, a violation
  seq, a blame delta, the BLAKE3 vector) → exactly those four fail.
- External oracles: the RFC 8785 examples and the BLAKE3 empty-input vector
  were typed from the published documents, not generated; the reference agrees
  with them. Every JSON value in the suite (284) canonicalizes identically under
  Trail of Bits' `rfc8785` package, except two integers above 2^53 − 1 that it
  refuses — which led the spec to refuse them too (`hash-015`).

Per ADR-0001 the fallback (bench on Python if Rust is late) therefore means
implementing v0.1 in Python behind the same CLI, not using 0.4.0 as is.
