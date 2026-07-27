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

## Goal

Self-modifying agents are easy to build and hard to trust. An autonomous agent doesn't
just *run* your system — in the field it **rewrites** it (a new skill, an edited tool, a
spawned sub-agent, a redirected goal), and **git never sees any of it**. The next release
overwrites the field-learned adaptations and the reasoning behind them.

**agentvcs's goal is to make that run-time evolution first-class and trustworthy:**

1. **Capture** every iteration as one commit across code + goal + models + trace + swarm.
2. **Prove & freeze** what works into a deterministic, replayable recipe.
3. **Reconcile** the agent's run-time line back into your git releases instead of losing it.
4. **Measure** whether the self-modification is actually improving — not just changing.

Pure-Python standard library, zero runtime dependencies, Apache-2.0. It **complements**
git — it doesn't replace it ([how it compares](docs/COMPARISON.md)).

```
 design-time line   ●──────●──────●   what your team develops & releases under git
                     \              \
                      \              ▼  agentvcs merge --reconcile <agent>
                       \            ◆  one reconciled history
                        \          ▲
 run-time line          ●────●────●   what the autonomous system changed about itself
```

## One commit, many dimensions

Every iteration is one commit across **four dimensions** plus a **state** — and, when the
agent has them, a sub-agent **swarm** and the runtime **frame**:

```
            ┌─────────── one commit ───────────┐
   code  →  │  tree     goal     models   trace │   state: fluid | crystallized
            └───────────────────────────────────┘
```

- **`fluid`** — still evolving: high-temperature models, code/skills/prompts/goals mutating
  between iterations. Powerful, expensive, non-deterministic.
- **`crystallized`** — a solution you trust, *frozen*: models pinned to temperature 0, the
  trace compiled into a replayable recipe. Cheap, stable, deterministic (`agentvcs freeze`,
  gated by a passing `eval`).

`agentvcs diff` tells you *which dimension* moved — a goal redirect and a code change are
distinguishable events, not one opaque text diff:

```
705b2fb..1d4bd90
  code
    ~ app.py
  goal
    from: Resolve refund requests autonomously
    to:   Resolve refund requests with fraud checks
```

The **heart** is `merge --reconcile`: a plain `git merge` clobbers field adaptations or
buries them in conflict markers and has no idea what the *goal* or *reasoning* should
become. agentvcs merges each dimension appropriately — three-way merge for code/skills
(eval-winner auto-resolves conflicting hunks first), union for model pins, node-by-node for
the swarm — and hands the semantic decision (goal + trace) to an agent you trust, which can
even return the conflict-free `resolved_files` agentvcs then writes.

## Real demos

