# Evolutionary dynamics for agentvcs — design & status

*A mapping of the "control-theory / biophysics for harnesses" brainstorm onto
agentvcs specifically. Tiers 1–2 are **shipped** (`src/agentvcs/dynamics.py`,
commands `agentvcs price` / `agentvcs health`, ratchet warnings on `agentvcs
branch`, MCP tools `avcs_price` / `avcs_health`); Tier 3 is documented and partly
deferred by design (see below).*

## The one distinction that scopes everything

Most of the brainstorm targets the **harness** — the thing that *runs* agents:
antithetic control of throughput, stochastic resonance in sampling temperature,
the marginal-value-theorem stopping rule, FBA budget allocation, Kleiber fleet
scaling. Those regulate a live controller.

**agentvcs is not the controller. It is the version control system over the
evolving commit graph.** It owns something no harness does: the *recorded lineage* —
every iteration as a commit across `code / goal / models / trace`, with an eval
score attributed per commit (`.agentvcs/evals/<oid>.json`), branches, merge-bases,
and the trace that caused each change.

That ownership is decisive. The evolutionary and information-theoretic ideas in the
brainstorm are **measurements over a population of variants across time** — which is
exactly the object agentvcs already stores and nothing else does. So the ideas that
"apply to agentvcs" are not a random subset; they are precisely the ones whose
natural home is a commit graph with fitness attached.

