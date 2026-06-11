# agentvcs

[![CI](https://github.com/EvolvingAgentsLabs/agentvcs/actions/workflows/ci.yml/badge.svg)](https://github.com/EvolvingAgentsLabs/agentvcs/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentvcs.svg)](https://pypi.org/project/agentvcs/)
[![Python](https://img.shields.io/pypi/pyversions/agentvcs.svg)](https://pypi.org/project/agentvcs/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

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

![agentvcs capturing a live Claude Code session](examples/recording/cc-trace.gif)

*A real run: `commit` pulls the conversation straight from your live Claude Code
session — the actual `thinking` / `tool_use` / `tool_result` — and `show --trace`
puts it next to the code. You never write a trace file. Full walkthrough in
[`docs/TUTORIAL.md`](docs/TUTORIAL.md).*

## Install

```bash
pip install agentvcs        # once published
# or from source:
pip install -e .
```

## Quickstart

```bash
agentvcs new my-agent               # scaffold a project already wired for agents (recommended)
# ...or initialize an existing directory:
agentvcs init                       # creates .agentvcs/ and a template agent.json
```

`agentvcs new` materializes a project a coding agent can drive immediately — an
`agent.json`, an `AGENTS.md` operating manual, the Claude Code skill, the MCP
config, and a first commit. Then just open it with your agent and describe what
to build.

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

The `trace` can be a file you maintain (above) **or** a *provider* that captures
the agent's native session automatically — see
[Zero-friction trace capture](#zero-friction-trace-capture-claude-code) below.

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
| `agentvcs new DIR` | scaffold a new agent project pre-wired with agentvcs |
| `agentvcs init` | create a repository |
| `agentvcs commit -m MSG` | snapshot code + goal + models + trace |
| `agentvcs log` | evolution history (state + goal per commit) |
| `agentvcs status` | working-tree changes, per dimension |
| `agentvcs show [COMMIT]` | one commit across all dimensions (`--trace` renders the conversation) |
| `agentvcs trace` | show the current trace source (file or auto-discovered session) |
| `agentvcs diff [A] [B]` | dimensional diff (default: parent..HEAD) |
| `agentvcs branch [NAME]` | list, or create a live branch |
| `agentvcs checkout REF` | restore the working tree from a branch/commit |
| `agentvcs rollback [REF]` | undo: restore the full prior state (the panic button) |
| `agentvcs freeze [COMMIT]` | crystallize a fluid commit into a deterministic recipe |
| `agentvcs replay [COMMIT]` | re-execute a crystallized recipe deterministically |
| `agentvcs ui` | serve a local web dashboard to *see* the evolution |

Add `--json` to any command for machine-readable output (see below). Use
`-C DIR` (like `git -C`) to run against a repo from any directory.

## See it: the local dashboard

The terminal shows you the history; `agentvcs ui` lets you *watch a mind move*.

```bash
agentvcs ui                 # opens http://127.0.0.1:8080 in your browser
```

A split view: the commit graph on the left, and for the selected commit, its
**dimensional diff** plus the agent's **inner monologue rendered as a chat** — the
exact `thinking` / `tool_use` / `tool_result` blocks that produced those lines of
code, with the goal and model that were in force. It polls, so as your agent keeps
committing in another terminal, new commits appear live.

Read-only, loopback-only, and (like the rest of agentvcs) **zero dependencies** —
just `http.server` and one self-contained HTML page. `--no-open` serves headless
and prints the URL; `--json` makes it machine-readable. The same data is available
as a small read-only JSON API under `/api/*` (see `docs/AGENT_MODE.md`).

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
  `avcs_freeze`, `avcs_replay`, `avcs_rollback`, `avcs_branch`, `avcs_checkout`,
  `avcs_trace`.

### Zero-friction trace capture (Claude Code)

Asking an agent to write its own trace file is fragile — it costs tokens and the
agent can simply forget. Instead, let agentvcs **vacuum the agent's native session
log** at commit time. Wire it once:

```bash
agentvcs init --claude-code     # or: agentvcs new my-agent --claude-code
```

which sets, in `agent.json`:

```json
"trace": { "provider": "claude-code", "auto": true },
"models": [{ "provider": "anthropic", "auto": true }]
```

Now you maintain **no** trace file. Each `agentvcs commit` reads Claude Code's
own session transcript — the real `tool_use` / `tool_result` / `thinking` blocks,
not a summary — and the model pin is detected from the model that actually ran.

```bash
agentvcs trace                  # confirm which session is hooked (+ message count, model)
agentvcs commit -m "v1"         # captures the live conversation, zero extra work
agentvcs show --trace           # the commit + the exact conversation that produced it
agentvcs freeze                 # crystallize that real, high-fidelity trace
```

Known secrets are scrubbed by default (`redact` / `redact_defaults` to tune). The
`trace` dimension is **pluggable** — `claude-code` is the first provider; any tool
that records a session (e.g. one backed by SQLite) can add another without changing
the on-disk format. See [`docs/SPEC.md`](docs/SPEC.md).

**New here?** Walk through it end-to-end in
[`docs/TUTORIAL.md`](docs/TUTORIAL.md) — build a tiny bot with Claude Code and
version every iteration, from first commit to a frozen recipe.

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

## Try the examples

A minimal first commit:

```bash
cd examples/refund-agent
agentvcs init
agentvcs commit -m "first run"
agentvcs show
```

Or run the **full agent loop** — a simulated agent that iterates, makes a
mistake, rolls it back, and freezes the result, driving agentvcs entirely in
`--json` mode:

```bash
bash examples/agent-loop-demo/run.sh
```

See [`examples/agent-loop-demo/`](examples/agent-loop-demo/) for the walkthrough,
or [`examples/recording/`](examples/recording/) for a ready-to-share screencast of
it. To put a **real** agent in front of agentvcs and score whether it adopts the
loop, use [`examples/claude-code-task/`](examples/claude-code-task/). To see the
**zero-friction trace provider** (commit captures the live Claude Code session,
no trace file), see [`examples/claude-code-trace/`](examples/claude-code-trace/).

## Scope

This repo is the **local protocol and runtime**, and it is deliberately
complete on its own — it works offline, on your machine, forever. Hosted
collaboration, a visual evolution tree, AI-assisted branch merging and fleet
observability are a separate concern and not part of this open-source core.

## License

Apache-2.0. See [LICENSE](LICENSE).
