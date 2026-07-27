# business-cases — the same power, in plain English

```bash
bash examples/business-cases/run.sh
```

Five everyday situations anyone running an AI product will recognize. Each ends in a
**one-line recommendation** — and there is **no math on screen**. Under the hood it runs
the exact same agentvcs diagnostics as [`../evolution-diagnostics/`](../evolution-diagnostics/);
here a small translator (`_plain.py`) turns each result into the decision a manager,
founder, or ops lead actually needs.

Everything is real: a deterministic test scores the agent each step, `agentvcs eval`
records it, and the verdicts are read back from the saved history.

## The five stories

**1. The support bot that got a little worse every week.**
A team lets its AI ticket-router "self-improve" weekly. Every week's tweak passes that
week's test, so everyone's happy — while quality quietly slides from 100% to 60%. The
per-week green checks hide it; only the whole-history view catches it.
> 🚨 *The self-updates are backfiring. Roll back to the best version and stop the
> unsupervised self-editing.*

**2. The same bot, run the smart way.**
Instead of letting it rewrite itself, the team tries a couple of options each week and
keeps the one that actually tests best. Same effort — quality now climbs to 100%.
> ✅ *The agent is genuinely improving. Safe to continue.*

**3. The custom version for a big client that nobody merged back.**
A special fork is patched in isolation for months and slowly rots.
> ⚠️ *The 'BigClient' version has drifted on its own too long and its quality is
> sliding. Merge it back into the main product before it drifts further.*

**4. Paying to stuff the prompt with context that changes nothing.**
An assistant reads a huge pile of documents on every question but almost always does the
same thing regardless.
> 💸 *You're paying for context the agent barely uses. Trim it to cut cost and latency
> with little to no quality loss.*

**5. One wrong "fact" poisoned the whole fleet.**
A fleet of agents shares a memory. One saves a wrong fact — does it fade, or spread?
> 🦠 *At this fleet size a bad entry spreads instead of dying out. Double-check at least
> 58% of memory reads — or run a smaller fleet.* (Shrink the fleet and it becomes
> self-correcting.)

## Why it matters

The value of agentvcs isn't the equations — it's the calls above. It watches your
agents' whole history and tells you, in plain terms: *stop, this is getting worse* ·
*keep going, this is working* · *merge that fork back* · *cut this context, it's wasted*
· *your shared memory can spread a mistake*. The math is real and lives in
[`docs/EVOLUTIONARY_DYNAMICS.md`](../../docs/EVOLUTIONARY_DYNAMICS.md) — the decision-maker
never has to see it.
