# agentvcs

**Version control for software that is *cultivated*, not written.**

Git versions one thing: source code, frozen in time, changed by humans. But when
a fleet of agents builds and runs software, four things change at once — the
**code**, the **goal** it's pursuing, the **models** it's running, and the
**messages** the agents exchange to get there — and they change *while the system
is running*. The line between design-time and run-time disappears.

No tool versions that. `agentvcs` does.

```
            ┌─────────── one commit ───────────┐
   code  →  │  tree     goal     models   trace │  state: fluid | crystallized
            └───────────────────────────────────┘
```

Every commit is a snapshot across **all four dimensions** plus a **state**:

- **`fluid`** — the agent is still evolving: high-temperature models, code and
  goals mutating between iterations. Powerful, expensive, non-deterministic.
- **`crystallized`** — a solution you trust, *frozen*. Models pinned to
  temperature 0 and the message trace compiled into a replayable recipe. Cheap,
  stable, deterministic. `agentvcs freeze` does the conversion.

This is the open-source core — the "git for agents". Zero runtime dependencies,
pure Python stdlib, fully auditable. Apache-2.0.

## Install

```bash
pip install agentvcs        # once published
# or from source:
pip install -e .
```

## Quickstart

```bash
agentvcs init                       # creates .agentvcs/ and a template agent.json
```

> `avcs` is a built-in shorthand for `agentvcs` — every command below works with either name.

Declare the non-code dimensions in `agent.json`:

```json
{
  "goal": "Resolve refund requests autonomously",
  "models": [
    { "provider": "anthropic", "model": "claude-opus-4-8", "params": { "temperature": 1.0 } }
  ],
  "trace": "traces/run.jsonl",
  "state": "fluid"
}
```

Then version the whole evolving system:

```bash
agentvcs commit -m "initial fluid refund agent"
agentvcs log                        # the evolution history, with goal + state per commit
agentvcs diff                       # dimensional diff: what changed in code vs goal vs models vs trace
agentvcs branch experiment          # a live branch — fork the execution, not just the text
agentvcs checkout experiment
agentvcs freeze                     # crystallize HEAD → deterministic recipe under crystal/
```

`agentvcs diff` is the point. It tells you *which dimension* moved:

```
705b2fb..1d4bd90
  code
    ~ app.py
  goal
    from: Resolve refund requests autonomously
    to:   Resolve refund requests with fraud checks
```

A goal redirect and a code change are now distinguishable events, not one opaque
text diff.

## Commands

| command | what it does |
|---|---|
| `agentvcs init` | create a repository |
| `agentvcs commit -m MSG` | snapshot code + goal + models + trace |
| `agentvcs log` | evolution history (state + goal per commit) |
| `agentvcs status` | working-tree changes, per dimension |
| `agentvcs show [COMMIT]` | one commit across all dimensions |
| `agentvcs diff [A] [B]` | dimensional diff (default: parent..HEAD) |
| `agentvcs branch [NAME]` | list, or create a live branch |
| `agentvcs checkout REF` | restore the working tree from a branch/commit |
| `agentvcs rollback [REF]` | undo: restore the full prior state (the panic button) |
| `agentvcs freeze [COMMIT]` | crystallize a fluid commit into a deterministic recipe |

Add `--json` to any command for machine-readable output (see below).

## Built for agents (B2A)

The primary user of a VCS for agent fleets *is an agent*. agentvcs is designed so
a coding agent (Claude Code, Cursor, …) can drive it without guessing:

- **`--json` on every command** (or `AGENTVCS_JSON=1`) → one parseable object,
  no spinners, no color, no prose.
- **Stable `error.code`s** (`NOT_A_REPO`, `BAD_REF`, `ALREADY_CRYSTALLIZED`, …) →
  recover programmatically, not by parsing English. Full list in
  [`docs/AGENT_MODE.md`](docs/AGENT_MODE.md).
- **`agentvcs rollback`** → a real panic button: restores the *entire* prior state
  (code + goal + models + trace) and is itself reversible.
- **Auto-discovery** → `agentvcs init` scaffolds an `AGENTS.md` so the next agent
  to open the repo learns the workflow on its own.
- **A Claude Code skill** ships in [`.claude/skills/agentvcs/`](.claude/skills/agentvcs/SKILL.md).
- **An MCP server** (zero-dependency, stdio JSON-RPC):

  ```bash
  claude mcp add agentvcs -- agentvcs-mcp
  ```

  Exposes `avcs_log`, `avcs_show`, `avcs_diff`, `avcs_status`, `avcs_commit`,
  `avcs_freeze`, `avcs_rollback`, `avcs_branch`, `avcs_checkout`.

```jsonc
$ agentvcs diff --json
{"ok": true, "command": "diff", "a": "705b2fb…", "b": "1d4bd90…",
 "diff": {"code": {"added": [], "removed": [], "modified": ["app.py"]},
          "goal": {"from": "…autonomously", "to": "…with fraud checks"},
          "models": null, "trace": null, "state": null}}
```

## How it stores things

Content-addressed objects under `.agentvcs/objects/`, exactly like git's loose
objects — but the object types are `commit`, `tree`, `goal`, `modelpin`, `trace`
and `crystal`. Identical dimensions are stored once. See
[`docs/SPEC.md`](docs/SPEC.md) for the on-disk format — that spec *is* the
standard we're proposing.

## Try the example

```bash
cd examples/refund-agent
agentvcs init
agentvcs commit -m "first run"
agentvcs show
```

## Scope

This repo is the **local protocol and runtime**, and it is deliberately
complete on its own — it works offline, on your machine, forever. Hosted
collaboration, a visual evolution tree, AI-assisted branch merging and fleet
observability are a separate concern and not part of this open-source core.

## License

Apache-2.0. See [LICENSE](LICENSE).
