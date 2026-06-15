# Merging minds, not just code

### A smart `merge` for agentvcs — built *and* powered by nanoLoop

When a fleet of agents builds software, the hardest merge isn't the code. Git
merges *text*. But when two agent branches diverge, the thing that actually
matters — the **reasoning**: what each branch tried, what it learned, which
dead-ends it already burned tokens exploring — lives in the message trace, and
nothing merges that. The agent that picks up the merged branch inherits the
files but not the lessons. It re-derives, re-debates, and often re-walks a path a
sibling branch already proved was wrong. Working-memory amnesia.

This post is about closing that gap, and about two projects that fit together to
do it.

Both ideas here are **[Ismael Faro](https://github.com/ismaelfaro)'s**:

- **[agentvcs](https://github.com/EvolvingAgentsLabs/agentvcs)** — "git for
  agents." Version control where every commit captures four dimensions at once —
  **code, goal, models, and the message trace** — plus a state (`fluid` while the
  agent is still evolving, `crystallized` once you freeze a trusted, deterministic
  recipe). I'm working on implementing it at EvolvingAgentsLabs.
- **[nanoLoop](https://github.com/ismaelfaro/nanoLoop)** — a tiny autonomous
  engineering harness: **Plan → Build → Review → Test → Ship**, each phase a
  subagent with isolated context, sandboxed and gated.

The fun part: nanoLoop **built** this feature in agentvcs, and then became the
**brain that runs it**.

---

## What we added

agentvcs already stored a two-parent–capable commit model, so a real merge fit
without a schema change. Two features went in:

**1. `agentvcs merge <branch>` — a multidimensional, three-way merge.**
It finds the merge-base across the full parent DAG, does a line-level three-way
merge of the code (git-style conflict markers when hunks overlap), unions the
model pins, and writes a genuine two-parent merge commit.

**2. `agentvcs log --reasoning` — a decision-aware history.**
It reads goal transitions, eval verdicts, and a new *durable* rollback ledger
(`.agentvcs/rollbacks.jsonl`) and renders the commit history as a **decision
ledger**: what was attempted, what passed, what got rolled back and why. The
first thing a fresh agent should run, so it inherits hindsight instead of
repeating a predecessor's mistakes.

---

## The key design choice: mechanism vs. intelligence

agentvcs's whole promise is **zero runtime dependencies, pure Python stdlib,
fully auditable**. Reconciling two reasoning traces into one coherent narrative
is an inherently *LLM* job. Putting a model call inside agentvcs would break that
promise.

So the merge is split along the seam the project already uses for `replay --exec`:

- **agentvcs (the mechanism, deterministic):** finds the base, merges the code
  tree, unions models, and assembles a **reconciliation bundle** — base / ours /
  theirs goals + traces + code diffs + conflicts. With no helper, it ships a
  deterministic fallback (a mechanical merge marker; both parent traces stay
  reachable, nothing is lost).
- **An external reconciler (the intelligence, probabilistic):** when you pass
  `--reconcile <CMD>`, agentvcs pipes the bundle to that process on stdin and
  reads back `{goal, trace, notes}` on stdout. The core never imports an LLM.

That `CMD` is where **nanoLoop plugs in** — it ships a first-class
`nanoloop reconcile` subcommand that reads the bundle on stdin and writes the
Consolidated Knowledge Trace on stdout, using its own OpenRouter model layer.

```
agentvcs merge feature-sql --reconcile "nanoloop reconcile nanoLoop/.env"
```

---

## Does it actually work? A worked example.

Two branches diverge from a stub `store()` for a refund-ticket router:

- **`feature-sql`** — chose SQL. Spent 15 turns getting a validated schema right.
  Trace records the win *and* the scar: *poor write throughput under burst; INSERTs
  serialize on the db lock.*
- **`feature-nosql`** — chose append-only NoSQL. Trace records: *excellent burst
  throughput, no lock* — and the gap: *no schema validation; malformed tickets get
  written.*

The code conflicts (both rewrote `store.py`). A normal merge stops there. But we
want the **minds** reconciled regardless, so we merge *through* the conflict
(`--force`) with nanoLoop as the reconciler:

```
agentvcs merge feature-sql --reconcile "nanoloop reconcile nanoLoop/.env" --force
```

Here is the Consolidated Knowledge Trace it wrote into the merge commit —
excerpted and trimmed for length (the run is fully reproducible from the example
in this folder):

> **Merged goal:** *Persist refund tickets durably with both schema validation and
> high write throughput.*
>
> **[SYSTEM]** Reconciling 'feature-nosql' and 'feature-sql'. Both evolved from a
> stub store() with undecided backend. NoSQL chose append-only JSONL for burst
> throughput but lacked schema validation. SQL implemented full validation
> (id/amount/reason) but suffered serialized INSERTs under burst load. The merged
> approach must retain SQL-style validation while achieving NoSQL-level write
> throughput — likely via a write-ahead or buffered pattern. **Dead-ends to avoid:
> pure unvalidated NoSQL append (data integrity risk), pure synchronous SQL INSERT
> under burst (lock contention).**
>
> **[ASSISTANT]** Retained from NoSQL: append-only writes give excellent burst
> throughput with no lock contention. Lesson: do not block writers on a single DB
> lock during burst ingestion.
>
> **[ASSISTANT]** Retained from SQL: the schema validation for id/amount/reason is
> proven after 15 turns. Malformed tickets must be rejected before persistence —
> the critical gap in the NoSQL branch. Merged design: validate upfront (SQL
> logic), then write to an append-only store (NoSQL pattern) or a SQL table fed by
> an async queue to decouple validation from write serialization.

It didn't concatenate two chat logs. It **synthesized**: picked the winner per
concern, kept the lesson from the loser, and — crucially — wrote down the
dead-ends so the next agent won't re-explore them. That's the whole point.

---

## Status (honestly)

- Both features are implemented in agentvcs: **106 tests pass** (86 pre-existing,
  zero regressions, + 20 new).
- The merge, conflict markers, the freeze gate that blocks on unresolved
  conflicts, the `--reconcile` seam, and the decision-aware log are all
  smoke-tested end-to-end.
- nanoLoop ships a first-class **`nanoloop reconcile`** subcommand, so the merge
  command above works verbatim. (A from-scratch reference reconciler also lives in
  this folder, `reconcile.py`, for anyone who wants to wire a different brain.)
- Not yet done: conflict-aware *code* synthesis (the reconciler reasons about the
  conflict but a human/agent still resolves `store.py`), and surfacing the
  *abandoned* commit's decision text in `log --reasoning` (the data is on disk;
  it's a rendering gap).

The loop is satisfying: the harness that *builds* the merge is the same one that
*performs* the knowledge reconciliation. nanoLoop writes the mechanism; agentvcs
gives it a durable, multidimensional place to put the result.

---

*agentvcs and nanoLoop are both ideas by [Ismael Faro](https://github.com/ismaelfaro).
agentvcs: https://github.com/EvolvingAgentsLabs/agentvcs ·
nanoLoop: https://github.com/ismaelfaro/nanoLoop*