Runnable, narrated, and on the web — every number comes from a real `agentvcs eval`, nothing
faked. **[Live demos ↗](https://evolvingagentslabs.github.io/agentvcs/demos/)** ·
reproduction guide [`docs/DEMOS.md`](docs/DEMOS.md).

- **Business cases — plain English, no math on screen**
  (`bash examples/business-cases/run.sh`). Five everyday situations, each ending in a
  one-line call: a support bot that quietly gets worse every week (*roll back*), a client
  fork nobody merged (*merge it before it rots*), a prompt stuffed with context that changes
  nothing (*trim it, save cost*), one bad fact poisoning a shared-memory fleet (*verify N% of
  reads*).
- **Evolution diagnostics — the technical companion**
  (`bash examples/evolution-diagnostics/run.sh`). The same five with the real numbers and
  the theory; every claim asserted against `--json`.
- **Self-evolving eve merge** (`bash examples/eve-evolve-merge/demo.sh`). A
  [Vercel **eve**](https://vercel.com/eve) agent rewrites its own skill and spawns a
  sub-agent at run-time while the team evolves the same files in git — and `merge` fuses
  both.
- **The full agent loop** (`bash examples/agent-loop-demo/run.sh`). A simulated autonomous
  agent driving commit → eval → **rollback (with a recorded reason)** → freeze end to end.

More in [`examples/README.md`](examples/README.md).

## The math & models behind it

Two kinds of "model" sit under agentvcs.

**The data model** — a git-style content-addressed object store with typed objects
(`commit` / `tree` / `goal` / `modelpin` / `trace` / `crystal`), a per-commit `fluid ↔
crystallized` state machine, and a three-way *semantic* merge over the merge-base
([`docs/SPEC.md`](docs/SPEC.md)). Model pins are provider-agnostic (Anthropic, Google,
Qwen, …); `"auto"` fills the pin from the model that actually ran, so it can't drift.

**The mathematical models** — because agentvcs owns the whole *recorded lineage* (a
population of variants over time, each with an eval score), it can measure things a code VCS
can't. These are exact, standard-library computations over the commit graph — not vibes:

| Diagnostic | Model | Question it answers |
| --- | --- | --- |
| `price` | **Price equation** `w̄·Δz̄ = Cov(w,z) + E[w·Δz]` | Is improvement from *selecting* between branches, or *editing* within a lineage? |
| `price` (threshold) | **Eigen error catastrophe** (`μL < ln σ`) | Is self-editing losing information faster than selection recovers it? |
| `health` | **Critical slowing down** (lag-1 autocorrelation + variance) | Is a collapse coming *before* the mean score moves? |
| `health` / `branch` | **Muller's ratchet** | Is an unmerged branch a decaying asexual lineage that needs recombination (`merge`)? |
| `infobits` | **Kelly / Kussell–Leibler & channel capacity** (`I(context; action)` in bits) | How much can more context retrieval actually buy — where's the compression headroom? |
| `contain` | **Branching process** `R₀ = n·p` | Will a poisoned shared-memory entry spread, or die out? What verification rate contains it? |

The honest scope: these measure a population of variants across time — the object a **version
control system** owns. Controller/fleet math (throughput control, sampling, scheduling)
belongs to a live harness and is deliberately *out of scope*. Full derivations, mappings and
the scope boundary: [`docs/EVOLUTIONARY_DYNAMICS.md`](docs/EVOLUTIONARY_DYNAMICS.md).

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
agentvcs diff                  # dimensional diff: code vs goal vs models vs trace
agentvcs eval && agentvcs freeze   # prove it, then crystallize (freeze is gated on the eval)
agentvcs price                 # is the self-modification net-positive?
```

Declare the non-code dimensions in `agent.json`:

```json
{
  "goal": "Resolve refund requests autonomously",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8", "params": { "temperature": 1.0 } }],
  "trace": { "provider": "claude-code", "auto": true },
  "swarm": { "refund-verifier": { "role": "verify a refund", "skill_file": "agent/subagents/refund-verifier.md" } },
  "eval": { "command": "pytest -q", "runs": 3 },
  "state": "fluid"
}
```

`freeze` refuses to crystallize a commit that hasn't passed its `eval` (`EVAL_FAILED`);
`freeze --force` past a failure marks the recipe `verified: false` — never a silent lie.
`agentvcs rollback --reason "…"` restores the full prior state and records *why* in a durable
ledger. Secrets in captured traces are `[REDACTED]` by default.

## Commands

| command | what it does |
|---|---|
| `agentvcs new DIR` / `init` | scaffold / create a repository (`--claude-code` / `--qwen-code` / `--eve` wire trace capture) |
| `agentvcs commit -m MSG` | snapshot code + goal + models + trace |
| `agentvcs log` / `status` / `show` / `diff` | history / working-tree changes / one commit / dimensional diff |
| `agentvcs branch` / `checkout REF` | list/create a live branch / restore the working tree |
| `agentvcs merge BRANCH` | multidimensional merge; `--reconcile CMD` hands goal+trace+conflicts to an agent; `--target-goal` directs it |
| `agentvcs rollback [REF] --reason TEXT` | undo: restore the full prior state, with a recorded justification (the panic button) |
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

- **Demos** — plain-English business stories + the technical companion:
  [live demos](https://evolvingagentslabs.github.io/agentvcs/demos/) ·
  [`docs/DEMOS.md`](docs/DEMOS.md)
- **The math & models** — derivations, mappings, scope boundary:
  [`docs/EVOLUTIONARY_DYNAMICS.md`](docs/EVOLUTIONARY_DYNAMICS.md)
- **How it compares** — next to git, LangSmith/Langfuse and MLflow/W&B, and what it is *not*:
  [`docs/COMPARISON.md`](docs/COMPARISON.md)
- **Tutorial / Spec / Agent contract** — [`docs/TUTORIAL.md`](docs/TUTORIAL.md) ·
  [`docs/SPEC.md`](docs/SPEC.md) · [`docs/AGENT_MODE.md`](docs/AGENT_MODE.md)

## Scope

This repo is the **local protocol and runtime** — complete on its own, offline, forever. It
**complements** your existing stack (git, LangSmith/Langfuse, MLflow/W&B) rather than
replacing any of it. Hosted collaboration and fleet observability at scale are a separate
concern, not part of this open-source core.

## License

Apache-2.0. See [LICENSE](LICENSE).
