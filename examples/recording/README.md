# Recording assets for the landing page

A ~20s screencast of an agent driving the full agentvcs loop (iterate → diff →
rollback → freeze). Two ways to produce a shareable asset; pick one.

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
