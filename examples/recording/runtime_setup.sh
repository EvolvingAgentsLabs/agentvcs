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

# seed a realistic Claude Code transcript where the provider will look for it.
# 4 assistant turns carry real usage (input/output/cache) and tool_use blocks, so
# the reconstructed frame shows: $0.5822 spent, ~20.7% context, opus routing,
# and Write/Bash/Read tool usage — all derived, none typed.
ENC="$("$PY" -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
mkdir -p "$PROJECTS/$ENC"
"$PY" - "$PROJECTS/$ENC/session.jsonl" "$DEMO" <<'PY'
import json, sys
out, cwd = sys.argv[1], sys.argv[2]

def U(model, inp, output, cache):  # assistant usage block
    return {"input_tokens": inp, "output_tokens": output,
            "cache_read_input_tokens": cache, "cache_creation_input_tokens": 0}

lines = [
 {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "2026-06-14T01:00:00Z",
  "message": {"role": "user",
              "content": "Implement a correct add(a, b) in app.py and test it."}},
 {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "2026-06-14T01:00:04Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8",
   "usage": U("claude-opus-4-8", 8000, 600, 0),
   "content": [
     {"type": "thinking", "thinking": "Start with the obvious implementation, then test."},
     {"type": "text", "text": "I'll write add() and a quick check."},
     {"type": "tool_use", "name": "Write", "input": {"file_path": "app.py"}}]}},
 {"type": "user", "cwd": cwd, "uuid": "u2", "timestamp": "2026-06-14T01:00:06Z",
  "message": {"role": "user", "content": [{"type": "tool_result", "content": "wrote app.py"}]}},
 {"type": "assistant", "cwd": cwd, "uuid": "a2", "timestamp": "2026-06-14T01:00:10Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8",
   "usage": U("claude-opus-4-8", 7000, 900, 18000),
   "content": [
     {"type": "text", "text": "Running the check."},
     {"type": "tool_use", "name": "Bash", "input": {"command": "python3 -c 'import app'"}}]}},
 {"type": "user", "cwd": cwd, "uuid": "u3", "timestamp": "2026-06-14T01:00:12Z",
  "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
 {"type": "assistant", "cwd": cwd, "uuid": "a3", "timestamp": "2026-06-14T01:00:16Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8",
   "usage": U("claude-opus-4-8", 6000, 800, 30000),
   "content": [
     {"type": "text", "text": "Re-reading the spec for the edge cases."},
     {"type": "tool_use", "name": "Read", "input": {"file_path": "app.py"}}]}},
 {"type": "user", "cwd": cwd, "uuid": "u4", "timestamp": "2026-06-14T01:00:18Z",
  "message": {"role": "user", "content": [{"type": "tool_result", "content": "def add..."}]}},
 {"type": "assistant", "cwd": cwd, "uuid": "a4", "timestamp": "2026-06-14T01:00:22Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8",
   "usage": U("claude-opus-4-8", 3306, 602, 38000),
   "content": [
     {"type": "text", "text": "Done — add(a, b) is in app.py."}]}},
]
open(out, "w").write("\n".join(json.dumps(l) for l in lines) + "\n")
PY

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
m["budget"] = {"ceiling_usd": 2.0}
m["eval"] = {"command": "python3 -c 'import app; assert app.add(2,2)==4'"}
p.write_text(json.dumps(m, indent=2) + "\n")
PY
agentvcs commit -m "add() v1 (buggy)" >/dev/null

export PS1='\[\033[38;5;208m\]➜\[\033[0m\] \[\033[36m\]add-fn\[\033[0m\] $ '
clear
