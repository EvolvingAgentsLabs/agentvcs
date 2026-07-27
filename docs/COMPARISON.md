# Where agentvcs fits (and how it compares)

A frequent, fair question: *why another versioning layer — don't git, LangSmith, and
MLflow already cover this?* Short answer: they each cover **one** dimension of an agent's
work, in a **separate** tool, and none of them versions those dimensions **together, at
the moment the agent changed them.** agentvcs is the one atomic transaction across all of
them — and it **complements** those tools rather than replacing them.

## The gap

An autonomous agent that rewrites its own skills, prompts, and goals at run-time spans
three ops disciplines at once, and today they live in three disconnected places:

| Discipline | What it versions | Typical SOTA tool |
| --- | --- | --- |
| **DevOps** | source code | git |
| **LLMOps** | the execution trace / reasoning | LangSmith, Langfuse |
| **MLOps** | which model + params ran | MLflow, Weights & Biases |

Nothing ties them into one record. When an agent learns a skill mid-run, a
Voyager-style loop just writes it to a loose JSON file or a vector store — detached from
the code, the goal it served, the model that produced it, and the reasoning behind it.
The day the team cuts a release from git, that run-time evolution is silently overwritten.

## What agentvcs adds

One **commit** captures all of it at once — code, **goal**, **model pins**, the
**execution trace**, the sub-agent **swarm**, and a per-commit **state**
(`fluid` → `crystallized`). That single atomic transaction unifies DevOps + LLMOps +
MLOps, and unlocks operations none of the single-dimension tools can do:

| Concern | Where it lives today | agentvcs |
| --- | --- | --- |
| Source code | git ✅ | ✅ content-addressed, git-style object store |
| The **goal / intent** of an iteration | — (nowhere) | ✅ a versioned dimension; `diff` shows a goal redirect as its own event |
| Which **model + params** actually ran | MLflow / W&B registry (separate) | ✅ pinned per commit (`"auto"` fills it from the real run) |
| The **execution trace** | LangSmith / Langfuse (separate) | ✅ versioned *with* the code that produced it |
| Sub-agent **swarm** topology | — | ✅ merged node-by-node |
| **All of the above, atomically together** | — | ✅ one commit, one id |
| **Semantic** merge of divergent agent lines | git does text-only 3-way | ✅ `merge --reconcile`: 3-way code + eval-winner auto-resolve + an agent decides goal/trace |
| **Rollback** of the *full* multidimensional state | git resets code only | ✅ code+goal+models+trace, reversible, with a recorded `--reason` |
| **Trust gate**: freeze a proven solution | — | ✅ `eval → freeze → replay`: crystallize to a deterministic recipe, gated on a passing eval |
| Is the self-modification **net-positive**? | — | ✅ `price` / `health` (see [`EVOLUTIONARY_DYNAMICS.md`](EVOLUTIONARY_DYNAMICS.md)) |
| Offline, zero-dependency, local-first | varies | ✅ pure standard library, Apache-2.0 |

The headline is the **semantic** part: a plain `git merge` of two evolving agent lines
either clobbers the field-learned behavior or buries it in text conflict markers, and has
no idea what the *goal* or the *reasoning* should become. agentvcs merges each dimension
appropriately and hands the semantic decision to an agent you trust — so run-time
evolution survives the next release instead of being erased by a `git pull`.

## How it fits your existing stack

**It complements git; it does not replace it.** Keep committing code to git exactly as you
do. agentvcs versions the dimensions git structurally can't — goal, model pins, trace,
swarm — and reconciles the agent's run-time evolution back into your releases. Adoption is
incremental and low-friction:

- `agentvcs init` inside an existing repo — no migration, nothing to rip out.
- Pure standard library, zero runtime dependencies → drops into any pipeline.
- `--json` on every command + stable `error.code`s → a coding agent can drive it without
  guessing; `-C <dir>` works like `git -C`.
- An **MCP server** (`claude mcp add agentvcs -- agentvcs-mcp`) exposes the workflow to
  Claude Code / Cursor natively.

A realistic starting point: put **one** self-modifying agent's iteration loop under
agentvcs, keep your LangSmith/Langfuse dashboards and your git history, and use agentvcs
for the thing they can't do — versioning and reconciling the four dimensions together.

## What agentvcs is *not*

Being honest about the boundaries (they're a feature, not a hedge):

- **Not a hosted observability dashboard.** It reconstructs the operational frame
  (`runtime` / `watch`) and ships a small local UI, but fleet observability *at scale* is
  explicitly out of the open-source core — keep Langfuse/LangSmith for that.
- **Not a model registry or experiment tracker.** It pins the model + params that ran on
  each commit; it does not store or serve model weights/artifacts — keep MLflow/W&B.
- **Not a static-analysis or dependency gate.** It versions and reconciles; it does not,
  by itself, prove an edit won't break a dependency graph before the commit. In the
  Evolving Agents Labs ecosystem that role is played by separate, composable tools (see
  below) — agentvcs is deliberately unopinionated about which you use.

## Ecosystem (separate, composable tools)

agentvcs is one layer of a larger loop; these are **distinct projects** it interoperates
with, not features baked into it:

- [**odyssey**](https://github.com/lovellai-dev/odyssey) — a robotics mission runtime; the
  bundled [`odyssey` trace provider](../examples/odyssey/) versions a mission *outcome*
  (success rate, per-checkpoint metrics, grade) alongside the code that produced it.
- [**skill-map**](https://github.com/crystian/skill-map) — a graph-based skill/dependency
  gate used *alongside* agentvcs to catch a broken edit before it's committed.
- [**evolving-robot**](https://github.com/EvolvingAgentsLabs/evolving-robot) — a 2D robot
  that evolves its own skills, versioned by agentvcs, orchestrated by odyssey, gated by
  skill-map. Dogfooding that loop is what surfaced the odyssey provider.

The design principle throughout: agentvcs owns the **versioning and reconciliation**
transaction, and stays out of the business of the tools around it.

## See also

- [`../README.md`](../README.md) — the overview and quickstart.
- [`EVOLUTIONARY_DYNAMICS.md`](EVOLUTIONARY_DYNAMICS.md) — the diagnostics that measure
  whether an agent's self-modification is actually working, and the honest scope boundary
  between a VCS and a live harness.
- [`DEMOS.md`](DEMOS.md) — runnable, narrated walkthroughs.
