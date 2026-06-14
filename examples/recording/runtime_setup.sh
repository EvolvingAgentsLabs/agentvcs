#!/usr/bin/env bash
# Builds a self-contained toy project so runtime-trust.tape can record a REAL run
# of the runtime-visibility layer AND the eval-gated trust loop. We seed a genuine
# Claude Code session transcript (with real per-turn token usage + tool_use blocks)
# into the exact path the provider reads, so `agentvcs runtime` reconstructs an
# authentic frame — dollars, context %, routing, tools — with zero on-screen fakery.
# One coherent story: the agent was asked to implement add(a,b), and shipped a buggy
# version; the trust loop then proves and freezes the fix.
#
# Sourced by the tape (so env + the `agentvcs` shim persist in the recording shell).
# Cleanup helper: `bash runtime_setup.sh --clean`.

# Resolve the repo root. BASH_SOURCE is the reliable path under `vhs`; fall back to
# the canonical in-repo location (this script is at examples/recording/) so it also
# works when sourced from the repo root with BASH_SOURCE unset.
_SELF="${BASH_SOURCE[0]:-examples/recording/runtime_setup.sh}"
ROOT="$(cd "$(dirname "$_SELF")/../.." && pwd)"
DEMO="$HOME/.cache/agentvcs-demo/add-fn"
PROJECTS="$HOME/.claude/projects"
# Pin a modern interpreter — agentvcs needs >=3.10 and is pure stdlib.
PY="$(for c in python3.12 python3.11 python3.10 python3; do command -v "$c" >/dev/null 2>&1 && { "$c" -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null && { echo "$c"; break; }; }; done)"
PY="${PY:-python3}"

if [ "$1" = "--clean" ]; then
  enc="$(${PY:-python3} -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
  rm -rf "$DEMO" "$PROJECTS/$enc"
  echo "cleaned $DEMO and $PROJECTS/$enc"
  return 0 2>/dev/null || exit 0
fi

rm -rf "$DEMO"; mkdir -p "$DEMO"

# `agentvcs` as a plain command for the demo (no global install needed)
agentvcs() { PYTHONPATH="$ROOT/src" "$PY" -m agentvcs.cli "$@"; }
export -f agentvcs 2>/dev/null || true

# Install the REAL session frame. fixtures/runtime-session.jsonl is a genuine
# Claude Code transcript reduced to frame-only fields (real model/usage/tool names,
# all conversation content stripped — see make_runtime_fixture.py). The provider
# keys transcripts by directory, so we drop it where it looks for THIS demo's cwd.
# Nothing about the frame is typed or invented: `agentvcs runtime` reconstructs it.
ENC="$("$PY" -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
mkdir -p "$PROJECTS/$ENC"
cp "$ROOT/examples/recording/fixtures/runtime-session.jsonl" "$PROJECTS/$ENC/session.jsonl"

# the app the agent "produced" — deliberately WRONG, so the eval gate has teeth
cat > "$DEMO/app.py" <<'PY'
def add(a, b):
    return a - b   # bug: should be a + b
PY

cd "$DEMO" || return

# init wired to the live session AND runtime mode; declare the eval the gate enforces
agentvcs init --claude-code --runtime >/dev/null
"$PY" - <<'PY'
import json, pathlib
p = pathlib.Path("agent.json"); m = json.loads(p.read_text())
m["goal"] = "implement a correct add(a, b)"
# ceiling above the real spend; window=1M because the captured turns are the Opus
# 1M-context model (the transcript records the id without the [1m] suffix, so the
# default 200k table would otherwise overstate context pressure).
m["budget"] = {"ceiling_usd": 25.0, "windows": {"opus": 1000000}}
m["eval"] = {"command": "python3 -c 'import app; assert app.add(2,2)==4'"}
p.write_text(json.dumps(m, indent=2) + "\n")
PY
agentvcs commit -m "add() v1 (buggy)" >/dev/null

export PS1='\[\033[38;5;208m\]➜\[\033[0m\] \[\033[36m\]add-fn\[\033[0m\] $ '
clear
