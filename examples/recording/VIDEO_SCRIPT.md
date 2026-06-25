# agentvcs — demo video script

A ~3:00 screencast. The order leads with the **core idea** — versioning the agent's
*run-time* evolution and merging it back into a release **with an agent** — then
shows the multidimensional commit that makes that merge smart, the runtime frame
against the viewer's own session, the **eval → freeze → recall** trust loop, and
cross-runtime capture.

Every command shown exists and was exercised live (see `selftest/AGENT_SELFTEST.md`).
Don't show a feature the harness didn't confirm. The command **outputs** below are
illustrative — re-capture them from a real session before filming (see Production
notes); the *commands* are exact.

- Format: terminal screencast (the repo uses `vhs` `.tape` + asciinema `.cast`; see
  the files alongside this one). One terminal, large font.
- Total: ~3m00s. No slides — the terminal *is* the slide.
- Typing: use `vhs` so commands type at a readable speed; pause on every frame that
  contains a number or a dimensional diff.

---

## Cold open (0:00–0:22) — the problem, and the one command that fixes it

> **VO:** "Your agents don't just *run* your code — they rewrite it. New skills,
> edited tools, dropped prompts, redirected goals, *while they run*. Then you ship a
> release from `main`, and git quietly erases everything they learned in the field.
> Watch."

Two lines have diverged: `main` (your new release) and `runtime` (what the live
system changed about itself). Show it:

```bash
agentvcs log
```

```
* 7c1d… (runtime)  agent: added refund-triage skill, dropped a stale prompt
* 2a90… (main)     release: v1.4 — rewrote the tool API
* 51bb…            common ancestor
```

> **VO:** "Don't pick one and lose the other. Merge them — and let an agent reconcile
> the reasoning, not a blind text heuristic."

```bash
agentvcs checkout runtime
agentvcs merge main --reconcile "claude -p reconcile"
```

**Hold on the result:**

```
Merged main -> 9f3c1a2
  code:       three-way merged (skills/, tools/, prompts/)
  models:     pins unioned
  goal+trace: reconciled by the agent
```

> **VO:** "Code, skills and tools get a real three-way merge. The goal and the
> reasoning traces get handed to an agent. The field-learned behavior *and* the new
> release survive — nothing the system learned is lost."

---

## Act 1 (0:22–1:05) — why the merge can be smart: four dimensions, captured

> **VO:** "It can do that because a commit here isn't a text diff. It's the whole
> iteration."

```bash
agentvcs diff
```

```
2a90…..7c1d…
  code
    + skills/refund-triage.md
    ~ tools/refund.ts
    - prompts/legacy-router.md
  goal
    from: Route support tickets
    to:   Route + auto-triage refunds under $50
  trace  +18 messages
```

> **VO:** "Code, the goal it's pursuing, the models running it, and the trace — the
> actual reasoning — versioned together. So *which dimension moved* is a first-class
> answer, and the merge knows *why* each side changed, not just what."

```bash
agentvcs show --trace
```

Flash the captured `[thinking]` / `[tool_use]` / `[tool_result]` that produced the
new skill.

> **VO (over it):** "That reasoning is captured straight from the live session — and
> secrets in it are `[REDACTED]` before they ever hit disk."

---

## Act 2 (1:05–1:45) — the runtime your agent hides

> **VO:** "Versioning the run-time line means agentvcs also sees what your runtime
> won't show you. Run it against your *own* session."

```bash
agentvcs runtime
```

Let the frame paint and **hold on it for 4 seconds**:

```
runtime frame  (what your runtime hides)
  turns:     11
  budget:    27208 tok  (in 24306 / out 2902)  $0.5822 / ceiling $2.0000
  context:   41293/200000 tok  (20.6%)  compactions=0
  model routing:
    claude-opus-4-8: 11 turns, 24306+2902 tok, $0.5822
  tools:     Read×3, Bash×2
```

> **VO:** "The dollar cost, how full your context is, how many times it got
> compacted, which models ran, every tool you called — reconstructed from the log you
> already have, not estimated."

