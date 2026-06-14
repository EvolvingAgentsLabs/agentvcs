---
name: agentvcs
description: Version an evolving agent/app with agentvcs — commit code+goal+models+trace together, diff per dimension, rollback mistakes, and freeze (crystallize) a trusted solution into a deterministic recipe. Use when working in a repo that has a .agentvcs/ directory or an agent.json, or when the user asks to version, snapshot, branch, undo, or freeze an agent/fleet.
---

# Versioning evolving agents with agentvcs

agentvcs is a multidimensional VCS: each commit captures **code + goal + models +
trace** and a **state** (`fluid` = evolving, `crystallized` = frozen/deterministic).
Use it to make your own iterative work inspectable, reversible, and freezable.

## Always pass `--json`
Run every command with `--json`. Output is one JSON object: `{"ok": true, ...}` on
success, `{"ok": false, "error": {"code": "...", "message": "..."}}` on failure.
**Branch on the `code`, never on the message.** Codes: `NOT_A_REPO`, `ALREADY_REPO`,
`NO_COMMITS`, `NO_PARENT`, `BAD_REF`, `AMBIGUOUS_REF`, `BRANCH_EXISTS`,
`ALREADY_CRYSTALLIZED`.

## If your shell cwd is not sticky, use `-C`
Pass `-C <project-dir>` (like `git -C`) to run against that repo from anywhere:
`agentvcs -C /path/to/proj commit -m "..." --json`. `init` creates the dir if absent.

## The non-code state lives in `agent.json`
```json
{ "goal": "...", "models": [{"provider":"...","model":"...","params":{...}}],
  "trace": "traces/run.jsonl", "state": "fluid", "metrics": {} }
```
Keep `goal` current. The `trace` is the message history you are versioning beyond
code; you can supply it two ways:

- **Path (manual):** `"trace": "traces/run.jsonl"` — append agent messages as you work.
- **Provider (automatic, preferred in Claude Code):**
  ```json
  "trace": { "provider": "claude-code", "auto": true },
  "models": [{ "provider": "anthropic", "auto": true }]
  ```
  You then maintain **no** trace file: `commit` auto-vacuums Claude Code's native
  session transcript (real `tool_use`/`tool_result`/`thinking`), and the model pin
  is detected from what actually ran. Add `"redact": ["sk-[A-Za-z0-9-]+", ...]` to
  scrub secrets, or `"session"` / `"project_dir"` to pin a specific transcript.

## Core loop
```bash
agentvcs init --json                      # if no .agentvcs/ yet (scaffolds agent.json + AGENTS.md)
# ... edit code, update agent.json's goal, append to the trace file ...
agentvcs commit -m "what changed" --json  # after each meaningful iteration
agentvcs status --json                    # uncommitted changes, per dimension
agentvcs diff --json                      # parent..HEAD: which dimension moved?
```

## When you break something
```bash
agentvcs rollback --json                  # restore full prior state (HEAD's parent)
agentvcs rollback <ref> --json            # ...or to a specific commit (short prefix ok)
```
Rollback is reversible: the prior head is reported as `previous_head` and saved to
`.agentvcs/ROLLBACK_HEAD`. Recover with `agentvcs checkout <previous_head>`.

## Explore alternatives safely
```bash
agentvcs branch try-b --json && agentvcs checkout try-b --json
# evolve a different strategy here; keep the winner
```

## When a solution is trusted, freeze it
```bash
agentvcs freeze --json                    # crystallize HEAD -> deterministic recipe
```
This pins every model to temperature 0 and writes a replayable recipe to
`crystal/<commit>.json`. Re-running a crystallized commit is reproducible and cheap.
A crystallized commit cannot be re-crystallized (`ALREADY_CRYSTALLIZED`).

Re-execute a frozen recipe deterministically:
```bash
agentvcs replay --json                    # emit the frozen goal/models/steps
agentvcs replay --exec "my-runner" --json # pipe each step (JSON) to your executor
```
Replaying a fluid commit errors with `NOT_CRYSTALLIZED` — freeze it first.

## Inspect the captured conversation
```bash
agentvcs trace --json                     # which session/file is hooked (+ message count, model)
agentvcs show --trace --json              # the commit + the full conversation that produced it
```

## Show a human the evolution (local dashboard)
```bash
agentvcs ui --json                        # serve http://127.0.0.1:8080; prints {url,host,port}
agentvcs ui --no-open --json              # headless (no browser); keeps serving until stopped
```
A read-only split view: commit graph on the left; per commit, its dimensional diff
plus the trace rendered as a chat (`thinking`/`tool_use`/`tool_result`). Polls, so
commits appear live. Read-only, loopback-only, zero dependencies.

## Run it continuously inside Claude Code
Wire it once and the frame is always-on, no per-turn work:
```bash
agentvcs init --claude-code --runtime     # in the dir you launch Claude Code from
```
```jsonc
// ~/.claude/settings.json — live budget/$/context in the status bar, every render
"statusLine": { "type": "command", "command": "agentvcs statusline" }
// .claude/settings.json — auto-commit the frame each turn (a versioned session)
"hooks": { "Stop": [ { "hooks": [
  { "type": "command", "command": "agentvcs commit -m 'cc checkpoint'" } ] } ] }
```
The `statusLine` command must run where the runtime repo lives (cwd-based, or pass
`-C <repo>`); `statusline` drains and ignores the session JSON Claude Code pipes it,
so it can't hang the bar. `agentvcs log` then reads as the session's frame history.

## MCP alternative
If the `agentvcs` MCP server is connected, the same operations are available as
tools `avcs_log`, `avcs_show` (pass `trace:true` for the conversation), `avcs_diff`,
`avcs_status`, `avcs_commit`, `avcs_freeze`, `avcs_replay`, `avcs_rollback`,
`avcs_branch`, `avcs_checkout`, `avcs_trace`. Each returns the same `{"ok": ...}`
JSON. Register with: `claude mcp add agentvcs -- agentvcs-mcp`.
