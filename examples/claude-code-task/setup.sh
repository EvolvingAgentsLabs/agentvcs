#!/usr/bin/env bash
#
# Prepare a fresh sandbox where Claude Code can attempt the task with agentvcs
# available as a skill and (optionally) as an MCP server.
#
#   bash examples/claude-code-task/setup.sh
#   cd examples/claude-code-task/sandbox
#   claude            # then paste the contents of ../PROMPT.md
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SANDBOX="$HERE/sandbox"

rm -rf "$SANDBOX"
mkdir -p "$SANDBOX/.claude/skills"

# 1. Ship the agentvcs skill so the agent can discover it in the sandbox.
cp -r "$ROOT/.claude/skills/agentvcs" "$SANDBOX/.claude/skills/agentvcs"

# 2. Wire the MCP server (project-scoped .mcp.json that Claude Code reads).
if command -v agentvcs-mcp >/dev/null 2>&1; then
  cat > "$SANDBOX/.mcp.json" <<EOF
{ "mcpServers": { "agentvcs": { "command": "agentvcs-mcp" } } }
EOF
else
  cat > "$SANDBOX/.mcp.json" <<EOF
{ "mcpServers": { "agentvcs": {
  "command": "python3",
  "args": ["-m", "agentvcs.mcp_server"],
  "env": { "PYTHONPATH": "$ROOT/src" }
} } }
EOF
fi

# 3. Make sure the CLI is reachable; warn if not installed.
if ! command -v avcs >/dev/null 2>&1; then
  cat >> "$SANDBOX/.mcp.json.note" <<EOF
The 'avcs'/'agentvcs' CLI is not on PATH. Either install it:
    pip install -e "$ROOT"
or the agent can run it from source with:
    PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli ...
EOF
fi

echo "Sandbox ready: $SANDBOX"
echo "  - agentvcs skill installed at .claude/skills/agentvcs/"
echo "  - MCP server configured in .mcp.json"
if ! command -v avcs >/dev/null 2>&1; then
  echo "  - NOTE: CLI not installed — see .mcp.json.note (run: pip install -e \"$ROOT\")"
fi
echo
echo "Next:"
echo "  cd \"$SANDBOX\""
echo "  claude        # paste the task from $HERE/PROMPT.md"
echo
echo "After the agent finishes, score it:"
echo "  python3 \"$HERE/score.py\" \"$SANDBOX\""
