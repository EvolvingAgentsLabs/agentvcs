#!/usr/bin/env bash
# LK0 — agentvcs versions the harness of lora-kernel's edge/Mac stack and asks Claude Code
# to merge two lines of it. No local model is loaded or run: lora-kernel's numbers come from
# its committed results files (imported, not live).
#
#   examples/lora-kernel/demo.sh [--dry-run] [--lk PATH] [--work DIR]
#
#   --dry-run   stop before `merge resolve` runs Claude Code (prints the exact command instead)
#   --lk PATH   lora-kernel checkout, read only (default: $LK or ~/evolvingagents/lora-kernel)
#   --work DIR  agentvcs project directory to create (default: examples/lora-kernel/workdir)
#
# Environment: PYTHON (an interpreter with the agentvcs SDK; default: the dev venv if it exists),
# CLAUDE (path to `claude`; default: on PATH), RESOLVE_MODEL, RESOLVE_BUDGET_USD.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
dry=0
lk="${LK:-$HOME/evolvingagents/lora-kernel}"
work="$here/workdir"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --lk) lk="$2"; shift ;;
    --work) work="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$repo/crates/agentvcs-py/.venv/bin/python" ]; then PYTHON="$repo/crates/agentvcs-py/.venv/bin/python"; else PYTHON=python3; fi
fi
export PYTHON LK_EXAMPLE="$here"
avcs() { "$PYTHON" -m agentvcs -C "$work" --json "$@"; }
jq_() { "$PYTHON" -c "import json,sys; d=json.load(sys.stdin); $1"; }

echo "== LK0: lora-kernel edge/Mac harness under agentvcs"
echo "   lora-kernel (read only): $lk"
echo "   store: $work"
rm -rf "$work"; mkdir -p "$work"

echo; echo "== 1. import: the fork-point manifest, every value with its source"
"$PYTHON" "$here/import_lk.py" --lk "$lk" -o "$work/fork.json" --facts "$work/facts.json"
avcs init >/dev/null
avcs snapshot "$work/fork.json" | jq_ 'print("   manifest", d["manifest_id"]); [print("   ", k.ljust(22), v[:24] + "…") for k, v in sorted(d["dimensions"].items())]'

echo; echo "== 2. history: nine measured changes as patches (imported measurements, gated from results files)"
"$PYTHON" "$here/history.py" --lk "$lk" --store "$work" >"$work/history.out"
grep '^\[history\]' "$work/history.out" | sed 's/^/   /'
read -r base ours theirs < <("$PYTHON" -c "import json; h=json.load(open('$work/history.json')); print(h['base'], h['ours'], h['theirs'])")
for run in lk-trunk lk-domain lk-speed; do
  avcs verify "$run" | jq_ 'print("   verify '"$run"':", "valid" if d["valid"] else "INVALID", d["entries"], "entries")'
done

echo; echo "== 3. branches: domain (ours) and speed (theirs) diverge from the fork"
avcs diff "$base" "$ours" | jq_ 'print("   domain:", [c["dimension"] for c in d["changes"]])'
avcs diff "$base" "$theirs" | jq_ 'print("   speed: ", [c["dimension"] for c in d["changes"]])'

metrics=(--metric mlx.speedup_general --metric mlx.speedup_lora_domain --metric spec.alpha_domain --metric mlx.speedup_projected_k1_domain)
echo; echo "== 4. merge prepare: what merges mechanically, what needs judgment, and the evidence"
avcs merge prepare --base "$base" --ours "$ours" --theirs "$theirs" --ours-run lk-domain --theirs-run lk-speed "${metrics[@]}" \
  >"$work/prepare.json"
jq_ '
print("   merge_id", d["merge_id"])
print("   auto:", ", ".join(a["dimension"] + "=" + a["resolution"] for a in d["auto"] if a["resolution"] != "same"))
for c in d["conflicts"]:
    print("   CONFLICT", c["dimension"], c["type"])
    for side in ("ours", "theirs"):
        print("     ", side.ljust(6), [f["path"] + ": " + json.dumps(f.get("from")) + " -> " + json.dumps(f.get("to")) for f in c["diff_" + side]["details"]["fields"]])
        for e in c["evidence"][side]:
            b = {k: round(v, 3) for k, v in e["blame"].items() if v is not None}
            print("        patch", e["patch_id"][:15] + "…", e["author"]["id"], "gate", e["gate"]["passed"], "blame", b)
