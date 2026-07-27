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
| `NOT_CRYSTALLIZED` | `replay` on a fluid commit | `freeze` it first, then replay |
| `UNKNOWN_TRACE_PROVIDER` | `agent.json`'s `trace.provider` is not registered | fix the provider name (known: `claude-code`) |
| `BAD_TRACE` | `agent.json`'s `trace` is neither a path nor a provider object | set it to a path string or `{ "provider": ... }` |
| `PORT_IN_USE` | `ui` could not bind any port in the probed range | pass a free `--port`, or stop the other server |
| `BAD_TRAIT` | `price --trait` got a value other than `score`/`size`/`cost` | pick a valid trait |
| `INTERNAL` | unexpected error (MCP tools / UI API only) | report; do not retry blindly |

## Command output fields (success)

- `init` → `repository`, `manifest`, `agents_md`, `trace_provider` (`--claude-code` wires the live session)
- `commit` → `commit`, `branch`, `state`, `message`
- `log` → `commits[]` of `{commit, state, timestamp, message, goal, parents}`
- `status` → `branch`, `head`, `diff`
- `show` → commit summary + `models[]`, `trace_messages`, `metrics`, `crystal`; with `--trace` (CLI) or `trace:true` (MCP) also a full `trace[]` of messages
- `trace` → the current trace source: `{kind:"path"|"provider"|"none", ...}` — for a provider, `transcript`, `messages`, and the detected `model`
- `diff` → `a`, `b`, `diff` (per-dimension; `null` where unchanged)
- `branch` → list `{current, branches[]}` or `{branch, commit}` when creating
- `checkout` → `ref`, `commit`
- `rollback` → `restored_to`, `previous_head`, `goal`, `state`, `reason` (the justification recorded in the durable ledger; `--reason TEXT` sets it, else it defaults to the restored commit's goal)
- `freeze` → `commit`, `source`, `state`, `recipe_path`
- `replay` → `commit`, `source_commit`, `goal`, `models`, `executed`, `steps[]` (each `{index, step[, exit_code, output]}`)
- `ui` → `url`, `host`, `port` (printed once when the dashboard binds, then it keeps serving until interrupted)
- `price` → `trait`, `n_parents`, `selection` (`Cov(w,z)`), `transmission` (`E[w·Δz]`), `selection_contrib`, `transmission_contrib`, `delta_zbar`, `reading`, `threshold{crossed, code, degrading}`, `l_total`/`l_effective` (editable-surface size); `insufficient:true` + `message` when there are `<2` eval'd branch points
- `health` → `healthy` (bool), `warnings[]` (flat, act on these), plus the full `price`, `slowing` (`{lag1_autocorr, variance_trend, warning, signal}`), and `ratchet` (`{trunk, branches[], warnings[]}`) sub-objects
- `branch` (list form) also carries `ratchet` per branch (`none`/`medium`/`high`) and a top-level `warnings[]` for long unmerged lineages
- `infobits` → `n_decisions`, `distinct_actions`, `action_entropy_bits` (`H(A)`), `transition_mi_bits` (`I(prev;next)`, a lower-bound proxy), `context_tokens`, `bits_per_ktok`, `reading`; `insufficient:true` when the traces hold no tool-use decisions
- `contain` → `fanout` (n), `prob` (p), their `*_source`, `r0` (`n·p`), `contained` (bool), `critical_prob` (`1/n`), `required_verification_rate`, `reading`; `insufficient:true` when neither a measured/`--fanout` n nor a measured/`--prob` p is available

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

It exposes one tool per operation: `avcs_log`, `avcs_show`, `avcs_trace`,
`avcs_diff`, `avcs_status`, `avcs_commit`, `avcs_freeze`, `avcs_replay`,
`avcs_rollback`, `avcs_branch`, `avcs_checkout`, `avcs_merge`, `avcs_eval`,
`avcs_recall`, `avcs_runtime`, `avcs_budget`, `avcs_context`, `avcs_price`,
`avcs_health`, `avcs_infobits`, `avcs_contain`. Each tool result is a single
text-content item whose text is the same `{"ok": ...}` JSON described above; tool
failures set `isError: true`.

The server operates on the repository discovered from its working directory.

## Local dashboard (`agentvcs ui`)

`agentvcs ui` serves a read-only web dashboard (standard library only, loopback by
default) for *seeing* the evolution: a commit graph on the left, and per commit its
dimensional diff plus a chat-style render of the captured trace (`thinking` /
`tool_use` / `tool_result` blocks), goal, and model pins. It polls so new commits
appear live while an agent keeps working.

```bash
agentvcs ui                       # open a browser on http://127.0.0.1:8080
agentvcs ui --no-open --json      # headless: print {url,host,port}, keep serving
agentvcs ui --port 9000 --host 0.0.0.0
```

It also exposes the same data as a tiny read-only JSON API (same `{"ok":...}`
envelope; errors carry the stable `error.code`), useful to agents that want the
history programmatically over HTTP:

| Route | Returns |
|-------|---------|
| `GET /api/repo` | `{current, head, branches[], goal}` |
| `GET /api/log` | `{commits[]}` (same rows as `log`) |
| `GET /api/commit/<ref>` | `{commit}` (same as `show`) |
| `GET /api/commit/<ref>/trace` | `{trace[]}` (raw message blocks) |
| `GET /api/diff?a=&b=` | `{a, b, diff}` (defaults parent..`b`) |

`<ref>` accepts the same branch name / full id / short prefix as the CLI.

## Trace providers (high-fidelity, zero-friction capture)

`agent.json`'s `trace` is either a **path** (you maintain the file) or a
**provider** object that agentvcs reads automatically at commit time:

```json
"trace": { "provider": "claude-code", "auto": true },
"models": [{ "provider": "anthropic", "auto": true }]
```

With the `claude-code` provider you maintain **no** trace file: `commit` vacuums
Claude Code's native session transcript (`~/.claude/projects/<cwd "/"→"-">/<uuid>.jsonl`)
— the real `tool_use` / `tool_result` / `thinking` blocks — and `"auto": true`
model pins are filled from the model that actually ran. Run `agentvcs trace` to
confirm which transcript is hooked before committing. Known secrets are scrubbed
by default; add `"redact": ["sk-[A-Za-z0-9-]+", ...]` for more, or `"redact": false`
to disable. Pin a specific transcript with `"session"` / `"project_dir"` / `"path"`.
