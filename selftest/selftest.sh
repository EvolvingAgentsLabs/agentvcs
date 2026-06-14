#!/usr/bin/env bash
# agentvcs self-test harness — run by a Claude Code agent to verify the runtime
# integration against its OWN live session (real tokens/tools, not a simulation),
# plus the deterministic eval-gate / recall / replay / cross-runtime checks.
#
#   bash selftest/selftest.sh
#
# IMPORTANT: run this from inside the Claude Code session you want to measure, and
# ideally after you've already done a little real work this session (so the live
# trace has substance). It must run somewhere under the directory Claude Code was
# launched in, or the live-session checks degrade to WARN (the trace provider keys
# transcripts by cwd).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${AVCS_SRC:-$(cd "$HERE/../src" && pwd)}"

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "FATAL: need python >= 3.10 on PATH"; exit 1; }

avcs()    { PYTHONPATH="$SRC" "$PY" -m agentvcs.cli "$@"; }
jassert() { "$PY" -c "import sys,json
try:
    d=json.load(sys.stdin)
    sys.exit(0 if ($1) else 1)
except Exception:
    sys.exit(1)"; }

PASS=0; FAIL=0; WARN=0
ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
no()   { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
warn() { echo "  WARN  $1"; WARN=$((WARN+1)); }
hr()   { echo "------------------------------------------------------------"; }
# capture-first so a (correctly) non-zero exit from avcs can't poison the check
assert_json() { if printf '%s' "$3" | jassert "$2"; then ok "$1"; else no "$1"; fi; }

SANDBOX="$HERE/.sandbox"; rm -rf "$SANDBOX"; mkdir -p "$SANDBOX"
echo "agentvcs self-test"
echo "  python: $($PY --version 2>&1)   src: $SRC"
echo "  sandbox: $SANDBOX"

# =====================================================================
# 1. LIVE RUNTIME VISIBILITY — what your closed runtime hides, from THIS session
# =====================================================================
hr; echo "[1] Live runtime visibility (claude-code provider, runtime mode)"
LIVE="$SANDBOX/live"; mkdir -p "$LIVE"; echo 'print("selftest")' > "$LIVE/app.py"
avcs -C "$LIVE" init --claude-code --runtime >/dev/null 2>&1
"$PY" - "$LIVE" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])/"agent.json"
m=json.loads(p.read_text())
m["goal"]="agentvcs self-test: exercise the live runtime integration"
m["budget"]={"ceiling_usd":2.0}          # so dollar math + the bar light up
p.write_text(json.dumps(m,indent=2))
PY
avcs -C "$LIVE" commit -m "selftest live snapshot" >/dev/null 2>&1

RT="$(avcs -C "$LIVE" runtime --json 2>/dev/null)"
echo "  --- your own hidden frame (this is the headline feature) ---"
avcs -C "$LIVE" runtime 2>/dev/null | sed 's/^/    /'
echo "  ------------------------------------------------------------"

if printf '%s' "$RT" | jassert "d['runtime']['turns']>0"; then
  ok "trace captured straight from THIS Claude Code session"
else
  warn "no live turns captured — run after doing real work, from under the launch dir"
fi
if printf '%s' "$RT" | jassert "d['runtime']['budget']['tokens_total']>0"; then
  ok "real token budget surfaced (Claude Code never shows you this number)"
else
  warn "token total is 0 — the transcript had no usage yet; do more work and re-run"
fi
printf '%s' "$RT" | jassert "len(d['runtime']['models'])>0" \
  && ok "model routing surfaced" || warn "no model routing captured yet"
printf '%s' "$RT" | jassert "len(d['runtime']['tools'])>0" \
  && ok "your real tool usage surfaced" || warn "no tool usage captured yet"
echo "  budget / context readouts:"
avcs -C "$LIVE" budget  2>/dev/null | sed 's/^/    /'
avcs -C "$LIVE" context 2>/dev/null | sed 's/^/    /'
echo "  NOTE: if context shows >100%, your model's window isn't in the default table."
echo "        Set it in agent.json, e.g. \"budget\": {\"windows\": {\"opus\": 1000000}}."
echo "  statusline (drop this into ~/.claude/settings.json statusLine):"
avcs -C "$LIVE" statusline </dev/null 2>/dev/null | sed 's/^/    /'

# =====================================================================
# 2. EVAL GATE — freeze refuses unproven work; passing makes it 'verified'
# =====================================================================
hr; echo "[2] Eval/score gate (the trust layer)"
EV="$SANDBOX/evalgate"; mkdir -p "$EV"
echo 'def add(a, b): return a - b   # deliberately wrong' > "$EV/app.py"
avcs -C "$EV" init >/dev/null 2>&1
EVAL_CMD="$PY -c 'import app; assert app.add(2,2)==4'"
"$PY" - "$EV" "$EVAL_CMD" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])/"agent.json"
p.write_text(json.dumps({"goal":"implement a correct add(a,b)","models":[],
    "trace":None,"state":"fluid","eval":{"command":sys.argv[2]}}, indent=2))
