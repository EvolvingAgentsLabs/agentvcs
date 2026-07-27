#!/usr/bin/env bash
#
# Evolution diagnostics — five acts that prove agentvcs can measure whether an
# agent's self-modification is actually working, from data it already stores.
#
# Everything here is REAL: a deterministic benchmark (bench.py) scores the router
# the "agent" edits, and `agentvcs eval` records those scores. The diagnostics then
# read the commit graph + the eval side-table. Every claim the narration makes is
# asserted against `--json` output, so this script fails loudly if the tools ever
# stop earning it.
#
#   bash examples/evolution-diagnostics/run.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

if command -v avcs >/dev/null 2>&1; then
  AVCS() { avcs "$@"; }
else
  AVCS() { PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli "$@"; }
fi

act()  { printf '\n\033[1m\033[36m════ %s\033[0m\n' "$*"; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
note() { printf '\033[2m   %s\033[0m\n' "$*"; }

# check "<python bool over d>" <agentvcs args...> — run in --json, assert, tick.
# The expression is passed via the environment so its quotes never clash with the shell.
check() {
  local expr="$1"; shift
  export CHECK_EXPR="$expr"
  AVCS "$@" --json | python3 -c '
import sys, json, os
d = json.load(sys.stdin)
expr = os.environ["CHECK_EXPR"]
assert d.get("ok") is not False, d
assert eval(expr), "ASSERT FAILED: " + expr + "\n" + json.dumps(d, indent=2)
print("   \033[32m✓\033[0m " + expr)'
}

# --- the agent's edits: five router bodies with KNOWN benchmark accuracy -------
setbot() {
  case "$1" in
    r10) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t or "money back" in t: return "refunds"
    if "invoice" in t or "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
    ;;
    r09) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t or "money back" in t: return "refunds"
    if "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
    ;;
    r08) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t: return "refunds"
    if "charge" in t: return "billing"
    if "crash" in t or "error" in t or "page" in t: return "tech"
    return "general"
EOF
    ;;
    r07) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "invoice" in t or "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
    ;;
    r06) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t: return "refunds"
    if "charge" in t: return "billing"
    return "general"
EOF
    ;;
    broken) cat > bot.py <<'EOF'
def route(t):
    return "general"          # corrupted: everything to general (bench < 0.5, eval FAILS)
EOF
    ;;
  esac
}

write_bench() {
  cat > bench.py <<'EOF'
import sys
from bot import route
CASES = [("refund my order", "refunds"), ("money back please", "refunds"),
         ("urgent refund now", "refunds"), ("invoice is wrong", "billing"),
         ("charge on my card", "billing"), ("billing charge dispute", "billing"),
         ("app crash on login", "tech"), ("error 500 page", "tech"),
         ("how do i sign up", "general"), ("change my email", "general")]
acc = sum(1 for t, y in CASES if route(t) == y) / len(CASES)
if "--check" in sys.argv:      # the pass/fail gate: 0.5 is "still shippable"
    sys.exit(0 if acc >= 0.5 else 1)
print(f"{acc:.4f}")
EOF
}

manifest() { # manifest "<extra json>"
  cat > agent.json <<EOF
{
  "goal": "Route support tickets to billing / tech / refunds / general.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": null,
  "state": "fluid",
  "eval": { "command": "python3 bench.py --check", "score_command": "python3 bench.py" }$1
}
EOF
}

iterate() { # iterate <bodyid> "<message>"
  setbot "$1"
  AVCS commit -m "$2" --json >/dev/null
  local s; s=$(AVCS eval --json | python3 -c "import sys,json;print(json.load(sys.stdin)['score'])")
  note "commit: $2  →  eval bench=$s (passes ≥0.5, so nothing alarms you here)"
}

WORK="$HERE/workdir"; rm -rf "$WORK"; mkdir -p "$WORK"

###############################################################################
act "ACT 1 — the self-improvement loop that was quietly rotting"
note "An agent tunes a ticket router. It NEVER branches — it just keeps editing"
note "the one file, chasing edge cases. Every commit still passes its eval."
mkdir -p "$WORK/act1"; cd "$WORK/act1"
AVCS init --json >/dev/null; write_bench; manifest ""
iterate r10 "v1: keyword router with a refunds rule"
iterate r09 "opt: fold billing into charge-only"
iterate r08 "opt: broaden tech to catch 'page'"
iterate r07 "simplify: drop the refunds special-case"
iterate r06 "collapse rules to the essentials"
step "git would show five green commits. agentvcs asks: is the LINEAGE improving?"
AVCS price
note "Because there are no branches, selection is 0 BY CONSTRUCTION — this is an"
note "asexual lineage, and its within-line editing is net-negative. That is the"
note "Eigen error catastrophe: no commit-to-commit signal shows it, only the lineage."
check "d['threshold']['crossed'] is True" price
check "d['selection'] == 0.0" price
check "d['transmission'] < 0" price
AVCS health
check "d['healthy'] is False and any('CATASTROPHE' in w for w in d['warnings'])" health

