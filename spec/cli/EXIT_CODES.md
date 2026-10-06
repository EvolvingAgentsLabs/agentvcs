# Exit codes (v0.1)

| Code | Meaning | stdout with `--json` |
|---|---|---|
| 0 | success; for `verify`, the ledger is valid | `{"ok": true, …}` |
| 1 | the command ran and the answer is negative: `verify` found violations, a gate did not pass | `{"ok": true, …}` |
| 2 | usage error (unknown command, bad flags) | `{"ok": false, "error": {"code": "E_USAGE"}}` |
| 3 | invalid input: a file is not JSON, fails its schema, or carries a wrong hash | `{"ok": false, "error": {"code": "E_SCHEMA" \| "E_CONTENT_HASH" \| "E_MANIFEST_ID" \| "E_UNKNOWN_KIND" \| "E_PROTOCOL_VERSION" \| "E_CANONICAL" \| "E_INVALID_LEDGER"}}` |
| 4 | store error: not initialized, object not found | `{"ok": false, "error": {"code": "E_NO_STORE" \| "E_NOT_FOUND"}}` |
| 5 | refused by policy: ungated patch, freeze without a passed gate | `{"ok": false, "error": {"code": "E_PATCH_UNGATED" \| "E_NOT_GATED"}}` |

`E_CANONICAL`: the input cannot be canonicalized (NaN, infinity, lone surrogate).