PY
avcs -C "$EV" commit -m "add() v1 (buggy)" >/dev/null 2>&1

assert_json "freeze BLOCKS unproven work (EVAL_FAILED)" \
  "d['ok']==False and d['error']['code']=='EVAL_FAILED'" \
  "$(avcs -C "$EV" freeze --json 2>/dev/null)"

echo 'def add(a, b): return a + b   # fixed' > "$EV/app.py"
avcs -C "$EV" commit -m "add() v2 (fixed)" >/dev/null 2>&1
assert_json "eval passes after the fix" "d['passing']==True" \
  "$(avcs -C "$EV" eval --json 2>/dev/null)"
assert_json "freeze now succeeds and marks the recipe VERIFIED" \
  "d['ok'] and d['verified']==True" \
  "$(avcs -C "$EV" freeze -m 'freeze verified add()' --json 2>/dev/null)"

# =====================================================================
# 3. RECALL — the cache reflex; verified recipes rank first
# =====================================================================
hr; echo "[3] Recall (have I solved this before?)"
assert_json "recall returns the frozen recipe, flagged verified" \
  "len(d['hits'])>0 and d['hits'][0]['verified']==True" \
  "$(avcs -C "$EV" recall 'implement an add function' --json 2>/dev/null)"
MISS="$(avcs -C "$EV" recall 'render a 3d physics engine' --json 2>/dev/null)"
printf '%s' "$MISS" | jassert "len(d['hits'])==0" \
  && ok "recall miss is honest for unrelated goals" \
  || warn "unrelated goal produced a (weak) hit"

# =====================================================================
# 4. REPLAY — the frozen recipe is re-emitted deterministically
# =====================================================================
hr; echo "[4] Replay (re-run a crystallized recipe)"
assert_json "replay emits the deterministic recipe" \
  "d['ok'] and d['executed']==False and 'goal' in d" \
  "$(avcs -C "$EV" replay --json 2>/dev/null)"

# =====================================================================
# 5. CROSS-RUNTIME — the same pipeline, a qwen-code session
# =====================================================================
hr; echo "[5] Cross-runtime (qwen-code provider)"
QW="$SANDBOX/qwen"; mkdir -p "$QW"
mkdir -p "$SANDBOX/.qwen/tmp/proj"
cat > "$SANDBOX/.qwen/tmp/proj/checkpoint-default.json" <<'JSON'
[
 {"role":"user","parts":[{"text":"build a refunds queue"}]},
 {"role":"model","parts":[{"text":"on it"},{"functionCall":{"name":"write_file","args":{"path":"app.py"}}}],"usageMetadata":{"promptTokenCount":4200,"candidatesTokenCount":180}},
 {"role":"user","parts":[{"functionResponse":{"name":"write_file","response":{"ok":true}}}]}
]
JSON
echo 'x=1' > "$QW/app.py"
avcs -C "$QW" init --runtime >/dev/null 2>&1
"$PY" - "$QW" "$SANDBOX/.qwen" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])/"agent.json"
m=json.loads(p.read_text())
m["goal"]="build a refunds queue"
m["trace"]={"provider":"qwen-code","qwen_dir":sys.argv[2],"model":"qwen3-coder-plus"}
m["budget"]={"ceiling_usd":1.0}
p.write_text(json.dumps(m,indent=2))
PY
avcs -C "$QW" commit -m "from qwen session" >/dev/null 2>&1
assert_json "qwen-code session captured + normalized identically to Claude" \
  "d['trace_messages']==3" \
  "$(avcs -C "$QW" show --trace --json 2>/dev/null)"
assert_json "runtime frame reconstructed from a qwen checkpoint too" \
  "d['runtime']['budget']['tokens_total']==4380 and len(d['runtime']['tools'])>0" \
  "$(avcs -C "$QW" runtime --json 2>/dev/null)"

# =====================================================================
# 6. UNIT SUITE — fast confirmation nothing is broken
# =====================================================================
hr; echo "[6] Unit suite"
if PYTHONPATH="$SRC" "$PY" -m pytest "$HERE/../tests" -q -p no:cacheprovider >/tmp/avcs_selftest_pytest.log 2>&1; then
  ok "pytest green ($(grep -oE '[0-9]+ passed' /tmp/avcs_selftest_pytest.log | tail -1))"
else
  no "pytest failed — see /tmp/avcs_selftest_pytest.log"
fi

# =====================================================================
hr; echo "VERDICT:  PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
if [ "$FAIL" -eq 0 ]; then
  echo "  Core integration verified."
  [ "$WARN" -gt 0 ] && echo "  (WARNs are usually a thin live session — see section [1] notes.)"
  echo "  -> Safe to proceed with README / docs / video updates."
else
  echo "  Some checks FAILED — do NOT update docs yet; report the failing sections."
fi
echo "  Inspect the sandbox at: $SANDBOX"
echo "  Clean up with:          rm -rf $SANDBOX"
exit 0
