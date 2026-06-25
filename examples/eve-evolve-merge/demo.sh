#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# agentvcs × Vercel eve — merging a self-evolving agent with its design-time release
# (offline, deterministic, no Vercel account and no LLM needed)
#
# THE STORY
#   A Vercel eve agent (RefundBot) is defined as markdown: instructions + one
#   skill + one sub-agent. It then evolves along TWO lines from the same base:
#
#     • run-time line  (branch `runtime`): the LIVE agent, handed a fraud task,
#       autonomously REWRITES its own skill and SPAWNS a new sub-agent.
#     • design-time line (branch `main`):  the team, editing the files in git with
#       a code agent (e.g. Claude Code), EVOLVES the same skill differently and
#       UPDATES the existing sub-agent.
#
#   Neither line should be lost. `agentvcs merge` reconciles them across every
#   dimension at once:
#     - skill  (markdown / code) → both edited it → CONFLICT → an agent synthesizes
#                                   the conflict-free file (union of both policies).
#     - swarm  (sub-agent topology) → run-time CREATED one, design EVOLVED another
#                                   → merged node-by-node, both kept.
#     - goal+trace → the divergent reasoning is reconciled into one working memory.
#
#   Run it:   bash examples/eve-evolve-merge/demo.sh
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/examples/eve-evolve-merge"
for p in python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    PYBIN="$p"; break
  fi