###############################################################################
act "ACT 2 — the cure is recombination, not more editing"
note "Same agent, same benchmark. Now it FORKS two variants each round, keeps the"
note "better one, and invests more exploration in the winning line."
mkdir -p "$WORK/act2"; cd "$WORK/act2"
AVCS init --json >/dev/null; write_bench; manifest ""
iterate r06 "root: weak baseline"
AVCS branch keep --json >/dev/null
iterate r08 "explore A (main line)"
AVCS checkout keep --json >/dev/null
iterate r07 "explore B (alt line)"
note "A (0.8) beat B (0.7) — invest three refinements in A:"
AVCS checkout main --json >/dev/null
AVCS branch k1 --json >/dev/null; AVCS branch k2 --json >/dev/null
iterate r09 "A: refine 1"
AVCS checkout k1 --json >/dev/null; iterate r10 "A: refine 2"
AVCS checkout k2 --json >/dev/null; iterate r09 "A: refine 3"
AVCS checkout keep --json >/dev/null; iterate r07 "B: dead-end tweak"
step "Same edits, but now selection between branches is doing real work:"
AVCS price
AVCS health
check "d['threshold']['crossed'] is False" price
check "d['selection'] > 0" price
check "d['transmission'] > 0" price
check "d['healthy'] is True" health

###############################################################################
act "ACT 3 — Muller's ratchet: a lineage editing alone is doomed"
note "A feature branch evolves in isolation and slowly rots. agentvcs flags it as a"
note "ratchet risk on plain 'branch' — and merging it back ends the isolation."
mkdir -p "$WORK/act3"; cd "$WORK/act3"
AVCS init --json >/dev/null; write_bench; manifest ""
iterate r10 "baseline on main"
AVCS branch feature --json >/dev/null; AVCS checkout feature --json >/dev/null
iterate r09 "feature: tweak 1"
iterate r08 "feature: tweak 2"
iterate r07 "feature: tweak 3"
iterate r06 "feature: tweak 4"
iterate r06 "feature: tweak 5"
AVCS checkout main --json >/dev/null
step "Plain 'agentvcs branch' now carries a ratchet warning:"
AVCS branch
check "any(b['name']=='feature' and b['ratchet']=='high' for b in d['branches'])" branch
check "len(d['warnings']) >= 1" branch
step "Recombine — merge the isolated lineage back. The ratchet clears:"
AVCS merge feature --json | python3 -c "import sys,json;d=json.load(sys.stdin);print('   merge status:',d.get('status'))"
check "all(b.get('ratchet')=='none' for b in d['branches'])" branch

###############################################################################
act "ACT 4 — infobits: how many bits does your context actually buy?"
note "Two agents, 30 tool calls each. One is nearly deterministic (calls 'read'"
note "over and over); the other genuinely varies. Kelly/Kussell-Leibler: the value"
note "of context is bounded by the bits it adds to the decision."
mk_trace() { # mk_trace <dir> <python-list-of-tools>
  mkdir -p "$1"; cd "$1"; AVCS init --json >/dev/null
  python3 - "$2" <<'EOF'
import json, sys
tools = eval(sys.argv[1])
open("run.jsonl","w").write("\n".join(
    json.dumps({"role":"assistant","content":[{"type":"tool_use","name":t}]}) for t in tools))
open("agent.json","w").write(json.dumps(
    {"goal":"do work","models":[],"trace":"run.jsonl","state":"fluid"}))
EOF
  AVCS commit -m "session" --json >/dev/null
}
mk_trace "$WORK/act4-low"  "['read']*26 + ['grep','edit','read','read']"
step "Low-entropy agent (a 40k-token context feeding a near-fixed decision):"
AVCS infobits
check "d['action_entropy_bits'] < 1.0" infobits
mk_trace "$WORK/act4-high" "['read','edit','bash','grep','write','test']*5"
step "High-entropy agent (context genuinely drives the choice):"
AVCS infobits
check "d['action_entropy_bits'] > 2.0" infobits
note "The low-entropy pipeline carries < 1 bit — a quantified license to compress"
note "its context hard. (The MI here uses the previous action as the context proxy,"
note "a labeled lower bound — the tool never overclaims what it measured.)"

###############################################################################
act "ACT 5 — contain: is shared-memory poisoning self-limiting?"
note "A fleet reads a shared memory. If a corrupt entry fans out to n readers and"
note "each re-propagates with probability p, it dies out iff R0 = n·p < 1."
mkdir -p "$WORK/act5"; cd "$WORK/act5"
AVCS init --json >/dev/null; write_bench
# a swarm of 6 readers (fan-out n) declared in agent.json
manifest ",
  \"swarm\": {
    \"reader0\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"reader1\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"reader2\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"reader3\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"reader4\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"reader5\": {\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"}
  }"
for i in 1 2 3 4 5; do
  case $i in 3|5) setbot broken;; *) setbot r10;; esac   # 2 of 5 states are corrupt (eval FAILS)
  AVCS commit -m "round $i" --json >/dev/null
  AVCS eval --json >/dev/null || true
done
step "Fan-out n measured from the swarm, escape rate p from the failed-eval fraction:"
AVCS contain
check "d['contained'] is False and d['r0'] > 1" contain
note "Not self-limiting. The tool gives the fix as a number — the verification rate"
note "that pulls R0 back under 1:"
check "d['required_verification_rate'] > 0" contain
step "Shrink the fan-out (a smaller fleet) and it becomes self-limiting:"
AVCS contain --fanout 2
check "d['contained'] is True" contain --fanout 2

printf '\n\033[1m\033[32m════ All five acts asserted green.\033[0m\n'
note "agentvcs measured — from data it already stores — whether self-modification"
note "was net-positive (price), caught the collapse early (health), flagged a doomed"
note "lineage (ratchet), bounded the value of context (infobits), and sized the"
note "verification a shared memory needs (contain). No harness required."
