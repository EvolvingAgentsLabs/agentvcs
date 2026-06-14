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

![agentvcs surfacing the runtime frame, then gating freeze on a passing eval](examples/recording/runtime-trust.gif)

*A real run: `agentvcs runtime` reconstructs the operational frame your runtime
hides — dollar cost, context pressure, model routing, real tool usage — from your
own session log. Then the trust loop: `freeze` refuses a buggy `add()`
(`EVAL_FAILED`), and once the eval passes it crystallizes a recipe stamped
`verified` that `recall` can replay for ~$0. Numbers are reconstructed, not staged.*

## The runtime your agent can't see

Because agentvcs already vacuums your session log, it can reconstruct the
**operational frame your closed runtime keeps to itself** — and put a number on
it. Run it against your *own* live session:

```bash
agentvcs runtime           # the whole frame, reconstructed from your session log
```

```
runtime frame  (what your runtime hides)
  turns:     11
  budget:    27208 tok  (in 24306 / out 2902)  $0.5822 / ceiling $2.0000
  context:   41293/200000 tok  (20.6%)  compactions=0
  model routing:
    claude-opus-4-8: 11 turns, 24306+2902 tok, $0.5822
  tools:     Read×3, Bash×2
```

The **dollar cost** of this session, how **full your context window** is, how many
times it was silently **compacted** (history dropped), which **models** actually
ran, your real **tool usage**, and any **subagent fan-out** — none of which your
runtime shows you. It's reconstructed from the log you already have, not estimated.

```bash
agentvcs budget            # token + dollar accounting vs a ceiling you set
agentvcs context           # context-window pressure + compaction count
agentvcs statusline        # one compact line for ~/.claude/settings.json statusLine
agentvcs watch             # live, redraws like top
```

Turn it on with `agentvcs init --runtime` (or `--claude-code`), and set a ceiling
and the window for your model in `agent.json`:

```json
"budget": { "ceiling_usd": 2.0, "windows": { "opus": 1000000 } }
```

> The window table defaults to 200k; if `context` reads **>100%** your model's real
> window just isn't in the table yet (e.g. Opus's 1M variant). Set it as above.

This is **cross-runtime**: the same frame reconstructs from a `qwen-code` session
(`agentvcs init --qwen-code`), so it isn't tied to Claude Code.

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

## Trust what you freeze: eval → freeze → recall

`fluid → crystallized` is only worth something if "frozen" means "proven". So
`freeze` is **gated by an eval**. Declare the check in `agent.json`:

```json
"eval": { "command": "python3 -c 'import app; assert app.add(2,2)==4'", "runs": 1 }
```

```bash
agentvcs eval              # run the check, record the score on this commit
agentvcs freeze            # crystallize — but ONLY if the eval passes
```

If the code is wrong, `freeze` refuses (`EVAL_FAILED`) instead of minting a
recipe you can't trust. Pass it, and the recipe is stamped `verified: true`. The
gate is honest under pressure: a flaky check (`"runs": 5`) must pass **all** runs,
and `freeze --force` past a failure marks the recipe `verified: false` — never a
silent lie. Secrets in the captured trace are `[REDACTED]` by default before they
ever hit the object store.

Then close the loop — *don't re-derive what you've already proven*:

```bash
agentvcs recall "implement an add function"   # have I solved this before?
#   45922c00d97d  score 0.33  ✓verified  implement a correct add(a,b)
#   -> replay the top hit:  agentvcs replay 45922c00d97d
agentvcs recall "..." --verified-only         # only recipes that passed their gate
agentvcs replay 45922c00d97d                  # re-run the frozen recipe for ~$0
```

A frozen, verified recipe is a cache hit: deterministic, cheap, and trustworthy
because it carries the proof that it worked.

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
| `agentvcs eval [COMMIT]` | run `agent.json`'s eval and record the score |
| `agentvcs freeze [COMMIT]` | crystallize a fluid commit into a deterministic recipe (eval-gated) |
| `agentvcs replay [COMMIT]` | re-execute a crystallized recipe deterministically |
| `agentvcs recall GOAL` | rank frozen recipes matching a goal — replay instead of re-deriving |
| `agentvcs runtime` | the operational frame your runtime hides (budget/context/routing/tools/subagents) |
| `agentvcs budget` | token + dollar accounting vs a ceiling |
| `agentvcs context` | context-window pressure + compaction count |
| `agentvcs statusline` / `watch` | one compact status line / live `top`-style readout |
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

![agentvcs capturing a live Claude Code session](examples/recording/cc-trace.gif)

*`commit` pulls the conversation straight from your live session — the actual
`thinking` / `tool_use` / `tool_result` — and `show --trace` puts it next to the
code. You never write a trace file.*

Known secrets are scrubbed by default (`redact` / `redact_defaults` to tune). The
`trace` dimension is **pluggable** — `claude-code` and `qwen-code` ship today
(`agentvcs init --qwen-code` wires the latter), and any tool that records a session
(e.g. one backed by SQLite) can add another without changing the on-disk format.
The same trace and the same runtime frame reconstruct identically across providers,
so nothing here is tied to one runtime. See [`docs/SPEC.md`](docs/SPEC.md).

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