Everything else — the controller math — is deliberately **out of scope for this
repo** (see the README scope note: *"Hosted collaboration and fleet observability at
scale are a separate concern, not part of this open-source core"*). Listing what we
are **not** doing, and why, is the most load-bearing part of this plan: it keeps a
VCS from metastasizing into a scheduler.

All new surfaces below must honor the non-negotiables in `AGENTS.md`: **zero runtime
deps (stdlib only), stable `--json` contract, stable `error.code`s, format changes
are spec changes, reversibility.** Every one of the proposals is a *pure function
over data agentvcs already has* plus a CLI/MCP surface — no new dependencies, no new
stored-object shapes except where explicitly noted.

---

## Tier 1 — Core fit, high payoff. Build these.

These three consume only the commit graph + the eval side-table. They are the
flagship: agentvcs becomes the first VCS that can *tell you whether your
self-improvement loop is actually improving*.

### 1.1 Price equation — the metric a VCS of agents is missing

**Idea (#4).** `w̄·Δz̄ = Cov(wᵢ, zᵢ) + E[wᵢ·Δzᵢ]`. The change in a trait
decomposes into **selection between variants** (the covariance of fitness with the
trait) plus **transmission within a lineage** (fitness-weighted change during
inheritance).

**Why it's the right fit.** This answers the question a coding agent using agentvcs
actually has and cannot otherwise answer: *"of the improvement I see, how much came
from choosing well between branches versus editing well within a branch?"* A `git`
log cannot separate those. agentvcs can, because it has both the sibling structure
(branches off a common base) and per-commit fitness (eval score).

**Mapping.**
- Population at a branch point = the set of child commits sharing a parent
  (siblings), plus their descendants along each line.
- Fitness `wᵢ` = the recorded eval `score` for commit *i* (`repo.read_eval(oid)["score"]`).
- Trait `zᵢ` = configurable: the score itself (are we selecting on what we measure?),
  or `cost_usd` from the runtime frame, or spec size in "loading units" (see 1.2).
- `Cov(w, z)` over siblings = the **selection differential** (did the higher-fitness
  branch get chosen / advanced?).
- `E[w·Δz]` along each parent→child edge = the **transmission term** (did within-branch
  editing move the trait, weighted by fitness?).

**Deliverable.** `agentvcs price [--since REF] [--trait score|cost|size]` (+ MCP
tool `avcs_price`, + `--json`). Walk the graph via existing `repo.log` / parent
pointers and `merge_base`; emit per-branch-point and aggregate:
```json
{"selection": 0.42, "transmission": -0.08, "delta_zbar": 0.34,
 "reading": "improvement is selection-driven; within-branch editing is slightly degrading"}
```
No new stored objects — pure read over commits + evals. New file
`src/agentvcs/price.py`, wired into `cli.py` and `mcp_server.py` with a test in
`tests/test_price.py`.

### 1.2 Eigen error threshold — is the self-rewrite loop still net-positive?

**Idea (#5), computed via its Price identity.** The error catastrophe (`μL > ln σ`)
is exactly the balance point where the transmission term goes negative and exceeds
selection: `E[w·Δz] < 0` (mutational degradation from self-editing) overtakes
`Cov(w, z)` (selection). **We do not need to estimate μ, L, or σ separately** — the
crossing is observable directly from the two Price terms agentvcs already computes in
1.1. That's the instrument.

**Deliverable.** Fold into `agentvcs price` as a verdict, or expose
`agentvcs threshold`:
- Track the time series of `E[w·Δz]` (magnitude) vs `Cov(w, z)` across recent commits.
- When `|E[w·Δz]| > Cov(w, z)` for a sustained window, emit:
  `{"code": "ERROR_CATASTROPHE", "message": "self-improvement loop is degrading: within-lineage editing is losing information faster than selection recovers it — freeze the editable surface or raise eval coverage"}`.
- This is a **new stable warning code**, not an error that blocks anything — advisory,
  ties naturally into `freeze` (the honest response is to crystallize and stop
  mutating) and into eval coverage (the honest response is sharper fitness signal).

**Engineering payoff worth stating in the docs.** `L_max = ln σ / μ` scales *linearly*
in `1/μ` and only *logarithmically* in `σ`. Halving the per-edit break probability
(better per-edit verification) roughly doubles the complexity you can safely
self-modify; doubling eval sharpness buys ~40%. **Verification-per-edit beats
eval-quality by an order of magnitude** — a concrete guidance line agentvcs can put in
front of users at the moment the threshold is crossed.

**Caveat to ship honestly (Wiehe 1997).** The threshold is sharp only on a single-peak
landscape; on rugged landscapes it softens. Report `L_max` / the crossing as an
order-of-magnitude signal, not a cliff. The doc and `--json` output should say so.

### 1.3 Critical slowing down — early warning before the mean moves

**Idea (#J, Scheffer 2009).** Lag-1 autocorrelation and variance of a state variable
rise *before* a bifurcation — a leading indicator of collapse.

**Why it fits agentvcs and not the harness.** agentvcs already stores the per-commit
eval-score series with timestamps (`.agentvcs/evals/<oid>.json` has `score` and `ts`)
and already renders live telemetry in `monitor.py` (`watch` / `statusline` /
`render_panel`). This is a cheap statistic over data already on disk.

**Deliverable.** Add to `monitor.py` a `slowing_signal(repo)` that computes lag-1
autocorrelation + rolling variance of the recent eval-score series and surfaces it in
`render_panel` / `watch` and as an `agentvcs health --json` field:
```json
{"lag1_autocorr": 0.81, "variance_trend": "rising", "warning": "approaching instability"}
```
Pure stdlib arithmetic, no new stored objects. Test in `tests/test_monitor.py`.

---

## Tier 2 — Strong theoretical grounding, modest build.

### 2.1 Muller's ratchet — the formal argument for `merge`

**Idea (#G).** Asexual lineages without recombination irreversibly accumulate
deleterious mutations; the least-loaded class, once lost, cannot be recovered without
recombination. Click rate scales with `N·e^(−U/s)`.

**Why it matters here.** This is a *theoretical proof of agentvcs's core thesis*, not
a new feature. `merge --reconcile` is the recombination operator. A long-lived branch
that never merges is a condemned asexual lineage. That reframes merge from "workflow
convenience" to "the only mechanism that reconstitutes the least-loaded variant class."

**Deliverable (light).** A staleness/ratchet warning on `status` / `log` / `branch`
for branches that have diverged far from their merge-base without merging back, plus a
paragraph in the merge docs stating the argument. Uses `merge_base` + commit distance +
the eval-score trend on the branch (proxy for accumulating load). No new object shapes.

### 2.2 Kinetic proofreading + somatic hypermutation — the eval-gate law and the editable surface

**Idea (#D).** Kinetic proofreading: chained irreversible-discard stages give error
`f = f₀^(n+1)` — error falls *exponentially in the number of stages*, but only if each
intermediate is **hard-rejected**, not merely re-scored. Somatic hypermutation: mutate
only a declared region (CDRs), protect the framework, so the `L` that enters `μL < ln σ`
is only the *editable* region.

**Two concrete consequences for agentvcs:**

1. **The freeze gate is already a proofreading stage — make the architecture explicit.**
   `freeze` hard-rejects an unproven commit (`EVAL_FAILED`), which is exactly the
   irreversible-discard requirement. A *cascade* of independent evals with hard-reject
   gives `ε^n` at `n×` cost. Document that a verifier that only *scores* and lets the
   candidate proceed buys nothing; only a hard-reject-and-restart stage lowers μ. This
   is an architecture insight, and it's already latent in `eval.py` /
   `ensure_passing`.

2. **Declare the editable surface in `agent.json`** so the Eigen bound (1.2) uses
   `L_effective` = editable units only, not the whole spec. Proposal:
   ```json
   "editable": ["skills/", "prompts/planner.md"]   // the CDRs; everything else is framework
   ```
   `price`/`threshold` then computes the error-catastrophe crossing against the editable
   surface, which is the actual competitor to `ln σ / μ`. This is the engineering answer
   to the `L_max ≈ 25` calculation: shrink the mutable surface per cycle and the loop
   stays sub-threshold. Adding a new *optional* manifest key is not a stored-object
   format change (it's read config, like `eval`), so it stays within the invariants.

---

## Tier 3 — Measurement-only diagnostics (shipped, clearly labeled as estimates)

These report numbers *about* the harness/memory layers from the lineage agentvcs
stores; they deliberately trigger **no** behavior (no compression, no auto-verify).
Each is honest about being a proxy.

- **Kelly / Kussell–Leibler + channel capacity (#H, #9) → `agentvcs infobits`.** The
  log-growth value of side information is bounded by `I(context; action)` bits.
  `infobits` measures the decision channel from the recorded traces: `H(action)` over
  tool selections (the bits actually exercised) and `I(prev action; next action)` — a
  *concrete, computable* mutual information whose context variable is the preceding
  action. That MI is an explicit **lower-bound proxy** for `I(full-context; action)`,
  not the whole thing, and the output says so. A low figure bounds what more retrieval
  can buy — the quantitative case for compression — but agentvcs never compresses
  anything itself; that stays in the harness/retrieval layer.
- **Branching process R₀ + dispersion k (#G) → `agentvcs contain`.** For shared-memory
  poisoning, corruption is self-limiting iff `R₀ = n·p < 1`. `contain` measures the
  fan-out `n` from the subagent/swarm topology and the escape probability `p` from the
  empirical failed-eval fraction (both overridable via `--fanout`/`--prob`), then
  reports `R₀`, whether it's contained, and the **required verification rate**
  `1 − 1/R₀`. The output carries the honest caveat that this is a mean-field bound —
  the dispersion (tail) matters more than the mean, so a low average `R₀` with a heavy
  tail still permits rare large cascades.
- **Replicator dynamics / DeSoc correlation discounting (#6).** Already partially
  present: `plural.py` selects maximally-diverse fleets by discounting Soul correlation
  (facility-location over skill profiles). Frequency-dependent replicator dynamics is
  the continuous-time generalization; the connection is noted in `plural.py`'s
  docstring. No new build unless variants start competing for a shared task pool — at
  which point `plural`'s diversity score and `price`'s selection term are the two
  inputs a replicator step needs.

---

## Explicitly out of scope for agentvcs (and where they belong)

These are excellent ideas that target the **controller / scheduler / retrieval / fleet
runtime**, not a version control system. Building them into agentvcs would violate the
repo's stated scope and turn a VCS into a harness. Listed so the boundary is on record:

| Idea | Belongs to |
|---|---|
| Antithetic integral control of throughput/cost (#1) | harness controller |
| Stochastic resonance in sampling temperature (#7) | decoder / sampling loop |
| FBA / dFBA budget allocation (#3) | harness scheduler |
| Marginal value theorem — subtask abandonment (#E) | agent control loop |
| Lévy flights / DDM / chemotaxis search (#E) | agent search policy |
| WBE–Kleiber fleet scaling, cable constant, MCA (#F) | fleet orchestrator |
| Integrate-and-fire alerting (#8) | HEAT / alerting product |
| Turing role differentiation (#J) | fleet scheduler |
| PK compartmental memory dosing (#I) | evolving-memory layer |
| Bode integral / waterbed (#2) | design principle (audit, not code) |

The Bode integral (#2) is worth keeping as an *auditing principle* for the whole
system — "measure where you moved the fragility, don't claim you removed it" — and 1.2
already instantiates it concretely (Olsman 2019 gives the hard trade-off bound for the
antithetic motif; the error-threshold crossing is that trade-off made visible on the
commit graph).

---

## Phased roadmap

1. **`price.py` + `agentvcs price --json` + `avcs_price` MCP tool** (1.1). Selection vs
   transmission over the commit graph. Self-contained; ships value immediately.
2. **Error-threshold verdict** (1.2) folded into `price` as an advisory
   `ERROR_CATASTROPHE` signal; add the `editable` manifest key (2.2) so the bound uses
   `L_effective`.
3. **`slowing_signal` in `monitor.py`** + `agentvcs health` (1.3). Early-warning over
   the eval series; drop into `watch`/`statusline`.
4. **Muller's-ratchet staleness warning** on `branch`/`status` + merge-docs argument
   (2.1). Reinforces the existing merge thesis.
5. **Docs pass**: the proofreading/hard-reject architecture note (2.2.1) in the eval
   docs; the out-of-scope table in the README/SPEC so contributors don't scope-creep.

Order 1→5 is strict-value-first: each step is independently useful, none blocks on the
next, and steps 1–2 deliver the headline capability — *a VCS that can measure whether an
agent's self-modification is net-positive, from data it already stores.*

## Status (shipped)

Steps 1–5 above are implemented in `src/agentvcs/dynamics.py` (pure stdlib, no new
stored-object shapes, `--json` throughout):

- **`agentvcs price [--since REF] [--trait score|size|cost]`** — Price decomposition
  (`selection` = `Cov(w,z)`, `transmission` = `E[w·Δz]`, fitness = offspring count)
  with the `ERROR_CATASTROPHE` verdict folded in, and `l_total`/`l_effective` from the
  optional `agent.json` `"editable"` surface.
- **`agentvcs health`** — rollup of Price + critical-slowing-down (`slowing()`, lag-1
  autocorrelation + variance trend over the eval-score series) + Muller's-ratchet load
  (`ratchet()`), with a flat `warnings[]`.
- **`agentvcs branch`** now carries a per-branch `ratchet` risk and surfaces
  merge-me warnings for long unmerged lineages.
- The slowing signal also rides in `agentvcs watch`'s panel.
- MCP tools **`avcs_price`** / **`avcs_health`**; new stable error code **`BAD_TRAIT`**.
- Architecture notes landed where they belong: the kinetic-proofreading / hard-reject
  argument in `eval.py`, the replicator connection in `plural.py`.

Tier 3 is also shipped, as measurement-only diagnostics that trigger no behavior:

- **`agentvcs infobits`** (MCP `avcs_infobits`) — `H(action)` + `I(prev; next)` bits
  over the recorded tool selections; the Kelly/Kussell–Leibler bound on the value of
  context, labeled as a lower-bound proxy.
- **`agentvcs contain [--fanout N] [--prob P]`** (MCP `avcs_contain`) — the
  branching-process test `R₀ = n·p` for shared-memory poisoning, with `n`/`p` measured
  from the subagent/swarm topology and the failed-eval fraction, returning the required
  verification rate and a mean-field/tail caveat.

The controller/fleet math in the table above stays out of scope — those regulate a
live harness, not a version control system.
