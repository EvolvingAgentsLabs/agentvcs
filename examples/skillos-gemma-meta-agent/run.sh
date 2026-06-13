#!/usr/bin/env bash
#
# SkillOS × Gemma × agentvcs — the full meta-agent demo.
#
# A meta-agent (meta_agent.py) runs a SkillOS cognitive pipeline on Gemini
# (option 1) / local Gemma via Ollama (fallback) / an offline deterministic
# backend (so this always runs, even in CI). Each iteration it PLANS → GENERATES
# → EXECUTES → EVALUATES a sub-agent, and we version every iteration with
# agentvcs across all four dimensions — code + goal + models + trace — rolling
# back a regression and freezing the trusted result into a deterministic recipe.
#
# The trace is captured automatically: agent.json declares the `skillos` trace
# provider, so each `agentvcs commit` vacuums .skillos/sessions/*.jsonl. You
# maintain no trace file.
#
#   bash run.sh                                        # offline, fully reproducible
#   GEMINI_API_KEY=AI...        bash run.sh            # real Gemini reasoning
#   OLLAMA_BASE_URL=http://localhost:11434/v1 bash run.sh   # local Gemma 4
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
FMT="$HERE/_fmt.py"

if command -v avcs >/dev/null 2>&1; then
  AVCS() { avcs "$@"; }
else
  AVCS() { PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli "$@"; }
fi

av() { echo "  \$ agentvcs $* --json"; AVCS "$@" --json | python3 "$FMT"; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
note() { printf '\033[2m   %s\033[0m\n' "$*"; }

WORK="$HERE/workdir"
rm -rf "$WORK"; mkdir -p "$WORK"
# Bring the meta-agent + its markdown skills into the workdir (the versioned code).
cp "$HERE/meta_agent.py" "$WORK/"
cp -r "$HERE/skills" "$WORK/"
cd "$WORK"

# Session logs are the *trace* dimension (captured by the provider), not *code* —
# keep them out of the code tree.
echo ".skillos" > .agentvcsignore

# Write agent.json for this iteration: the goal moves, the trace is the SkillOS
# provider, models are Gemini-first with a local Gemma fallback (auto-pinned to
# whatever actually ran).
manifest() { # manifest "<goal>"
  cat > agent.json <<EOF
{
  "goal": "$1",
  "models": [
    { "provider": "google", "params": { "temperature": 0.9 }, "auto": true },
    { "provider": "ollama", "model": "gemma4", "note": "local fallback via Ollama" }
  ],
  "trace": { "provider": "skillos", "auto": true,
             "redact": ["sk-[A-Za-z0-9_-]+", "(?i)(api[_-]?key|token|secret)\\\\s*[:=]\\\\s*\\\\S+"] },
  "state": "fluid",
  "metrics": {}
}
EOF
}

# Run one meta-agent iteration; prints its result JSON line.
meta() { # meta <stage> "<goal>"
  echo "  \$ python meta_agent.py --stage $1"
  python3 meta_agent.py --stage "$1" --goal "$2" | python3 -c '
import json, sys
d = json.load(sys.stdin)
v = "PASS" if d["passed"] else "FAIL"
print("  -> built sub-agent on {} ({}); eval {} (target={!r})".format(
    d["backend"], d["model"], v, d["target"]["actual"]))'
}

############################################################################
step "Iteration 0 — bootstrap the meta-agent repo"
note "No .agentvcs here yet; initializing so the meta-agent can version its work."
av init

GOAL_V1="Extract the top-3 keywords from a block of text."
GOAL_V2="Extract the top-3 keywords from text, ignoring common stop-words."

############################################################################
step "Iteration 1 — meta-agent builds its first sub-agent (fluid)"
note "SkillOS pipeline: ingress → routing → planning(HWM) → execution → memory → egress."
manifest "$GOAL_V1"
meta v1 "$GOAL_V1"
av trace                       # which SkillOS session is hooked (+ model that ran)
av commit -m "v1: top-keywords sub-agent (naive) — eval passes"

############################################################################
step "Iteration 2 — evolve the GOAL, not just the code"
note "Product asks: ignore stop-words so the keywords are meaningful."
manifest "$GOAL_V2"
meta v2 "$GOAL_V2"
av commit -m "v2: ignore stop-words — eval passes"
note "Which dimension actually moved?"
av diff                        # goal + code (+ trace), models unchanged

############################################################################
step "Iteration 3 — a BAD idea (regression)"
note "Meta-agent 'optimizes' by only scanning the first 5 words. This overfits."
manifest "$GOAL_V2"
meta v3 "$GOAL_V2"             # eval FAILS
av commit -m "v3: collapse to first-5-words (experimental)"
note "The eval failed — this build is NOT trusted."

############################################################################
step "Iteration 3 ↩ — ROLLBACK the regression"
note "Restore the full prior state: code + goal + trace, in one move."
av rollback
grep -q "if w not in STOP" subagent/tool.py && note "subagent restored to the v2 stop-word logic ✓"

############################################################################
step "Iteration 4 — the proper improvement"
note "Rebuild the stop-word-aware sub-agent properly; eval passes again."
manifest "$GOAL_V2"
meta v4 "$GOAL_V2"
av commit -m "v4: stop-word-aware sub-agent (eval passes)"

############################################################################
step "Freeze — crystallize the trusted meta-agent"
note "This is solid. Freeze it: models → temperature 0, SkillOS trace → recipe."
av freeze

############################################################################
step "Final history"
av log
note "The crystallized recipe (deterministic, cheap to re-run):"
echo; cat crystal/*.json | python3 -m json.tool 2>/dev/null | head -40 || cat crystal/*.json

printf '\n\033[1m== Done ==\033[0m\n'
note "See it as a chat:  PYTHONPATH=$ROOT/src python3 -m agentvcs.cli -C $WORK ui"
note "The meta-agent's SkillOS reasoning (thinking/plan/exec) renders per commit."
