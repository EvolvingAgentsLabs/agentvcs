"""Live session feedback — the agentvcs runtime, in your terminal.

Your agent runtime gives you a nice live readout while it works, but it stops at
what *it* knows. agentvcs adds the part the runtime can't: the dollar cost against
a ceiling, how close context is to a forced compaction, and — uniquely — whether
the goal you're about to grind on is **already solved and frozen** (recall), so you
can replay it instead of paying to redo it.

Two surfaces, both stdlib-only:

  * ``agentvcs watch`` — a full panel that redraws in place (like ``top``),
    rebuilding the frame from the live session log every couple of seconds.
  * ``agentvcs statusline`` — one compact line, designed to be dropped straight
    into your runtime's own status line (e.g. Claude Code's ``statusLine`` setting
    runs a command and shows its stdout), so agentvcs's feedback rides along inside
    the session you're already watching.
"""
from __future__ import annotations

import sys
import time

from .recall import recall
from .repository import Repository

# minimal ANSI; only emitted when color is on (a tty)
_R = "\033[0m"
_TONE = {"ok": "\033[32m", "warn": "\033[33m", "bad": "\033[31m",
         "dim": "\033[2m", "b": "\033[1m", "cyan": "\033[36m", "yellow": "\033[33m"}


def _c(s: str, tone: str, color: bool) -> str:
    return f"{_TONE[tone]}{s}{_R}" if (color and tone in _TONE) else s


def _human(n) -> str:
    if not isinstance(n, (int, float)):
        return "?"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.1f}k"
    return str(int(n))


def _usd(v) -> str:
    return f"${v:.4f}" if isinstance(v, (int, float)) else "—"


def _tone_for(frac, warn=0.7, bad=0.9) -> str:
    if frac is None:
        return "dim"
    if frac >= bad:
        return "bad"
    if frac >= warn:
        return "warn"
    return "ok"


def _bar(frac, width: int, color: bool, tone: str | None = None) -> str:
    if frac is None:
        return _c("[" + "·" * width + "]", "dim", color)
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    body = "█" * filled + "·" * (width - filled)
    return "[" + _c(body, tone or _tone_for(frac), color) + "]"