done
: "${PYBIN:?need python >= 3.10}"
avcs() { PYTHONPATH="$REPO/src" "$PYBIN" -m agentvcs.cli "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
cd "$W"
say()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
note() { printf '\033[0;90m   %s\033[0m\n' "$*"; }

# helper: print HEAD's merged sub-agent swarm (CLI doesn't render it; read the object)
show_swarm() {
  PYTHONPATH="$REPO/src" "$PYBIN" - "$@" <<'PY'
from agentvcs import Repository
r = Repository.open()
c = r.objects.read_obj(r.head_commit())
if not c.get("swarm"):
    print("   (no swarm on this commit)"); raise SystemExit
s = r.objects.read_obj(c["swarm"])
for nid, n in sorted(s["nodes"].items()):
    print(f"   - {nid:16s} {n.get('role','')}")
PY
}

# =====================================================================  BASE
say "BASE — define the eve agent as markdown (instructions + 1 skill + 1 sub-agent)"
mkdir -p agent/skills agent/subagents agent/hooks .eve/agentvcs
cp "$SRC/agent/instructions.md"            agent/instructions.md
cp "$SRC/agent/skills/refund-policy.md"    agent/skills/refund-policy.md
cp "$SRC/agent/subagents/refund-verifier.md" agent/subagents/refund-verifier.md
cp "$REPO/examples/eve/agent/hooks/agentvcs.ts" agent/hooks/agentvcs.ts
printf '.eve\nnode_modules\n.vercel\n' > .agentvcsignore

# agent.json — note the `swarm`: the sub-agent topology is a versioned dimension.
cat > agent.json <<'EOF'
{
  "goal": "RefundBot: process the payments refund queue safely.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": { "provider": "vercel-eve", "auto": true, "model": "claude-opus-4-8" },
  "swarm": {
    "refund-verifier": {
      "role": "verify a refund before it is issued",
      "skill_file": "agent/subagents/refund-verifier.md",
      "parent": "RefundBot"
    }
  },
  "state": "fluid",
  "metrics": {}
}
EOF
# the eve hook captured this base session into the trace agentvcs reads
cat > .eve/agentvcs/trace.jsonl <<'EOF'
{"ts":1,"type":"session.started","data":{"input":{"message":"Stand up RefundBot with a refund policy and a verifier sub-agent."}}}
{"ts":2,"type":"message.completed","data":{"model":"claude-opus-4-8","message":"Created the refund-policy skill and the refund-verifier sub-agent.","usage":{"inputTokens":1500,"outputTokens":120}}}
EOF

avcs init >/dev/null
# init scaffolds a generic agent.json; rewrite it with our eve+swarm manifest
cat > agent.json <<'EOF'
{
  "goal": "RefundBot: process the payments refund queue safely.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": { "provider": "vercel-eve", "auto": true, "model": "claude-opus-4-8" },
  "swarm": {
    "refund-verifier": {
      "role": "verify a refund before it is issued",
      "skill_file": "agent/subagents/refund-verifier.md",
      "parent": "RefundBot"
    }
  },
  "state": "fluid",
  "metrics": {}
}
EOF
avcs commit -m "base: RefundBot + refund-policy skill + refund-verifier sub-agent" | sed 's/^/  /'
note "swarm at base:"; show_swarm

# ==============================================================  RUN-TIME LINE
say "RUN-TIME LINE (branch 'runtime') — the LIVE agent evolves ITSELF"
avcs branch runtime >/dev/null && avcs checkout runtime >/dev/null
note "Task to the live agent: 'suspicious refunds are getting through — handle fraud.'"
note "It has no fraud capability, so it evolves: edits its skill + spawns a sub-agent."

# (a) it appends a fraud rule to its OWN skill
cat > agent/skills/refund-policy.md <<'EOF'
# Skill: Refund Policy

When deciding whether to issue a refund, apply **every** rule below in order. If any
rule rejects, do not refund.

## Rules
- Only refund payments whose status is `captured`.
- Never refund more than the original `amountCents`.
- Flag refunds to a new payee or device as suspicious and route them to the fraud-screener before issuing.
EOF

# (b) it SPAWNS a brand-new sub-agent...
cat > agent/subagents/fraud-screener.md <<'EOF'
# Sub-agent: fraud-screener

Role: score a refund for fraud risk before the verifier runs.

Steps:
1. Compare the payee and device against the original payment.
2. If the payee or device is new, raise risk to HIGH and require step-up approval.
EOF

# (c) ...and registers it in its own swarm (adds a node; goal line untouched)
cat > agent.json <<'EOF'
{
  "goal": "RefundBot: process the payments refund queue safely.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": { "provider": "vercel-eve", "auto": true, "model": "claude-opus-4-8" },
  "swarm": {
    "refund-verifier": {
      "role": "verify a refund before it is issued",
      "skill_file": "agent/subagents/refund-verifier.md",
      "parent": "RefundBot"
    },
    "fraud-screener": {
      "role": "score a refund for fraud risk before the verifier",
      "skill_file": "agent/subagents/fraud-screener.md",
      "parent": "RefundBot"
    }
  },
  "state": "fluid",
  "metrics": {}
}
EOF
# the eve hook captured the agent's autonomous reasoning for this change
cat > .eve/agentvcs/trace.jsonl <<'EOF'
{"ts":10,"type":"session.started","data":{"input":{"message":"Suspicious refunds are getting through — handle fraud."}}}
{"ts":11,"type":"message.completed","data":{"model":"claude-opus-4-8","reasoning":"I have no fraud capability. I will add a fraud rule to refund-policy and spawn a fraud-screener sub-agent that runs before the verifier.","message":"Evolving myself: added a fraud rule + spawned fraud-screener.","toolCalls":[{"name":"write_file","input":{"path":"agent/skills/refund-policy.md"}},{"name":"write_file","input":{"path":"agent/subagents/fraud-screener.md"}}],"usage":{"inputTokens":3200,"outputTokens":420}}}
{"ts":12,"type":"action.result","data":{"name":"write_file","result":{"ok":true}}}
EOF
avcs commit -m "runtime: agent self-evolved — fraud rule + spawned fraud-screener" | sed 's/^/  /'
note "swarm on the run-time line (a sub-agent was CREATED at run-time):"; show_swarm

# ============================================================  DESIGN-TIME LINE
say "DESIGN-TIME LINE (branch 'main') — the team edits the files in git (Claude Code)"
avcs checkout main >/dev/null
note "Independently, a developer evolves the SAME skill differently and UPDATES the verifier."

# (a) design-time edits the SAME skill — a different rule (a 30-day window)
cat > agent/skills/refund-policy.md <<'EOF'
# Skill: Refund Policy

When deciding whether to issue a refund, apply **every** rule below in order. If any
rule rejects, do not refund.

## Rules
- Only refund payments whose status is `captured`.
- Never refund more than the original `amountCents`.
- Reject refunds requested more than 30 days after the capture date.
EOF

# (b) design-time UPDATES the existing sub-agent (adds an amount-cap step)
cat > agent/subagents/refund-verifier.md <<'EOF'
# Sub-agent: refund-verifier

Role: verify a single refund request before RefundBot issues it.

Steps:
1. Confirm the payment exists and its status is `captured`.
2. Confirm the requested amount is ≤ the original captured amount.
3. Reject single refunds above 100,000 cents unless a manager approval token is present.

Return `ok` to proceed, or `reject` with a reason.
EOF
cat > .eve/agentvcs/trace.jsonl <<'EOF'
{"ts":20,"type":"session.started","data":{"input":{"message":"Release: tighten the refund policy with a 30-day window and a high-value cap."}}}
{"ts":21,"type":"message.completed","data":{"model":"claude-opus-4-8","reasoning":"Add a refund-window rule to the policy and a high-value approval cap to the verifier.","message":"Updated refund-policy and refund-verifier for the release.","usage":{"inputTokens":2400,"outputTokens":300}}}
EOF
avcs commit -m "main: design-time release — refund-window rule + verifier amount cap" | sed 's/^/  /'

# =====================================================================  MERGE
say "MERGE — reconcile the run-time line with the design-time release"
note "checkout runtime, then merge main — an agent reconciler resolves the skill conflict."
avcs checkout runtime >/dev/null
# Default reconciler: the deterministic offline stub. Swap in a real LLM brain by
# exporting AGENTVCS_RECONCILE, e.g. the Gemini-backed nanoLoop reconciler:
#   GEMINI_API_KEY=... AGENTVCS_RECONCILE="python3.12 $SRC/gemini_reconcile.py" bash demo.sh
RECON="${AGENTVCS_RECONCILE:-$PYBIN $SRC/reconcile.py}"
note "reconciler: $RECON"
avcs merge main --reconcile "$RECON" --json > merge.json 2>/dev/null || true
PYTHONPATH="$REPO/src" "$PYBIN" - <<'PY'
import json
m = json.load(open("merge.json"))
print(f"   status        : {m.get('status')}")
print(f"   conflicts left: {len(m.get('conflicts', []))}")
print(f"   AI-resolved   : {m.get('ai_resolved')}")
print(f"   reconciled goal: {m.get('goal')}")
PY

say "RESULT 1 — the skill: both lines' rules survive (conflict synthesized, no markers)"
cat agent/skills/refund-policy.md | sed 's/^/   /'

say "RESULT 2 — the swarm: design-time's EVOLVED verifier + run-time's NEW fraud-screener"
show_swarm
note "refund-verifier was evolved on the design line; fraud-screener was created on the"
note "run-time line — node-by-node merge kept BOTH. Neither line was lost."

say "RESULT 3 — one merge commit ties code + swarm + reconciled goal/trace together"
avcs show --trace 2>/dev/null | grep -iE "reconcil|fraud|window|verifier" | sed 's/^/   /' | head -6 || true

say "done — the self-evolved agent and the design-time release are now one agent."
note "Swap the reconciler for a real brain to get LLM-quality synthesis:"
note "  agentvcs merge main --reconcile \"claude -p 'reconcile this agentvcs bundle'\""
note "  agentvcs merge main --target-goal \"prioritize fraud safety over cost\"   # directed merge"
