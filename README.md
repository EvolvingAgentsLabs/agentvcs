# agentvcs

<p align="center">
  <img src="docs/img/agentvcs.jpg" alt="Two branches diverge and merge, sealed once the eval passes" width="100%">
</p>

[![CI](https://github.com/EvolvingAgentsLabs/agentvcs/actions/workflows/ci.yml/badge.svg)](https://github.com/EvolvingAgentsLabs/agentvcs/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue.svg)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Version control for software that *evolves while it runs*.**

> The open-source **"git for agents"**: version an agent's **code, skills, goals, models,
> traces & sub-agent swarm together** — and merge its **autonomous evolution back into
> your releases, intelligently.**

![agentvcs: a v1 agent splits into a run-time line that evolves itself autonomously and a design-time line developed under version control, then agentvcs merges both back into one reconciled v4](docs/media/agentvcs-evolution.gif)

<p align="center">
  <img src="docs/media/agentvcs-merge.gif" alt="Two branches of commits advance independently — one in ink, one in indigo — then converge on a diamond that seals the merge, and a single thicker line continues carrying nodes from both" width="640">
</p>
<p align="center"><sub>The merge, in seven seconds. <a href="docs/media/agentvcs-merge.mp4">MP4</a> · generated with <code>gemini-omni-flash-preview</code></sub></p>

## The problem

You build an agent the modern way — **skills as markdown, tools as code, prompts in
files**, all under git. But an autonomous agent doesn't just *run* that system; in the
field it **rewrites** it: a new skill here, an edited tool there, a spawned sub-agent, a
redirected goal — adapting to what it learns from real traffic.

**Git never sees any of it.** That run-time evolution lives only inside the running
process. The day your team cuts a release from `main`, you **overwrite it** — the
field-learned adaptations, and the reasoning that produced them, are gone.

So two lines now evolve in parallel, and losing either loses half the system:

```
 design-time line   ●──────●──────●   what your team develops & releases under git
                     \              \
                      \              ▼  agentvcs merge --reconcile <agent>
                       \            ◆  one reconciled history
                        \          ▲
 run-time line          ●────●────●   what the autonomous system changed about itself
```

agentvcs versions **both** and reconciles them — instead of letting a `git pull` erase
what the agent learned. Pure-Python stdlib, zero runtime dependencies, Apache-2.0.

## The core idea: one commit, many dimensions

Every iteration is one commit across **four dimensions** plus a **state** — and, when
the agent has them, a sub-agent **swarm** and the runtime **frame**:

```
            ┌─────────── one commit ───────────┐
   code  →  │  tree     goal     models   trace │   state: fluid | crystallized
            └───────────────────────────────────┘
```

- **`fluid`** — still evolving: high-temperature models, code/skills/prompts/goals
  mutating between iterations. Powerful, expensive, non-deterministic.
- **`crystallized`** — a solution you trust, *frozen*: models pinned to temperature 0,
  the trace compiled into a replayable recipe. Cheap, stable, deterministic
  (`agentvcs freeze`).

`agentvcs diff` tells you *which dimension* moved — a goal redirect and a code change are
now distinguishable events, not one opaque text diff:

```
705b2fb..1d4bd90
  code
    ~ app.py
  goal
    from: Resolve refund requests autonomously
    to:   Resolve refund requests with fraud checks
```

## The heart: reconcile the two lines (agent-driven merge)

A plain `git merge` would clobber the field adaptations or bury them in conflict markers,
and has no idea what the *goal* or the *reasoning* should become. agentvcs merges
**multidimensionally** and hands the semantic part to an agent:

```bash
# main    = your new release       (design-time line, developed under version control)
# runtime = what agentvcs captured (run-time line: skills/tools/prompts the system rewrote)
agentvcs checkout runtime
agentvcs merge main --reconcile "claude -p reconcile"   # any agent/command you trust
```

- **code · skills · tools · prompts** → real **three-way merge** against the merge-base.
  When one side has a higher **verified eval score**, conflicting hunks resolve to it
  automatically, *per-hunk*, before the agent is asked.
- **models** → pins are **unioned**.
- **goal · trace** → *not* merged textually. agentvcs builds a reconciliation **bundle**
  (`base`/`ours`/`theirs` + goals, traces, eval/cost metrics, and any unresolved conflict
  text) and pipes it to your `--reconcile` agent, which returns the reconciled
  `{goal, trace, notes}` — and optionally **`resolved_files`**, the conflict-free code it
  synthesized, which agentvcs writes for you.
- **swarm** → sub-agent topology (created/evolved/retired at run-time) is merged
  node-by-node.

The result is a two-parent merge commit that keeps the field-learned behavior **and** the
new release. Add **`--target-goal "…"`** to direct the merge toward a new objective.
Without `--reconcile`, agentvcs falls back to a safe mechanical union.

> See it end-to-end on a [Vercel **eve**](https://vercel.com/eve) agent that rewrites its
> own skill and spawns a sub-agent at run-time while the team evolves the same files in
> git: `bash examples/eve-evolve-merge/demo.sh`.

## Install

```bash
git clone https://github.com/EvolvingAgentsLabs/agentvcs
cd agentvcs && pip install -e .   # not on PyPI yet
```

> `avcs` is a built-in shorthand for `agentvcs` — every command works with either name.

## Quickstart

```bash
agentvcs new my-agent          # scaffold a project pre-wired for agents (agent.json, AGENTS.md, CC skill, MCP)
cd my-agent
agentvcs commit -m "initial fluid agent"
agentvcs log                   # evolution history (state + goal per commit)
agentvcs diff                  # dimensional diff: code vs goal vs models vs trace
agentvcs branch experiment     # fork the execution, not just the text
agentvcs merge experiment --reconcile "claude -p reconcile"
```

Declare the non-code dimensions in `agent.json`:

```json
{
  "goal": "Resolve refund requests autonomously",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8", "params": { "temperature": 1.0 } }],
  "trace": { "provider": "claude-code", "auto": true },
  "swarm": { "refund-verifier": { "role": "verify a refund", "skill_file": "agent/subagents/refund-verifier.md" } },
  "state": "fluid"
}
```

## Trust what you freeze: eval → freeze → recall

`fluid → crystallized` is only worth something if "frozen" means "proven", so `freeze`
is **gated by an eval** you declare in `agent.json`:

```json
"eval": { "command": "pytest -q", "runs": 3 }
```

```bash
agentvcs eval                          # run the check, record the score on this commit
agentvcs freeze                        # crystallize — ONLY if the eval passes (EVAL_FAILED otherwise)
agentvcs recall "implement add" --verified-only   # have I already proven this?
agentvcs replay <commit>               # re-run the frozen recipe for ~$0
```

A flaky check (`"runs": 5`) must pass **all** runs; `freeze --force` past a failure marks
the recipe `verified: false` — never a silent lie. Secrets in the captured trace are
`[REDACTED]` by default.

## Is the evolution actually working? (`price` / `health`)

Because agentvcs owns the whole lineage — every variant as a commit with an eval
score attached — it can answer something a code VCS never could: *is this
self-improvement loop still net-positive?* `agentvcs price` runs the **Price
equation** over the commit graph and splits the gain into **selection** (choosing
well between branches, `Cov(w,z)`) vs **transmission** (editing well within a
lineage, `E[w·Δz]`). When the transmission term goes negative and outruns selection,
you've hit the **Eigen error catastrophe** — the loop is losing information faster
than selection recovers it — and `price` says so, without you estimating a single
mutation rate.

```bash
agentvcs price                 # selection vs transmission + the error-catastrophe verdict
agentvcs health                # + critical-slowing-down early warning + Muller's-ratchet load
```

`health` folds in two more signals over data already on disk: **critical slowing
down** (rising variance/autocorrelation in the score series flags a collapse before
the mean moves) and **Muller's ratchet** (a long, unmerged branch is a condemned
asexual lineage — `merge` is the recombination that reconstitutes it). Declare an
`"editable": ["skills/", "prompts/…"]` surface in `agent.json` and the error bound is
computed against *that* size, not the whole spec — the engineering answer to "how
much can I let the agent rewrite itself?".

> **See it, no math required.** Five everyday business stories — a support bot that
> quietly gets worse every week, a fork nobody merged back, wasted context, a poisoned
> shared memory — each ending in a one-line call:
> **[live demos](https://evolvingagentslabs.github.io/agentvcs/demos/)** ·
> `bash examples/business-cases/run.sh` · guide in [`docs/DEMOS.md`](docs/DEMOS.md).

Two more diagnostics fall out of the same recorded lineage. `agentvcs infobits`
estimates how many **bits** your decisions actually carry (`H(action)` and
`I(prev; next)` over the trace's tool selections) — the Kelly/Kussell-Leibler ceiling
on what extra context retrieval can buy, i.e. your compression headroom. `agentvcs
contain` runs the branching-process test `R₀ = n·p` for shared-memory poisoning (fan-out
`n` from the subagent/swarm topology, escape rate `p` from the failed-eval fraction) and
tells you the **verification rate** that keeps corruption self-limiting. Design notes:
[`docs/EVOLUTIONARY_DYNAMICS.md`](docs/EVOLUTIONARY_DYNAMICS.md).

## The runtime your agent can't see

agentvcs vacuums your session log, so it can reconstruct the operational frame your closed
runtime hides — and put a number on it:

```bash
agentvcs runtime     # budget $ · context-window pressure · compactions · model routing · tool/subagent usage
agentvcs watch       # live, redraws like top
```

Cross-runtime: the same frame reconstructs from `claude-code`, `qwen-code`, `vercel-eve`
and `anthropic-managed` sessions. Wire it into Claude Code once with
`agentvcs init --claude-code --runtime` (live status line + a commit per turn). See
[`docs/AGENT_MODE.md`](docs/AGENT_MODE.md).

## Commands

| command | what it does |
|---|---|
| `agentvcs new DIR` | scaffold a new agent project pre-wired with agentvcs |
| `agentvcs init` | create a repository (`--claude-code` / `--qwen-code` / `--eve` wire trace capture) |
| `agentvcs commit -m MSG` | snapshot code + goal + models + trace |
| `agentvcs log` / `status` | evolution history / working-tree changes, per dimension |
| `agentvcs show [COMMIT]` | one commit across all dimensions (`--trace` renders the conversation) |
| `agentvcs diff [A] [B]` | dimensional diff (default: parent..HEAD) |
| `agentvcs branch` / `checkout REF` | list/create a live branch / restore the working tree |
| `agentvcs merge BRANCH` | multidimensional merge; `--reconcile CMD` hands goal+trace+conflicts to an agent; `--target-goal` directs it |
| `agentvcs rollback [REF]` | undo: restore the full prior state (the panic button) |
| `agentvcs eval` / `freeze` / `replay` / `recall` | the trust gate: prove → crystallize → re-run → find |
| `agentvcs price` / `health` | is the evolution *working*: selection-vs-transmission + error-catastrophe & ratchet warnings |
| `agentvcs infobits` / `contain` | information value of context (bits) · shared-memory poisoning containment (R₀) |
| `agentvcs runtime` / `budget` / `context` / `statusline` / `watch` | the operational frame your runtime hides |
| `agentvcs ui` | serve a local web dashboard to *watch* the evolution |
| `agentvcs soul` / `verify` / `fleet` | optional Soul/DeSoc layer (see below) |

Add `--json` to any command for machine-readable output; stable `error.code`s let agents
recover programmatically. An **MCP server** ships too: `claude mcp add agentvcs -- agentvcs-mcp`.

## Optional layers

- **Soul / DeSoc** (`agentvcs init --with-soul`) — off by default, zero crypto surface
  otherwise. Gives each instance an **Ed25519 Soul** so every commit is signed
  (forge-proof provenance), mints **Soulbound Tokens** on a verified `freeze`, and selects
  maximally-diverse fleets via DeSoc correlation discounting. Full vision:
  [`docs/papers/souls-of-silicon.md`](docs/papers/souls-of-silicon.md).
- **Corporate/legal layer** (`agentvcs init --corporate`) — opt-in audit log + signed
  approvals for governed deployments.

## Learn more

- **Demos** — five business stories in plain English + the technical companion, both
  runnable and on the web: [live demos](https://evolvingagentslabs.github.io/agentvcs/demos/)
  · reproduction guide [`docs/DEMOS.md`](docs/DEMOS.md)
- **Tutorial** — build a tiny bot with Claude Code and version every iteration:
  [`docs/TUTORIAL.md`](docs/TUTORIAL.md)
- **Spec** — the on-disk format (content-addressed objects, like git's, with `commit` /
  `tree` / `goal` / `modelpin` / `trace` / `crystal` types): [`docs/SPEC.md`](docs/SPEC.md)
- **Examples** — every demo indexed in [`examples/README.md`](examples/README.md), incl.
  the self-evolving eve merge ([`examples/eve-evolve-merge/`](examples/eve-evolve-merge/)).

## Scope

This repo is the **local protocol and runtime** — complete on its own, offline, forever.
Hosted collaboration and fleet observability at scale are a separate concern, not part of
this open-source core.

## License

Apache-2.0. See [LICENSE](LICENSE).
