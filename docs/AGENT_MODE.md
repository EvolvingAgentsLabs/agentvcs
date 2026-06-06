# Agent mode

agentvcs is built to be driven by autonomous coding agents, not only humans. This
document is the contract an agent can rely on.

## JSON output

Pass `--json` to any command (or set `AGENTVCS_JSON=1` in the environment). The
command then prints exactly **one** JSON object to stdout and nothing else — no
spinners, no ANSI color, no prose.

## Working directory: `-C` / `--repo`

Agents often run each shell command in a fresh process whose working directory is
not sticky. Pass `-C <dir>` (like `git -C`) so the command runs against that repo
regardless of the current directory — it works both before and after the
subcommand:

```
agentvcs -C /path/to/proj commit -m "..." --json
agentvcs commit -m "..." -C /path/to/proj --json
```

For `init`, the directory is created if it does not exist; for every other command
a missing directory fails with `BAD_DIR`.

Success:
```json
{ "ok": true, "command": "<name>", ...command-specific fields... }
```

Failure (exit code `1`):
```json
{ "ok": false, "command": "<name>", "error": { "code": "STABLE_CODE", "message": "human text" } }
```

**Branch on `error.code`, never on `error.message`.** Codes are stable across
versions; messages may change.

## Exit codes

| code | meaning |
|------|---------|
| `0`  | success |
| `1`  | a `RepoError` (see error codes below); in `--json` the body has `ok:false` |

## Error codes

| code | when | suggested agent recovery |
|------|------|--------------------------|
| `NOT_A_REPO` | no `.agentvcs/` found from the cwd upward | run `agentvcs init` |
| `ALREADY_REPO` | `init` on an existing repo | proceed; it is already initialized |
| `NO_COMMITS` | operation needs history but there is none | `commit` first |
| `NO_PARENT` | `rollback` with no parent to go to | nothing to undo; pick an explicit ref |
| `BAD_REF` | ref/commit/prefix did not resolve | re-check with `agentvcs log --json` |
| `AMBIGUOUS_REF` | short prefix matched multiple objects | use a longer prefix |
| `BRANCH_EXISTS` | `branch <name>` already exists | choose another name or `checkout` it |
| `BAD_DIR` | `-C <dir>` points to a non-existent directory (non-`init` command) | create it or fix the path |
| `ALREADY_CRYSTALLIZED` | `freeze` on a crystallized commit | already frozen; nothing to do |
| `INTERNAL` | unexpected error (MCP tools only) | report; do not retry blindly |

## Command output fields (success)

- `init` → `repository`, `manifest`, `agents_md`
- `commit` → `commit`, `branch`, `state`, `message`
- `log` → `commits[]` of `{commit, state, timestamp, message, goal, parents}`
- `status` → `branch`, `head`, `diff`
- `show` → commit summary + `models[]`, `trace_messages`, `metrics`, `crystal`
- `diff` → `a`, `b`, `diff` (per-dimension; `null` where unchanged)
- `branch` → list `{current, branches[]}` or `{branch, commit}` when creating
- `checkout` → `ref`, `commit`
- `rollback` → `restored_to`, `previous_head`, `goal`, `state`
- `freeze` → `commit`, `source`, `state`, `recipe_path`

The `diff` object is `{code:{added,removed,modified}, goal, models, trace, state}`;
every non-code dimension is `null` when unchanged, so an agent can cheaply detect
*which* dimension moved.

## References

`show`, `diff`, `checkout`, `rollback`, and `freeze` accept a branch name, a full
64-hex object id, or an unambiguous **short prefix** (≥4 chars). Ambiguous prefixes
fail with `AMBIGUOUS_REF`.

## MCP server

`agentvcs-mcp` is a stdio MCP server (newline-delimited JSON-RPC 2.0, zero
dependencies). Register it with Claude Code:

```bash
claude mcp add agentvcs -- agentvcs-mcp
```

It exposes one tool per operation: `avcs_log`, `avcs_show`, `avcs_diff`,
`avcs_status`, `avcs_commit`, `avcs_freeze`, `avcs_rollback`, `avcs_branch`,
`avcs_checkout`. Each tool result is a single text-content item whose text is the
same `{"ok": ...}` JSON described above; tool failures set `isError: true`.

The server operates on the repository discovered from its working directory.
