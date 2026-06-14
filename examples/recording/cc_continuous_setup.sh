#!/usr/bin/env bash
# Sets up a self-contained project for continuous.tape — the "agentvcs running
# continuously inside Claude Code" demo. It installs the SAME real captured-session
# fixture the runtime demo uses (fixtures/runtime-session.jsonl — genuine model/
# usage/tool numbers, all conversation content stripped), wires a runtime-mode repo
# to it, and seeds a couple of checkpoint commits so `log` shows session history.
# Nothing is fabricated: `statusline` / `runtime` / `commit` all read the real frame.
#
# Sourced by the tape. Cleanup: `bash cc_continuous_setup.sh --clean`.

_SELF="${BASH_SOURCE[0]:-examples/recording/cc_continuous_setup.sh}"
ROOT="$(cd "$(dirname "$_SELF")/../.." && pwd)"
DEMO="$HOME/.cache/agentvcs-demo/cc-continuous"
PROJECTS="$HOME/.claude/projects"
PY="$(for c in python3.12 python3.11 python3.10 python3; do command -v "$c" >/dev/null 2>&1 && { "$c" -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null && { echo "$c"; break; }; }; done)"
PY="${PY:-python3}"

if [ "$1" = "--clean" ]; then
  enc="$(${PY:-python3} -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
  rm -rf "$DEMO" "$PROJECTS/$enc"
  echo "cleaned $DEMO and $PROJECTS/$enc"
  return 0 2>/dev/null || exit 0
fi

rm -rf "$DEMO"; mkdir -p "$DEMO"
agentvcs() { PYTHONPATH="$ROOT/src" "$PY" -m agentvcs.cli "$@"; }
export -f agentvcs 2>/dev/null || true

# install the real captured-session fixture where the provider looks for this cwd
ENC="$("$PY" -c "import os;print(os.path.realpath('$DEMO').replace('/','-'))")"
mkdir -p "$PROJECTS/$ENC"
cp "$ROOT/examples/recording/fixtures/runtime-session.jsonl" "$PROJECTS/$ENC/session.jsonl"

echo 'def handle(msg): return {"queue": "billing"}' > "$DEMO/app.py"
cd "$DEMO" || return

agentvcs init --claude-code --runtime >/dev/null
"$PY" - <<'PY'
import json, pathlib
p = pathlib.Path("agent.json"); m = json.loads(p.read_text())
m["goal"] = "ship a refunds-triage queue"
m["budget"] = {"ceiling_usd": 50.0, "windows": {"opus": 1000000}}
p.write_text(json.dumps(m, indent=2) + "\n")
PY

# a couple of prior checkpoints so `log` shows the session evolving (each Stop hook
# fires one of these in a real session)
agentvcs commit -m "cc checkpoint: scaffolding" >/dev/null 2>&1
agentvcs commit -m "cc checkpoint: classifier"  >/dev/null 2>&1

export PS1='\[\033[38;5;208m\]➜\[\033[0m\] \[\033[36m\]refunds-queue\[\033[0m\] $ '
clear
