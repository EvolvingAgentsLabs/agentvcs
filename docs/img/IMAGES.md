# `docs/img/IMAGES.md` — images still wanted

Two images that the documents ask for (2026-10-09). Each is written into its document as an `<img>` inside an HTML
comment marked `IMAGE PLACEHOLDER — see docs/img/IMAGES.md`, so nothing renders broken while the file is missing.
**Once the file is committed here, delete the two comment lines (`<!-- IMAGE PLACEHOLDER …` and `-->`) around it.**
That is the only edit.

Neither is drawn. Both come from this repository: a terminal recording of a demo that runs offline, and a chart
rendered from a committed run. Every number on them comes from those files. The two other figures of this pass are
Mermaid diagrams written straight into `README.md` (the run lifecycle under "Rust core", and `merge resolve` under
"Resolve a merge with Claude Code"). They need no file.

Conventions followed. README images live in `docs/img/` and are referenced by their `raw.githubusercontent.com/…/main/`
URL, as the hero `agentvcs.jpg` is, so a README image shows only once its file is on `main`. Terminal recordings use
the VHS settings of `examples/recording/*.tape` (Dracula, 15 pt, 1380 × 940).

| file | size | format | used in | kind |
|---|---|---|---|---|
| `lk0-merge-dry-run.gif` | 1380 × 940 | GIF (VHS) | `README.md`, "Resolve a merge with Claude Code" | terminal recording |
| `f2-blame-recall.png` | 1600 × 720 (the script writes it) | PNG | `examples/toy_pipeline/RUN_REAL.md`, "Rerun result" | chart from a committed run |

---

## `lk0-merge-dry-run.gif`

**Path:** `docs/img/lk0-merge-dry-run.gif` · **size** 1380 × 940 · **format** GIF, about 15 s

**What it shows.** `examples/lora-kernel/demo.sh --dry-run` on its CI fixture, sections 3–5. Two branches diverge
from the fork manifest. `merge prepare` merges `spec.drafter_adapter` mechanically and hands over two `modify/modify`
conflicts (`serve.adapter`, `spec.sampling`). Each comes with the patches behind both sides, their gates and their
blame deltas. `merge resolve --dry-run` then writes the resolver's workspace and prints the `claude` command without
running it. No model, no network, no Claude Code call, and no lora-kernel checkout (the fixture stands in for it).

**Steps** (from the repository root):

1. Build the SDK once: `crates/agentvcs-py/dev.sh` (creates `crates/agentvcs-py/.venv`).
2. `brew install vhs` (it brings `ttyd` and `ffmpeg`).
3. Save this tape as `examples/recording/lk0-merge.tape`, next to the other tapes:

```
# VHS tape — LK0 merge, --dry-run, on the CI fixture (no lora-kernel checkout, no model, no Claude Code call).
# Render from the repository root:  vhs examples/recording/lk0-merge.tape
Output "docs/img/lk0-merge-dry-run.gif"

Set Shell bash
Set FontSize 15
Set Width 1380
Set Height 940
Set Theme "Dracula"
Set TypingSpeed 36ms
Set Padding 26
Set Margin 14
Set MarginFill "#16161e"
Set WindowBar Colorful
Set BorderRadius 10

Hide
Type "export PYTHON=$PWD/crates/agentvcs-py/.venv/bin/python PS1='$ ' && rm -rf /tmp/lk0 && clear"
Enter
Sleep 500ms
Show

Type "examples/lora-kernel/demo.sh --dry-run --lk examples/lora-kernel/tests/fixture/lk --work /tmp/lk0 \"
Enter
Type `  | sed -n '/^== 3/,/^== 6/p' | grep -v '^     cd ' | sed "s#$HOME#~#g"`
Sleep 600ms
Enter
Sleep 9s
```

4. `vhs examples/recording/lk0-merge.tape` writes `docs/img/lk0-merge-dry-run.gif`.
5. Check the GIF. The long "to resolve for real" command (it prints absolute paths) is filtered out by the `grep -v`,
   and `$HOME` is rewritten to `~`. The workspace line shows a system temp path, which is expected.

Checked on 2026-10-09: `vhs validate` passes on the tape, and the typed pipeline prints exactly sections 3–5 (two
conflicts, `auto: spec.drafter_adapter=ours`, `conflicts: 2`). The GIF itself was not rendered here, because `ttyd`
could not start in the sandbox.

**Alt text:** Terminal recording of examples/lora-kernel/demo.sh --dry-run on its CI fixture: two branches diverge
from a fork manifest, merge prepare merges one dimension mechanically and hands over two modify/modify conflicts,
each with the patches, gates and blame deltas behind both sides, and merge resolve writes the resolver's workspace
without invoking Claude Code.

**Where:** `README.md`, section "Resolve a merge with Claude Code", right after the Mermaid diagram of `merge resolve`.

