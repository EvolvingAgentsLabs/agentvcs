"""Translate one agentvcs --json result into a plain-language business bottom line.

The diagnostics compute real math (Price equation, branching-process R0, entropy);
this renderer throws all of that away and prints the *decision* a non-technical
stakeholder actually needs — no Cov, no bits, no R0 in the headline.
"""
import json
import sys

d = json.load(sys.stdin)
if d.get("ok") is False:
    print(f"  (error: {d['error']['code']})")
    sys.exit(0)

cmd = d.get("command")
BAR = "  " + "─" * 68


def box(lines):
    print(BAR)
    for ln in lines:
        print("  " + ln)
    print(BAR)


if cmd == "price":
    if d.get("insufficient"):
        box(["ℹ  Not enough history yet to judge the trend."])
    elif d["threshold"]["crossed"]:
        box([
            "🚨 BOTTOM LINE — the self-updates are BACKFIRING.",
            "",
            "Left to keep editing itself, the agent is getting WORSE over time,",
            "not better. Each weekly update passed its own test, so nothing looked",
            "wrong week to week — the decline only shows up across the whole history.",
            "",
            "→ Roll back to the best version and stop the unsupervised self-editing.",
        ])
    elif d["delta_zbar"] > 0:
        box([
            "✅ BOTTOM LINE — the agent is genuinely improving.",
            "",
            "Trying a few versions and keeping the best one is paying off: quality is",
            "trending UP across the history, not just on any single test. Safe to continue.",
        ])
    else:
        box(["➖ BOTTOM LINE — flat. The changes aren't moving quality either way."])

elif cmd == "branch":
    highs = [b["name"] for b in d.get("branches", []) if b.get("ratchet") == "high"]
    if highs:
        who = ", ".join(f"'{h}'" for h in highs)
        box([
            f"⚠️  BOTTOM LINE — the {who} version has drifted on its own too long.",
            "",
            "It has been patched in isolation for several releases and its quality is",
            "sliding. Versions maintained alone tend to rot — small mistakes pile up",
            "with nothing to correct them.",
            "",
            "→ Merge it back into the main product before it drifts further.",
        ])
    else:
        box(["✅ BOTTOM LINE — no version has been left to drift. Nothing urgent to merge."])

elif cmd == "infobits":
    if d.get("insufficient"):
        box(["ℹ  No decisions recorded yet to measure."])
    elif d["action_entropy_bits"] < 1.0:
        box([
            "💸 BOTTOM LINE — you're paying for context the agent barely uses.",
            "",
            "The agent reads a large amount of material on every request but almost",
            "always does the same thing regardless. That context is hardly changing its",
            "decisions — so you can trim it to cut cost and speed things up, with little",
            "to no quality loss.",
        ])
    else:
        box([
            "✅ BOTTOM LINE — the context is genuinely shaping the agent's answers.",
            "",
            "What you feed the agent really is driving its decisions. Don't trim it blindly.",
        ])

elif cmd == "contain":
    if d.get("insufficient"):
        box(["ℹ  Not enough fleet/quality data to judge spread risk."])
    elif not d["contained"]:
        pct = round(d["required_verification_rate"] * 100)
        box([
            "🦠 BOTTOM LINE — one bad memory entry will SPREAD across the fleet.",
            "",
            "At the current fleet size and error rate, a single wrong 'fact' saved to the",
            "shared memory gets read and re-used by other agents faster than it dies out.",
            "",
            f"→ Double-check at least {pct}% of what agents read from memory — or run a",
            "  smaller fleet — to keep a mistake from snowballing.",
        ])
    else:
        box([
            "✅ BOTTOM LINE — a bad memory entry fades out on its own here.",
            "",
            "At this fleet size the shared memory is self-correcting: mistakes don't snowball.",
        ])

else:
    print("  " + json.dumps({k: v for k, v in d.items()
                             if k not in ("ok", "command")}))
