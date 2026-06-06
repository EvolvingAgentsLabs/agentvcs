#!/usr/bin/env bash
#
# The "fire test": a simulated autonomous agent building a support-ticket router,
# driving agentvcs entirely in --json mode (the agent contract). It iterates,
# introduces a regression, ROLLS BACK the bad iteration, fixes it properly, and
# finally FREEZES (crystallizes) the trusted solution into a deterministic recipe.
#
# Reproducible: re-run any time; it rebuilds workdir/ from scratch.
#   bash examples/agent-loop-demo/run.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
FMT="$HERE/_fmt.py"

# Prefer the installed CLI; fall back to running from source (no install needed).
if command -v avcs >/dev/null 2>&1; then
  AVCS() { avcs "$@"; }
else
  AVCS() { PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli "$@"; }
fi

# Run an agentvcs command in --json mode and render it like an agent session.
av() {
  echo "  \$ agentvcs $* --json"
  AVCS "$@" --json | python3 "$FMT"
}

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
note() { printf '\033[2m   %s\033[0m\n' "$*"; }

WORK="$HERE/workdir"
rm -rf "$WORK"
mkdir -p "$WORK/traces"
cd "$WORK"

# --- helpers an "agent" uses to write the four dimensions -------------------
manifest() { # manifest "<goal>"
  cat > agent.json <<EOF
{
  "goal": "$1",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8", "params": { "temperature": 1.0 } }],
  "trace": "traces/run.jsonl",
  "state": "fluid",
  "metrics": {}
}
EOF
}
trace() { echo "$1" >> traces/run.jsonl; }

############################################################################
step "Iteration 0 — bootstrap"
note "Agent: no .agentvcs here yet; initializing so I can version my work."
av init
: > traces/run.jsonl

############################################################################
step "Iteration 1 — first working version (fluid)"
note "Agent goal: route support tickets to a queue."
manifest "Route incoming support tickets to the correct queue."
cat > router.py <<'EOF'
def route(text):
    t = text.lower()
    if "invoice" in t or "charge" in t:
        return "billing"
    if "error" in t or "crash" in t:
        return "tech"
    return "general"
EOF
trace '{"role":"planner","content":"Classify by keywords into billing/tech/general."}'
trace '{"role":"worker","content":"Implemented keyword router."}'
av commit -m "v1: keyword ticket router"

############################################################################
step "Iteration 2 — evolve the GOAL, not just code"
note "Agent: product asked to fast-track urgent tickets. Updating the goal + code."
manifest "Route support tickets to a queue AND flag urgent ones for fast-track."
cat > router.py <<'EOF'
def route(text):
    t = text.lower()
    urgent = "urgent" in t or "asap" in t
    if "invoice" in t or "charge" in t:
        queue = "billing"
    elif "error" in t or "crash" in t:
        queue = "tech"
    else:
        queue = "general"
    return {"queue": queue, "urgent": urgent}
EOF
trace '{"role":"planner","content":"Add urgency flag; return structured result."}'
trace '{"role":"worker","content":"Added urgent detection."}'
av commit -m "v2: add urgency flag"
note "Inspecting what changed across dimensions:"
av diff

############################################################################
step "Iteration 3 — a BAD idea (regression)"
note "Agent: let me 'simplify' the routing... (this will overfit and break it)."
cat > router.py <<'EOF'
def route(text):
    # premature 'optimization': route almost everything to tech
    return {"queue": "tech", "urgent": "urgent" in text.lower()}
EOF
trace '{"role":"worker","content":"Collapsed routing to a single branch."}'
av commit -m "v3: collapse routing (experimental)"
note "Agent runs its eval... billing tickets now misrouted. Accuracy dropped."

############################################################################
step "Iteration 3 ↩ — ROLLBACK the regression"
note "Agent: that made it worse. Restore the full prior state (code + goal + trace)."
av rollback
note "Verify the good code is back:"
grep -q 'queue = "billing"' router.py && note "router.py restored to v2 logic ✓"

############################################################################
step "Iteration 4 — the proper improvement"
note "Agent: add a real 'refunds' queue instead of collapsing everything."
manifest "Route tickets across billing/tech/refunds/general AND flag urgent ones."
cat > router.py <<'EOF'
def route(text):
    t = text.lower()
    urgent = "urgent" in t or "asap" in t
    if "refund" in t or "money back" in t:
        queue = "refunds"
    elif "invoice" in t or "charge" in t:
        queue = "billing"
    elif "error" in t or "crash" in t:
        queue = "tech"
    else:
        queue = "general"
    return {"queue": queue, "urgent": urgent}
EOF
trace '{"role":"planner","content":"Add dedicated refunds queue."}'
trace '{"role":"worker","content":"Implemented refunds routing; eval passes."}'
av commit -m "v4: add refunds queue (eval passes)"

############################################################################
step "Freeze — crystallize the trusted solution"
note "Agent: this is solid. Freeze it to a deterministic, temperature-0 recipe."
av freeze

############################################################################
step "Final history"
av log
note "The crystallized recipe (what makes re-runs cheap & reproducible):"
echo
cat crystal/*.json

printf '\n\033[1m== Done ==\033[0m\n'
note "An agent did all of this with only --json output and stable error codes:"
note "iterate → inspect per dimension → rollback a mistake → freeze when trusted."
