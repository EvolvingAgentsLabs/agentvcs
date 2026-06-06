#!/usr/bin/env bash
#
# Fair blind test: scaffold a project that ALREADY uses agentvcs (via `agentvcs new`),
# then give the agent an evolving, multi-step task that NEVER mentions agentvcs.
# The question: does the pre-wired context (agent.json, AGENTS.md, the skill, .mcp.json)
# make a real agent adopt the loop on its own?
#
#   bash examples/blind-fleet-task/setup.sh
#   cd examples/blind-fleet-task/sandbox
#   claude            # paste ../TASK.md  (do NOT add any agentvcs hint)
#   python3 ../../claude-code-task/score.py .
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SANDBOX="$HERE/sandbox"

rm -rf "$SANDBOX"
if command -v agentvcs >/dev/null 2>&1; then
  agentvcs new "$SANDBOX" >/dev/null
else
  PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli new "$SANDBOX" >/dev/null
fi

echo "Ready: $SANDBOX"
echo "  This project already uses agentvcs (agent.json, AGENTS.md, skill, .mcp.json, 1 commit)."
echo
echo "Next (blind — give ONLY the task, no agentvcs hint):"
echo "  cd \"$SANDBOX\""
echo "  claude            # paste $HERE/TASK.md"
echo
echo "Then score whether the context alone drove adoption:"
echo "  python3 \"$ROOT/examples/claude-code-task/score.py\" \"$SANDBOX\""
