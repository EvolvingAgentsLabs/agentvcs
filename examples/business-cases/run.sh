#!/usr/bin/env bash
#
# Five plain-language business stories. Each is a situation a manager, founder, or
# ops lead recognizes — and each ends in a one-line recommendation, with NO math on
# screen. Under the hood it is the exact same agentvcs diagnostics as the
# evolution-diagnostics example; here _plain.py translates their output into the
# decision a non-technical stakeholder actually needs.
#
# Everything is real: a deterministic benchmark scores the agent, `agentvcs eval`
# records it, and the verdicts are read back from the commit history.
#
#   bash examples/business-cases/run.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PLAIN="$HERE/_plain.py"

if command -v avcs >/dev/null 2>&1; then AVCS() { avcs "$@"; }
else AVCS() { PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli "$@"; } ; fi

story() { printf '\n\033[1m\033[36m▐ %s\033[0m\n' "$*"; }
say()   { printf '   %s\n' "$*"; }
plain() { AVCS "$@" --json | python3 "$PLAIN"; }

setbot() { # writes a ticket-router whose benchmark accuracy is known
  case "$1" in
    q100) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t or "money back" in t: return "refunds"
    if "invoice" in t or "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
;;  q90) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t or "money back" in t: return "refunds"
    if "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
;;  q80) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t: return "refunds"
    if "charge" in t: return "billing"
    if "crash" in t or "error" in t or "page" in t: return "tech"
    return "general"
EOF
;;  q70) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "invoice" in t or "charge" in t: return "billing"
    if "crash" in t or "error" in t: return "tech"
    return "general"
EOF
;;  q60) cat > bot.py <<'EOF'
def route(t):
    t = t.lower()
    if "refund" in t: return "refunds"
    if "charge" in t: return "billing"
    return "general"
EOF
;;  broken) cat > bot.py <<'EOF'
def route(t):
    return "general"
EOF
;;  esac
}

write_bench() { cat > bench.py <<'EOF'
import sys
from bot import route
CASES = [("refund my order","refunds"),("money back please","refunds"),
         ("urgent refund now","refunds"),("invoice is wrong","billing"),
         ("charge on my card","billing"),("billing charge dispute","billing"),
         ("app crash on login","tech"),("error 500 page","tech"),
         ("how do i sign up","general"),("change my email","general")]
acc = sum(1 for t, y in CASES if route(t) == y) / len(CASES)
if "--check" in sys.argv:
    sys.exit(0 if acc >= 0.5 else 1)
print(f"{acc:.4f}")
EOF
}

manifest() { cat > agent.json <<EOF
{ "goal": "Send each customer ticket to the right team.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": null, "state": "fluid",
  "eval": { "command": "python3 bench.py --check", "score_command": "python3 bench.py" }$1 }
EOF
}

ship() { # ship <quality-id> "<what shipped>"  -> commits + evals, prints a plain line
  setbot "$1"; AVCS commit -m "$2" --json >/dev/null
  local s; s=$(AVCS eval --json | python3 -c "import sys,json;print(int(round(json.load(sys.stdin)['score']*100)))")
  say "$2  →  passed its test at ${s}% quality ✓"
}

WORK="$HERE/workdir"; rm -rf "$WORK"; mkdir -p "$WORK"

###############################################################################
story "STORY 1 — The support bot that got a little worse every week"
say "A support team lets its AI ticket-router 'self-improve' each week. Every"
say "Monday it ships a tweak, and every Monday the tweak passes the weekly test."
say "So everyone is happy. Are they right to be?"
echo
mkdir -p "$WORK/s1"; cd "$WORK/s1"; AVCS init --json >/dev/null; write_bench; manifest ""
ship q100 "Week 1 — first version"
ship q90  "Week 2 — 'streamline billing'"
ship q80  "Week 3 — 'catch more tech tickets'"
ship q70  "Week 4 — 'simplify the rules'"
ship q60  "Week 5 — 'clean up'"
say "Every single week was green. Now ask agentvcs about the WHOLE story:"
plain price

