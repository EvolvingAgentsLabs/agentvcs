# Conformance suite — agentvcs protocol v0.1

83 golden cases that pin every observable behaviour of the protocol: canonical
hashing, manifest ids, semantic diff, ledger verification and blame.

```bash
python conformance/run.py --cli "agentvcs"                 # stdlib only
python conformance/run.py --cli "agentvcs" --group verify --out results.jsonl
```

| group | cases | spec |
|---|---|---|
| hash | 15 | `spec/PROTOCOL.md §1` — incl. RFC 8785 and BLAKE3 published vectors |
| manifest | 13 | `spec/PROTOCOL.md §2` |
| diff | 16 | `spec/SEMANTIC_DIFF.md` |
| verify | 31 | `spec/LEDGER.md` — 6 valid ledgers, 25 broken one way each |
| blame | 8 | `spec/BLAME.md` |

Each case is a directory: `case.json` (`argv`, expected exit code, expected JSON
subset, optional `first_violation`, `source`) plus its input files.

## Regenerating

Cases are generated, never hand-edited: `python conformance/tools/gen.py`
(needs `pip install blake3`). Verdicts — which error, which op, which delta — are
declared by hand in `gen.py`; the reference functions in `tools/ref.py` only fill
in hashes and must agree with every declaration or generation aborts. CI checks
that regeneration is byte-identical to what is committed.

`tools/refcli.py` is the runner's positive control, not an implementation.

## Results

- [`results/legacy-python-0.4.0.md`](results/legacy-python-0.4.0.md) — 0/83, as predicted.