**To place it:** commit the GIF to `docs/img/`. In `README.md`, delete the line
`<!-- IMAGE PLACEHOLDER — see docs/img/IMAGES.md` above `<p align="center">` and the line `-->` after the caption.

---

## `f2-blame-recall.png`

**Path:** `docs/img/f2-blame-recall.png` · **size** 1600 × 720 (`figsize=(10, 4.5)` at 160 dpi) · **format** PNG

**What it shows.** Gate F2's rerun on a real model (Qwen2.5-1.5B-Instruct Q4_K_M, Colab T4, 2026-10-06).
`extract.recall` over the 8100 ledger steps is drawn as a rolling mean of 50 documents. A dashed line marks the step
where the gated patch was applied (2051). Blame's two segment means are drawn as bars: 0.431 (n = 684) and 0.873
(n = 2016). The title carries the single attribution, delta +0.442, and the label carries the paired gate gain,
+0.444 ≥ 0.10. All of it is read from `examples/toy_pipeline/runs/f2-rerun-2026-10-06/` (`export.audit.json.gz` for
the per-step values, `result.json` for the patch step, the gate and blame). Blame's step index is the position among
the ledger's `step` entries; the script uses the same index, and it reproduces both segment means exactly.

**Steps** (from the repository root; matplotlib in a throwaway venv, since it is not a dependency here):

```bash
python3 -m venv /tmp/avcs-img && /tmp/avcs-img/bin/pip install matplotlib
cat > /tmp/avcs-img/f2.py <<'PY'
import gzip, json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

run = sys.argv[1].rstrip("/"); out = sys.argv[2]
ledger = json.load(gzip.open(f"{run}/export.audit.json.gz"))["ledger"]
result = json.load(open(f"{run}/result.json"))
steps = [e for e in ledger if e["kind"] == "step"]          # blame's step index = position among steps
pts = [(i, e["body"]["metrics"]["extract.recall"]) for i, e in enumerate(steps)
       if "extract.recall" in e["body"]["metrics"]]
at = result["harness"]["reloads"][0]["at_step"]
segs = result["blame"]["extract.recall"]["segments"]
delta = result["blame"]["extract.recall"]["attributions"][0]["delta"]
W = 50                                                       # rolling mean over 50 documents
xs = [pts[j][0] for j in range(W - 1, len(pts))]
ys = [sum(v for _, v in pts[j - W + 1:j + 1]) / W for j in range(W - 1, len(pts))]

fig, ax = plt.subplots(figsize=(10, 4.5), dpi=160)
ax.plot(xs, ys, color="#9aa3ad", linewidth=1, label=f"extract.recall, rolling mean of {W} docs")
for s in segs:
    ax.hlines(s["mean"], s["from_step"], s["to_step"], color="#1f2a44", linewidth=2.4)
    ax.text(s["from_step"] + 80, s["mean"] - 0.07,
            f"segment mean {s['mean']:.3f} (n = {s['n']})", ha="left", fontsize=9, color="#1f2a44")
ax.axvline(at, color="#2f3e8f", linestyle="--", linewidth=1.4)
ax.text(at + 60, 0.08, f"patch applied at step {at}\n(gate: paired gain +{result['gate']['extract.recall.gain']:.3f} ≥ 0.10)",
        fontsize=9, color="#2f3e8f")
ax.set_ylim(0, 1.05); ax.set_xlim(0, len(steps))
ax.set_xlabel("ledger step"); ax.set_ylabel("extract.recall")
ax.set_title(f"agentvcs blame — one attribution, the supervisor's patch, delta +{delta:.3f}")
ax.spines[["top", "right"]].set_visible(False)
ax.legend(frameon=False, loc="lower right")
fig.text(0.99, 0.01, "source: examples/toy_pipeline/runs/f2-rerun-2026-10-06/", ha="right", fontsize=8, color="#666")
fig.tight_layout(); fig.savefig(out)
PY
/tmp/avcs-img/bin/python /tmp/avcs-img/f2.py examples/toy_pipeline/runs/f2-rerun-2026-10-06 docs/img/f2-blame-recall.png
```

The recipe was rendered once on 2026-10-09 to check it. The PNG is not committed.

**Alt text:** Line chart of extract.recall over 8100 ledger steps as a rolling mean of 50 documents: flat near 0.43
until a dashed line at step 2051 where the gated patch is applied, then near 0.87 to the end. Two horizontal bars mark
blame's segment means, 0.431 (n = 684) and 0.873 (n = 2016); the title reads one attribution, delta +0.442.

**Where:** `examples/toy_pipeline/RUN_REAL.md`, section "Rerun result", after the bullet "Falsifiers: none met.". It
is referenced relatively (`../../docs/img/f2-blame-recall.png`), so it shows on any branch that has the file.

**To place it:** commit the PNG to `docs/img/`. In `RUN_REAL.md`, delete the line
`<!-- IMAGE PLACEHOLDER — see docs/img/IMAGES.md` above the `<img …>` and the line `-->` after the caption.