###############################################################################
story "STORY 2 — The same bot, run the smart way"
say "Rewind. This time the team doesn't let the bot rewrite itself in place. Each"
say "week it tries a couple of options and KEEPS THE ONE THAT ACTUALLY TESTS BEST."
echo
mkdir -p "$WORK/s2"; cd "$WORK/s2"; AVCS init --json >/dev/null; write_bench; manifest ""
ship q60 "Start — modest baseline"
AVCS branch keep --json >/dev/null
ship q80 "Option A"
AVCS checkout keep --json >/dev/null; ship q70 "Option B"
say "Option A won. Put the next round of effort into A:"
AVCS checkout main --json >/dev/null
AVCS branch k1 --json >/dev/null; AVCS branch k2 --json >/dev/null
ship q90 "A, improved"
AVCS checkout k1 --json >/dev/null; ship q100 "A, improved further"
AVCS checkout k2 --json >/dev/null; ship q90 "A, another try"
AVCS checkout keep --json >/dev/null; ship q70 "B, abandoned"
say "Same effort, opposite outcome:"
plain price

###############################################################################
story "STORY 3 — The custom version for a big client that nobody merged back"
say "For one important customer, the team forked a special version of the agent and"
say "kept patching it on the side for months, separate from the main product."
echo
mkdir -p "$WORK/s3"; cd "$WORK/s3"; AVCS init --json >/dev/null; write_bench; manifest ""
ship q100 "Main product — solid"
AVCS branch BigClient --json >/dev/null; AVCS checkout BigClient --json >/dev/null
ship q90 "BigClient patch 1"; ship q80 "BigClient patch 2"; ship q70 "BigClient patch 3"
ship q60 "BigClient patch 4"; ship q60 "BigClient patch 5"
AVCS checkout main --json >/dev/null
say "agentvcs watches how far that side-version has drifted:"
plain branch

###############################################################################
story "STORY 4 — Paying to stuff the prompt with context that changes nothing"
say "An assistant reads a huge pile of company documents on every single question."
say "It is slow and expensive. Is all that reading actually helping it answer?"
echo
mk_agent() { mkdir -p "$1"; cd "$1"; AVCS init --json >/dev/null
  python3 - "$2" <<'EOF'
import json, sys
tools = eval(sys.argv[1])
open("run.jsonl","w").write("\n".join(json.dumps(
  {"role":"assistant","content":[{"type":"tool_use","name":t}]}) for t in tools))
open("agent.json","w").write(json.dumps(
  {"goal":"answer questions","models":[],"trace":"run.jsonl","state":"fluid"}))
EOF
  AVCS commit -m "a day of work" --json >/dev/null; }
mk_agent "$WORK/s4" "['look_up_docs']*27 + ['search','answer','look_up_docs']"
plain infobits
say "(For contrast, an assistant whose answers really depend on what it reads shows"
say " a much richer mix of actions — this one is on autopilot.)"

###############################################################################
story "STORY 5 — One wrong 'fact' poisoned the whole fleet"
say "A fleet of customer-facing agents shares a memory of things they've 'learned'."
say "One of them saves a wrong fact. Does it fade away — or spread to the others?"
echo
mkdir -p "$WORK/s5"; cd "$WORK/s5"; AVCS init --json >/dev/null; write_bench
manifest ",
  \"swarm\": { \"agent1\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"agent2\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"agent3\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"agent4\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"agent5\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"},
    \"agent6\":{\"role\":\"reads shared memory\",\"skill_file\":\"x.md\"} }"
for i in 1 2 3 4 5; do
  case $i in 3|5) setbot broken;; *) setbot q100;; esac
  AVCS commit -m "day $i" --json >/dev/null; AVCS eval --json >/dev/null || true
done
plain contain
say "Shrinking the fleet changes the answer — a smaller team is self-correcting:"
plain contain --fanout 2

printf '\n\033[1m\033[32m▐ Five everyday situations, five clear calls — and not one equation on screen.\033[0m\n'
say "Behind each verdict is real math (the same as the evolution-diagnostics demo),"
say "but the person making the decision never has to see it."
