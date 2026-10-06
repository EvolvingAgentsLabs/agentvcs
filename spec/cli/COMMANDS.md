# CLI contract (v0.1)

Every command accepts `--json` and then prints exactly one JSON object on stdout:
`{"ok": true, …}` or `{"ok": false, "error": {"code": "E_…", "message": "…"}}`.
Consumers branch on `code`. No command prompts; destructive commands need `--yes`.
`-C <dir>` runs against another project directory. Exit codes: `EXIT_CODES.md`.

Commands marked **(conf)** have golden cases in `conformance/` for v0.1.

| Command | Output (normative fields) |
|---|---|
| `init` | `{"ok", "store"}` — creates `.agentvcs/`; idempotent |
| `hash <file> [--canonical]` **(conf)** | `{"ok", "hash", "canonical"?}` — with `--canonical`, the file is JSON and is hashed in JCS form, which is also returned as a string; without it, raw bytes |
| `snapshot <manifest.json\|yaml>` **(conf)** | `{"ok", "manifest_id", "dimensions": {name: content_hash}}` — accepts the authoring form (hashes optional), validates, stores |
| `run start --manifest <id> [--run-id <s>]` | `{"ok", "run_id"}` |
| `run end <run> [--status s]` | `{"ok", "run_id", "entries"}` |
| `step record <run>` (stdin: StepRecord body) | `{"ok", "seq", "entry_hash"}` |
| `diff <a> <b>` **(conf)** | `SEMANTIC_DIFF.md` — `a`, `b` are manifest ids in the store or paths to manifest files |
| `patch propose <run> --from <id> --to <manifest> --rationale <s> --evidence <i,j> [--author type:id]` | `{"ok", "patch_id", "semantic_diff"}` |
| `gate run <patch_id> --suite <suite.yaml>` | `{"ok", "gate_result"}` — runs the suite's declared command, reads its JSON metrics |
| `patch apply <patch_id> --at-step <n>` | `{"ok", "seq", "entry_hash", "active_manifest"}` — refuses ungated patches (`E_PATCH_UNGATED`) |
| `patch rollback <patch_id>` | `{"ok", "patch_id", "active_manifest"}` |
| `resume <run> --from-step <n> --manifest <id>` | `{"ok", "run_id", "parent", "checkpoint_ref"}` — creates the child run; the harness restores via its hook |
| `log <run>` | `{"ok", "entries": [...]}` |
| `blame <run\|bundle> --metric <m>` **(conf)** | `BLAME.md` |
| `bisect <run> --metric <m> --bad <cond> --exec <cmd>` | `{"ok", "first_bad_patch", "probes": [...]}` — no goldens in v0.1 |
| `freeze <manifest_id>` | `{"ok", "manifest_id", "frozen": true}` — requires a passed gate naming it |
| `export audit <run> [-o file]` | writes an audit bundle (`PROTOCOL.md §4`) |
| `verify <run\|bundle>` **(conf)** | `LEDGER.md` |
| `mcp` | MCP server over stdio exposing the commands above with the same JSON |

`hash` is not in the revival plan's command table. It is added because
canonicalization must be testable on its own, before any object exists.
