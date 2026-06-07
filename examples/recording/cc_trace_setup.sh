#!/usr/bin/env bash
# Builds a self-contained toy project so cc-trace.tape can record a REAL run of the
# Claude Code trace provider — including genuine auto-discovery. We seed a sample
# session transcript into the exact path the provider reads
# (~/.claude/projects/<cwd "/"->"-">/…jsonl), so `init --claude-code`, `trace`,
# `commit`, and `show --trace` all work with zero on-screen trickery.
#
# Sourced by the tape (so env + the `agentvcs` shim persist in the recording shell).
# Cleanup helper at the bottom: `bash cc_trace_setup.sh --clean`.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEMO="$HOME/.cache/agentvcs-demo/triage-bot"
PROJECTS="$HOME/.claude/projects"

if [ "$1" = "--clean" ]; then
  enc="$(python3 -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
  rm -rf "$DEMO" "$PROJECTS/$enc"
  echo "cleaned $DEMO and $PROJECTS/$enc"
  return 0 2>/dev/null || exit 0
fi

rm -rf "$DEMO"; mkdir -p "$DEMO"

# `agentvcs` as a plain command for the demo (no global install needed)
agentvcs() { PYTHONPATH="$ROOT/src" python3 -m agentvcs.cli "$@"; }
export -f agentvcs 2>/dev/null || true

# seed a realistic Claude Code transcript where the provider will look for it
ENC="$(python3 -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
mkdir -p "$PROJECTS/$ENC"
python3 - "$PROJECTS/$ENC/session.jsonl" "$DEMO" <<'PY'
import json, sys
out, cwd = sys.argv[1], sys.argv[2]
app = "def handle(msg):\n    return classify(msg)  # -> {queue, urgent}\n"
lines = [
 {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "2026-06-07T20:00:00Z",
  "message": {"role": "user",
              "content": "Create a support-triage queue in app.py: classify a message and flag urgent ones."}},
 {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "2026-06-07T20:00:04Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8", "content": [
     {"type": "thinking", "thinking": "Keep it minimal: a keyword classifier with an urgent flag, one handle()."},
     {"type": "text", "text": "I'll add a small triage function."},
     {"type": "tool_use", "name": "Write", "input": {"file_path": "app.py", "content": app}}]}},
 {"type": "user", "cwd": cwd, "uuid": "u2", "timestamp": "2026-06-07T20:00:06Z",
  "message": {"role": "user", "content": [{"type": "tool_result", "content": "File written: app.py"}]}},
 {"type": "assistant", "cwd": cwd, "uuid": "a2", "timestamp": "2026-06-07T20:00:08Z",
  "message": {"role": "assistant", "model": "claude-opus-4-8", "content": [
     {"type": "text", "text": "Done — app.py routes refunds to billing and flags urgent messages."}]}},
]
open(out, "w").write("\n".join(json.dumps(l) for l in lines) + "\n")
PY

# the app the agent "produced"
cat > "$DEMO/app.py" <<'PY'
def handle(msg):
    t = msg.lower()
    return {"queue": "billing" if "refund" in t else "general",
            "urgent": "urgent" in t}
PY

cd "$DEMO" || return

# init the repo wired to the live session (done here so the recording can OPEN by
# showing the wiring with `cat agent.json` instead of init's prose), then give the
# goal dimension a meaningful value.
agentvcs init --claude-code >/dev/null
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("agent.json"); m = json.loads(p.read_text())
m["goal"] = "Build a support-triage queue"
p.write_text(json.dumps(m, indent=2) + "\n")
PY

export PS1='\[\033[38;5;208m\]➜\[\033[0m\] \[\033[36m\]triage-bot\[\033[0m\] $ '
clear
