# Recording assets for the landing page

Three screencasts live here:

- **`runtime-trust.gif`** — the README hero: the **runtime frame** (`agentvcs
  runtime` → dollar cost, context %, routing, real tool usage) followed by the
  **eval → freeze → recall** trust loop (`freeze` refuses a buggy `add()` with
  `EVAL_FAILED`, then crystallizes a `verified` recipe once the eval passes).
  Regenerate with VHS:
  ```bash
  vhs examples/recording/runtime-trust.tape    # writes runtime-trust.gif
  ```
  Its setup ([`runtime_setup.sh`](runtime_setup.sh)) installs a **real** captured
  session as the frame source: [`fixtures/runtime-session.jsonl`](fixtures/) is an
  actual Claude Code transcript reduced to frame-only fields — genuine model/usage/
  tool names, every byte of conversation content stripped — by
  [`make_runtime_fixture.py`](make_runtime_fixture.py). So the frame's numbers
  ($17.13, 17.6% context, real tool counts) are *reconstructed from a real session*,
  not typed. The `add()` trust-loop half is a constructed worked example (the eval/
  freeze/recall calls genuinely execute). Self-cleaning at the end.

  Regenerate the fixture from your own session:
  ```bash
  python3 examples/recording/make_runtime_fixture.py \
      ~/.claude/projects/<encoded-cwd>/<session>.jsonl \
      examples/recording/fixtures/runtime-session.jsonl
  ```

- **`cc-trace.gif`** — the **Claude Code trace provider** flow (`cat agent.json` →
  `trace` → `commit` → `show --trace`). Regenerate it (zero deps, then `agg`):
  ```bash
  python3 examples/recording/make_cc_cast.py
  agg --theme dracula --font-size 16 examples/recording/cc-trace.cast examples/recording/cc-trace.gif
  ```
  It seeds a throwaway toy project + a sample session transcript where the provider
  looks for it, records the real (colored) CLI output through a pty, and cleans up
  after itself. A VHS variant is in [`cc-trace.tape`](cc-trace.tape).

- **`demo.gif`** — an agent driving the full loop (iterate → diff → rollback →
  freeze). Two ways to produce it; pick one.

## Option A — asciinema cast (already generated, zero deps)

[`demo.cast`](demo.cast) is committed and ready to use. Regenerate it any time:

```bash
python3 examples/recording/make_cast.py
```

Then either:

```bash
asciinema upload demo.cast          # hosted player — embed the <script> on the landing
asciinema play  demo.cast           # local preview
agg demo.cast demo.gif              # convert to GIF (brew install agg)
```

`asciinema` casts are tiny, text, and copy-pasteable — great for a docs/landing
embed and they keep the terminal colors crisp.

## Option B — VHS (one command → polished GIF)

[`demo.tape`](demo.tape) renders an authentic GIF directly from `run.sh`:

```bash
brew install vhs
vhs examples/recording/demo.tape    # writes demo.gif
```

Tweak font, theme, and size at the top of `demo.tape`.

## Embedding on the landing

- **GIF**: `![agentvcs](examples/recording/demo.gif)` — simplest, autoplay, works
  everywhere (including the GitHub README).
- **asciinema**: upload, then paste the provided `<script src="https://asciinema.org/a/….js">`
  embed for a seekable, copy-pasteable player.

Keep the asset short. The story it must tell in one glance: *an agent versions its
own goal+code, undoes a mistake in one step, and freezes the result.*