' <"$work/prepare.json"

resolve=(merge resolve --base "$base" --ours "$ours" --theirs "$theirs" --ours-run lk-domain --theirs-run lk-speed
         "${metrics[@]}" --suite "$here/suite.yaml")
[ -n "${CLAUDE:-}" ] && resolve+=(--claude "$CLAUDE")
[ -n "${RESOLVE_MODEL:-}" ] && resolve+=(--model "$RESOLVE_MODEL")
[ -n "${RESOLVE_BUDGET_USD:-}" ] && resolve+=(--budget-usd "$RESOLVE_BUDGET_USD")

echo; echo "== 5. merge resolve: Claude Code resolves, agentvcs audits, gates (suite.yaml, static) and records"
have_claude=1
if [ -n "${CLAUDE:-}" ]; then [ -x "$CLAUDE" ] || have_claude=0; else command -v claude >/dev/null || have_claude=0; fi
if [ "$dry" = 1 ] || [ "$have_claude" = 0 ]; then
  [ "$have_claude" = 0 ] && echo "   NOTE: no \`claude\` found (set CLAUDE=/path/to/claude); not resolving."
  [ "$dry" = 1 ] && echo "   NOTE: --dry-run; not invoking Claude Code."
  avcs "${resolve[@]}" --dry-run | jq_ 'print("   workspace written:", d["workspace"]); print("   conflicts:", d["conflicts"]); print("   claude would run:", " ".join(d["command"][:3]), "…", "(" + str(len(d["command"])) + " args)")'
  echo "   to resolve for real:"
  printf '     cd %q && PYTHON=%q LK_EXAMPLE=%q %q -m agentvcs -C %q --json' "$repo" "$PYTHON" "$here" "$PYTHON" "$work"
  printf ' %q' "${resolve[@]}"; echo
  echo; echo "== 6. blame (imported history)"
else
  set +e
  avcs "${resolve[@]}" >"$work/resolve.json"; rc=$?
  set -e
  jq_ '
if not d.get("ok"): print("   resolve failed:", d["error"]); sys.exit(0)
print("   merged", d["merged"], "record", d["record"])
g = d.get("gate") or {}
print("   gate passed:", g.get("passed"), {k: v for k, v in (g.get("metrics") or {}).items()})
r = d.get("resolver") or {}
print("   resolver:", r.get("agent"), r.get("version"), r.get("model"), "cost $", r.get("cost_usd"), "turns", r.get("turns"))
' <"$work/resolve.json"
  echo "   (exit $rc; full output in $work/resolve.json)"
  echo; echo "== 6. verify + blame"
  "$PYTHON" - "$work" <<'PY' || true
import json, sys, agentvcs
work = sys.argv[1]
d = json.load(open(work + "/resolve.json"))
if d.get("ok"):
    rec = json.loads(agentvcs.open_store(work, False).get_object(d["record"]))
    res = rec["resolution"]
    print("   decision:", json.dumps(res["resolutions"]))
    print("   rationale:", res["rationale"])
PY
fi
for run in lk-trunk lk-domain lk-speed; do avcs verify "$run" | jq_ 'print("   verify '"$run"':", d["valid"])'; done
blame() { avcs blame "$1" --metric "$2" | jq_ '
segs = " | ".join("steps %d-%d mean %s" % (s["from_step"], s["to_step"], s["mean"]) for s in d["segments"] if s["n"])
att = "; ".join("delta %+.3f -> %s" % (a["delta"], [p[:15] + "…" for p in a["patches"]]) for a in d["attributions"] if a["delta"] is not None)
print("   blame '"$1 $2"':", segs, "||", att)'; }
blame lk-trunk library.delivered_precision
blame lk-trunk mac.spec_speedup_base_general
blame lk-domain spec.alpha_domain
blame lk-speed mlx.speedup_general