# ----------------------------------------------------------------- the panel
def render_panel(repo: Repository, color: bool = False, width: int = 72) -> str:
    """A full multi-line snapshot of the runtime frame + agentvcs's value-add."""
    frame = repo.runtime_frame()
    manifest = repo.read_manifest()
    goal = manifest.get("goal", "")
    mode = repo.mode()
    branch = repo.current_branch() or "detached"
    b, ctx = frame["budget"], frame["context"]

    lines = []
    head = _c("agent", "b", color) + _c("vcs", "cyan", color)
    lines.append(f"{head}  {_c(branch, 'b', color)}  {_c(mode + ' mode', 'dim', color)}")
    if goal:
        lines.append(_c("  " + goal[:width - 2], "dim", color))
    lines.append("")

    # budget — tokens always, dollars + bar when a ceiling is set
    ceil = b["ceiling_usd"]
    frac = (b["cost_usd"] / ceil) if (ceil and b["cost_usd"] is not None) else None
    tone = "bad" if b["over_budget"] else _tone_for(frac)
    spend = f"{_usd(b['cost_usd'])}" + (f" / {_usd(ceil)}" if ceil is not None else "")
    bar = "  " + _bar(frac, 18, color, tone) if frac is not None else ""
    lines.append(f" {_c('budget ', 'b', color)} {_human(b['tokens_total'])} tok"
                 f"  {_c(spend, tone, color)}{bar}")

    # context — used/window + bar + compaction count
    cfrac = (ctx["used"] / ctx["window"]) if (ctx["window"] and ctx["used"]) else None
    ctone = _tone_for(cfrac, warn=0.7, bad=0.85)
    pct = f"{ctx['pct']}%" if ctx["pct"] is not None else "?"
    lines.append(f" {_c('context', 'b', color)} {_human(ctx['used'])}/{_human(ctx['window'])}"
                 f"  {_bar(cfrac, 18, color, ctone)} {_c(pct, ctone, color)}"
                 f"  {_c('compactions ' + str(ctx['compactions']), 'dim', color)}")

    # routing / tools / subagents
    if frame["models"]:
        routing = "  ".join(f"{m['model']}×{m['turns']}" for m in frame["models"])
        lines.append(f" {_c('routing', 'b', color)} {routing}")
    if frame["tools"]:
        lines.append(f" {_c('tools  ', 'b', color)} "
                     + " ".join(f"{t['name']}×{t['count']}" for t in frame["tools"]))
    if frame["subagents"]:
        lines.append(f" {_c('agents ', 'b', color)} "
                     + " ".join(f"{s['type']}×{s['count']}" for s in frame["subagents"]))

    # eval — is the current state actually proven, or just claimed done?
    head = repo.head_commit()
    ev = repo.read_eval(head)
    if ev:
        tone = "ok" if ev["ok"] else "bad"
        mark = "✓ passed" if ev["ok"] else "✗ FAILED"
        lines.append(f" {_c('eval   ', 'b', color)} "
                     + _c(f"{mark}  {ev['passed']}/{ev['total']} runs  score {ev['score']}", tone, color))
    elif manifest.get("eval"):
        lines.append(f" {_c('eval   ', 'b', color)} "
                     + _c("· not run yet — `agentvcs eval` before you freeze", "warn", color))

    # recall — the reflex the runtime doesn't have (verified recipes first)
    hits = recall(repo, goal, limit=3, min_score=0.1) if goal else []
    if hits:
        top = hits[0]
        trust = "✓verified" if top.get("verified") else "unverified"
        lines.append(f" {_c('recall ', 'b', color)} "
                     + _c(f"✓ {len(hits)} match → replay {top['commit'][:9]}"
                          f" ({trust}, score {top['score']:.2f})",
                          "ok" if top.get("verified") else "cyan", color))
    else:
        lines.append(f" {_c('recall ', 'b', color)} "
                     + _c("· no cache hit — this is new work", "dim", color))

    # warnings — the actionable part
    warns = []
    if b["over_budget"]:
        over = abs(b["remaining_usd"]) if b["remaining_usd"] is not None else 0
        warns.append(_c(f" ⚠ OVER BUDGET by {_usd(over)} — pause and ask a human", "bad", color))
    elif frac is not None and frac >= 0.9:
        warns.append(_c(f" ⚠ {int(frac * 100)}% of budget spent", "warn", color))
    if cfrac is not None and cfrac >= 0.85:
        warns.append(_c(" ⚠ context nearly full — a compaction will drop history soon", "warn", color))
    if warns:
        lines.append("")
        lines += warns
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- status line
def statusline(repo: Repository, color: bool = False) -> str:
    """One compact line for embedding in your runtime's own status line."""
    frame = repo.runtime_frame()
    b, ctx = frame["budget"], frame["context"]
    goal = repo.read_manifest().get("goal", "")
    parts = [_c("⬡ " + (goal[:24] or repo.current_branch() or "agentvcs"), "cyan", color)]

    spend = _usd(b["cost_usd"])
    if b["ceiling_usd"] is not None:
        spend += "/" + _usd(b["ceiling_usd"])
    tok = f"{_human(b['tokens_total'])} tok {spend}"
    parts.append(_c(tok, "bad", color) if b["over_budget"] else tok)

    if ctx["pct"] is not None:
        ct = f"ctx {ctx['pct']:.0f}%"
        parts.append(_c(ct, "warn", color) if ctx["pct"] >= 85 else ct)

    ev = repo.read_eval(repo.head_commit())
    if ev:
        parts.append(_c("✓eval" if ev["ok"] else "✗eval", "ok" if ev["ok"] else "bad", color))

    hits = recall(repo, goal, limit=1, min_score=0.1) if goal else []
    if hits:
        parts.append(_c(f"✓recall→{hits[0]['commit'][:7]}", "ok", color))
    return "  ·  ".join(parts)


# --------------------------------------------------------------------- watch
def watch(repo: Repository, interval: float = 2.0, color: bool = True,
          width: int = 72, out=None) -> None:
    """Redraw the panel in place until interrupted (Ctrl-C). Rebuilds from the
    live session log each tick, so it tracks the agent as it works."""
    out = out or sys.stdout
    interval = max(0.5, interval)
    try:
        while True:
            try:
                panel = render_panel(repo, color=color, width=width)
            except Exception as e:  # a half-written log shouldn't kill the watch
                panel = f"(waiting for session… {e})\n"
            out.write("\033[2J\033[3J\033[H")        # clear + home
            out.write(panel)
            out.write(_c(f"\n  refreshing every {interval:g}s · Ctrl-C to stop\n", "dim", color))
            out.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        out.write("\n")