**On-screen callouts:** `$0.5822`, `20.6%`, `compactions=0`, `Read×3, Bash×2`.

```bash
agentvcs statusline      # ⬡ agent · 27.2k tok $0.5822/$2.0000 · ctx 21%
```

> **VO:** "Drop that into your runtime's status line and the number is always on."

*(Optional 3s B-roll: `agentvcs watch` redrawing like `top`.)*

---

## Act 3 (1:45–2:35) — trust what you freeze: eval → freeze → recall

> **VO:** "When a run-time solution is worth keeping, freeze it into a cheap,
> deterministic recipe — but only if it's *proven*."

Set the stage: a deliberately wrong `add()`.

```bash
cat app.py
#   def add(a, b): return a - b   # wrong
agentvcs freeze
```

**Hold on the refusal:**

```
EVAL_FAILED  —  fix it or freeze --force to override the gate
```

> **VO:** "It refuses. A frozen recipe you can't trust is worse than no recipe."

Fix it, prove it, freeze it:

```bash
# def add(a, b): return a + b   # fixed
agentvcs eval        #  ✓ passed 1/1  score 1.0
agentvcs freeze      #  ok  verified: true
```

> **VO:** "Now it passes — and the recipe is stamped *verified*. The gate is honest
> under pressure: a flaky check has to pass every run, and forcing past a failure
> marks the recipe verified-false. Never a silent lie."

Close the loop — the cache reflex:

```bash
agentvcs recall "implement an add function"
#   45922c00d97d  score 0.33  ✓verified  implement a correct add(a,b)
#   -> replay the top hit:  agentvcs replay 45922c00d97d
agentvcs replay 45922c00d97d        # deterministic, ~$0
```

> **VO:** "Solved this before? `recall` ranks your *verified* recipes, and `replay`
> re-runs the proven one for about zero dollars — instead of paying the model to
> re-derive it."

---

## Act 4 (2:35–2:50) — not tied to one runtime

> **VO:** "None of this is Claude-Code-specific."

```bash
agentvcs init --qwen-code
agentvcs commit -m "from a qwen session"
agentvcs runtime
```

Show the frame rebuilt from a **qwen-code** checkpoint — same shape, real tokens.

> **VO:** "Same trace, same frame, reconstructed from a qwen-code session — and the
> same from Vercel eve or Anthropic Managed Agents. The format is pluggable. It sits
> *beside* your runtime, not inside it."

---

## Close (2:50–3:00)

Back to a clean prompt. Two lines on screen:

> **agentvcs — version control for agents that evolve while they run.**
> Merge run-time evolution back into your releases — *with an agent.*
> Zero dependencies. Apache-2.0. `pip install agentvcs`

> **VO:** "It's the open-source core. Pure Python, zero dependencies. Link below."

---

## Production notes

- **Lead with the merge, always.** The cold open (the two diverged lines + the
  agent-reconciled merge) is the whole pitch now. If you cut for length, cut Act 2's
  `statusline`/`watch` B-roll or Act 4 before you touch the cold open or the eval
  refusal.
- **Set up two real branches** for the cold open: do a few minutes of real work on a
  `runtime` line (let the agent add a skill / edit a tool), make a separate release
  commit on `main`, then film the genuine `merge --reconcile`. Use a real reconcile
  command so the goal/trace reconciliation is authentic.
- **Real numbers only.** Record the runtime frame against a genuine session
  (`agentvcs init --runtime`, then real work) so the budget/context are authentic.
  The numbers above are illustrative — re-capture yours.
- **Set the ceiling and window first** so the dollar math and the bar light up:
  `"budget": { "ceiling_usd": 2.0, "windows": { "opus": 1000000 } }` in `agent.json`.
  Without the window pin, `context` can read >100% on a 1M model — don't film that.
- **Pacing:** hold ~4s on any frame with numbers or a dimensional diff; viewers read
  dollars, percentages and `+/-/~` lines slowly. Type at vhs default speed.
- **Reuse the toolchain:** turn each act into a `.tape` alongside this file so the
  demo is reproducible, like `cc-trace.tape`.
