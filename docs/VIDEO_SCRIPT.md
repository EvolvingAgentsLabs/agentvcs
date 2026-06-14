# agentvcs — demo video script

A ~2:30 screencast. The order is deliberate and matches what the self-test
(`selftest/AGENT_SELFTEST.md`, 13/13 PASS) proved is real, in the order that
lands hardest: **lead with the runtime frame against the viewer's own session**,
then the **eval → freeze → recall** trust loop, then **cross-runtime**.

Every command shown below was exercised live in the self-test. Don't show a
feature the harness didn't confirm.

- Format: terminal screencast (the repo already uses `vhs` `.tape` +
  asciinema `.cast`; see `examples/recording/`). One terminal, large font.
- Total: ~2m30s. Three acts. No slides — the terminal *is* the slide.
- Typing: use `vhs` so commands type at a readable speed; pause on every frame
  that contains a number.

---

## Cold open (0:00–0:12) — the hook

> **VO:** "Your coding agent just spent your money, filled its context window, and
> dropped half its history to compaction. It didn't tell you any of that. Watch."

Show nothing but a prompt. Type one command:

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

> **VO:** "That's *your* session. The dollar cost, how full your context is, how
> many times it got compacted, which models ran, every tool you called.
> Reconstructed from the log you already have — not estimated."

**On-screen callouts** (highlight as VO names them): `$0.5822`, `20.6%`,
`compactions=0`, `Read×3, Bash×2`.

---

## Act 1 (0:12–0:50) — the frame, in pieces

> **VO:** "It's not one number. It's the whole operational picture, broken out."

```bash
agentvcs budget        # token + dollar accounting vs a ceiling you set
agentvcs context       # context pressure + how much history was silently dropped
```

Show the context bar painting:

```
context window
  used:        41293 / 200000 tok  [████················] 20.6%
  compactions: 0  (context the runtime silently dropped)
```

> **VO:** "Set a dollar ceiling, and it tells you what's left. The context bar is
> the one your runtime won't draw — including the history it threw away."

Then the kicker — it lives in your status line:

```bash
agentvcs statusline
```

```
⬡ agentvcs self-test  ·  27.2k tok $0.5822/$2.0000  ·  ctx 21%
```

> **VO:** "Drop that into your runtime's status line and the number is always on."

*(Optional 3s B-roll: `agentvcs watch` redrawing like `top`.)*

---

## Act 2 (0:50–1:50) — trust what you freeze: eval → freeze → recall

> **VO:** "Visibility is half of it. The other half is trust. agentvcs freezes a
> solution into a cheap, deterministic recipe — but only if it's *proven*."

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

*(Optional 4s: `agentvcs show --trace` flashing a `sk-ant-…` secret rendered as
`[REDACTED]`.)*

> **VO (over that):** "And secrets in the captured trace are redacted by default,
> before they ever hit disk."

---

## Act 3 (1:50–2:20) — not tied to one runtime

> **VO:** "None of this is Claude-Code-specific."

```bash
agentvcs init --qwen-code
agentvcs commit -m "from a qwen session"
agentvcs runtime
```

Show the frame rebuilt from a **qwen-code** checkpoint — same shape, real tokens.

> **VO:** "Same trace, same frame, reconstructed from a qwen-code session. The
> format is pluggable. It sits *beside* your runtime, not inside it."

---

## Close (2:20–2:30)

Back to a clean prompt. One line of text on screen:

> **agentvcs — version control + runtime visibility for agents.**
> Zero dependencies. Apache-2.0. `pip install agentvcs`

> **VO:** "It's the open-source core. Pure Python, zero dependencies. Link below."

---

## Production notes

- **Real numbers only.** Record against a genuine session (`agentvcs init
  --runtime` then do a few minutes of real work) so the frame is authentic. The
  numbers above are from an actual self-test run; re-capture yours.
- **Set the ceiling and window first** so the dollar math and the bar light up:
  `"budget": { "ceiling_usd": 2.0, "windows": { "opus": 1000000 } }` in
  `agent.json`. Without the window pin, `context` can read >100% on a 1M model —
  don't film that frame.
- **Pacing:** hold ~4s on any frame with numbers; viewers read dollars and
  percentages slowly. Type commands at vhs default speed, not instant.
- **Reuse the toolchain:** turn each act into a `.tape` under
  `examples/recording/` so the demo is reproducible, like `cc-trace.tape`.
- **Lead with the frame, always.** If you cut for length, cut Act 1's `budget`/
  `context` breakout before you cut the cold-open frame or the eval refusal —
  those two shots are the whole pitch.
