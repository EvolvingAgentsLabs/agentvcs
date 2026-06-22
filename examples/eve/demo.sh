#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# agentvcs + Vercel eve — the 60-second demo (offline, no Vercel account needed)
#
# Tells the story that sells the integration: an eve agent builds a refund tool,
# then HALLUCINATES a non-existent package on its next turn and the build fails.
# Instead of restarting the whole session, the dev `agentvcs rollback`s to the
# good turn — code AND trace restored together in one commit — fixes the file,
# and resumes the eve session from there.
#
# This runs against a captured eve event trace, so it needs no running eve
# project. The *real* integration is the hook at agent/hooks/agentvcs.ts; this
# script just replays what that hook would have captured, so the flow is
# recordable today.
#
#   bash examples/eve/demo.sh
# ---------------------------------------------------------------------------
set -euo pipefail

# --- locate the agentvcs source so we can run the CLI from a checkout ---------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
avcs() { PYTHONPATH="$REPO/src" python3 -m agentvcs.cli "$@"; }
# prefer python3.10+; fall back to python3
for p in python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    PYBIN="$p"; break
  fi
done
avcs() { PYTHONPATH="$REPO/src" "$PYBIN" -m agentvcs.cli "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
cd "$W"
say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

# --- the eve agent source (the "code" dimension) ------------------------------
mkdir -p agent/tools agent/hooks .eve/agentvcs
cp "$REPO/examples/eve/agent/instructions.md" agent/instructions.md
cp "$REPO/examples/eve/agent/hooks/agentvcs.ts" agent/hooks/agentvcs.ts
cat > .agentvcsignore <<'EOF'
.eve
node_modules
.vercel
EOF
cat > agent.json <<'EOF'
{
  "goal": "A Vercel eve agent that builds and maintains a payments refund queue.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": { "provider": "vercel-eve", "auto": true, "model": "claude-opus-4-8" },
  "state": "fluid",
  "metrics": {}
}
EOF

# the GOOD refund tool + the trace eve's hook captured for turn 1
cat > agent/tools/refund.ts <<'EOF'
import { defineTool } from "eve/tools";
import { z } from "zod";
export default defineTool({
  description: "Issue a refund for a payment request.",
  inputSchema: z.object({ requestId: z.string(), amountCents: z.number().int().positive() }),
  async execute({ requestId, amountCents }) {
    return { requestId, amountCents, status: "refunded" };
  },
});
EOF
cat > .eve/agentvcs/trace.jsonl <<'EOF'
{"ts":1,"type":"session.started","data":{"input":{"message":"Add a refund handler tool for the payments queue."}}}
{"ts":2,"type":"message.completed","data":{"model":"claude-opus-4-8","reasoning":"base case first; idempotency next","message":"Creating the refund tool.","toolCalls":[{"name":"write_file","input":{"path":"agent/tools/refund.ts"}}],"usage":{"inputTokens":1820,"outputTokens":240}}}
{"ts":3,"type":"action.result","data":{"name":"write_file","result":{"ok":true}}}
{"ts":4,"type":"message.completed","data":{"model":"claude-opus-4-8","message":"Done — the refund tool is added and the build is green.","usage":{"inputTokens":2100,"outputTokens":90}}}
EOF

say "agentvcs init --eve   (wire the trace to the eve agent)"
avcs init --eve >/dev/null
avcs commit -m "turn 1: add refund tool" | sed 's/^/  /'

# --- turn 2: the agent hallucinates a package and the build fails -------------
cat > agent/tools/refund.ts <<'EOF'
import { defineTool } from "eve/tools";
import { dedupe } from "@vercel/magic-dedupe";   // <-- hallucinated package
import { z } from "zod";
export default defineTool({
  description: "Issue a refund for a payment request (idempotent).",
  inputSchema: z.object({ requestId: z.string(), amountCents: z.number().int().positive() }),
  async execute({ requestId, amountCents }) {
    return dedupe(requestId, async () => ({ requestId, amountCents, status: "refunded" }));
  },
});
EOF
cat >> .eve/agentvcs/trace.jsonl <<'EOF'
{"ts":5,"type":"session.started","data":{"input":{"message":"Now make it idempotent so retries don't double-refund."}}}
{"ts":6,"type":"message.completed","data":{"model":"claude-opus-4-8","reasoning":"Vercel must ship a dedupe primitive; import @vercel/magic-dedupe","message":"I'll add idempotency using Vercel's dedupe API.","toolCalls":[{"name":"write_file","input":{"path":"agent/tools/refund.ts"}}],"usage":{"inputTokens":2600,"outputTokens":310}}}
{"ts":7,"type":"action.result","data":{"name":"build","isError":true,"error":"Cannot find module '@vercel/magic-dedupe'"}}
{"ts":8,"type":"turn.failed","data":{"model":"claude-opus-4-8","error":"build failed: unresolved import '@vercel/magic-dedupe' (hallucinated package)"}}
EOF

say "agentvcs commit   (turn 2 — the agent hallucinated a package)"
avcs commit -m "turn 2: add idempotency" | sed 's/^/  /'

say "agentvcs log   (two turns, one good, one broken)"
avcs log | sed 's/^/  /'

say "agentvcs show --trace   (the hallucination is captured: turn.failed + bad import)"
avcs show --trace | grep -iE "magic-dedupe|turn.failed|dedupe API|build failed" | sed 's/^/  /' || true

say "agentvcs rollback   (restore the good turn — code AND trace, one undo)"
avcs rollback | sed 's/^/  /'

say "the working tree is restored — refund.ts no longer imports the hallucinated package:"
if grep -q "magic-dedupe" agent/tools/refund.ts; then echo "  !! still bad"; else echo "  ✓ refund.ts is back to the green turn-1 version"; fi
say "and HEAD's committed trace is the clean turn again:"
if avcs show --trace | grep -qi "turn.failed"; then echo "  !! failure still in trace"; else echo "  ✓ no failure in the committed trace"; fi

# --- resume: fix the tool correctly and continue the eve session -------------
cat > agent/tools/refund.ts <<'EOF'
import { defineTool } from "eve/tools";
import { z } from "zod";
const seen = new Set<string>();   // real idempotency: no hallucinated import
export default defineTool({
  description: "Issue a refund for a payment request (idempotent).",
  inputSchema: z.object({ requestId: z.string(), amountCents: z.number().int().positive() }),
  async execute({ requestId, amountCents }) {
    if (seen.has(requestId)) return { requestId, amountCents, status: "already_refunded" };
    seen.add(requestId);
    return { requestId, amountCents, status: "refunded" };
  },
});
EOF
say "resume from the good state with a real fix:"
avcs commit -m "turn 2 (resumed): idempotent refund, no hallucinated import" | sed 's/^/  /'
avcs log | sed 's/^/  /'

say "done — the eve agent recovered without restarting the session."
