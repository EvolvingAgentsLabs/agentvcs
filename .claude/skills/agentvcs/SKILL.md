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
Keep `goal` current and append agent messages to the `trace` file as you work — that
is the state you are versioning beyond code.

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

## MCP alternative
If the `agentvcs` MCP server is connected, the same operations are available as
tools `avcs_log`, `avcs_show`, `avcs_diff`, `avcs_status`, `avcs_commit`,
`avcs_freeze`, `avcs_rollback`, `avcs_branch`, `avcs_checkout`. Each returns the
same `{"ok": ...}` JSON. Register with: `claude mcp add agentvcs -- agentvcs-mcp`.
