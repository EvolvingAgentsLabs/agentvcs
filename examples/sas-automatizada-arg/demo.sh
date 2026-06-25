#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# agentvcs as the "libro de actas técnico" for an Argentine SAS Automatizada
# (autonomous company) — the 90-second, fully offline demo.
#
# Story: an autonomous agent runs a refunds/payments company. Its digital statute
# says transfers are a RESERVED MATTER — a human legal representative must
# authorize them. The agent:
#   1. does a benign acta (KYC check)        -> within mandate
#   2. wires money to a supplier             -> OUT OF MANDATE (no authorization)
#   3. the representative signs a board resolution clearing that acta
#   4. the audit (Libro de Actas Digital) is now COMPLIANT and Soul-signed —
#      the artifact you'd hand a regulator (UIF/AFIP/IGJ) or a court.
#
#   bash examples/sas-automatizada-arg/demo.sh
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for p in python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys;exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
    PYBIN="$p"; break
  fi
done
avcs() { PYTHONPATH="$REPO/src" "$PYBIN" -m agentvcs.cli "$@"; }
pyx()  { PYTHONPATH="$REPO/src" "$PYBIN" "$@"; }

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
cd "$W"
say()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
strip() { sed 's/\x1b\[[0-9;]*m//g'; }

# The representative's Ed25519 seed (their personal "Soul"). In real life this
# never leaves the human's wallet; here it's a fixed demo seed.
REP_SEED="0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a"
REP_PUB="$(pyx -c "from agentvcs import _ed25519 as ed; print(ed.publickey(bytes.fromhex('$REP_SEED')).hex())")"

say "agentvcs init --corporate   (born as a SAS Automatizada: signed actas + statute)"
avcs init --corporate | strip | sed 's/^/  /'

say "the generated statute (LEGAL.md) and the machine-binding block (agent.json):"
echo "  --- LEGAL.md (excerpt) ---"
sed -n '1,12p' LEGAL.md | sed 's/^/  /'

# --- set the mandate: transfers are a reserved matter; Ana is the representative
pyx - "$REP_PUB" <<'PY'
import json, sys, pathlib
pub = sys.argv[1]
m = json.loads(pathlib.Path("agent.json").read_text())
m["goal"] = "Operate the customer refunds & supplier-payments desk."
m["corporate"]["legal_name"] = "Refunds Autónoma SAS"
m["corporate"]["liability_limits"]["max_inference_usd"] = 2.0
m["corporate"]["liability_limits"]["requires_human_for"] = ["transfer", "wire", "pay_supplier"]
m["corporate"]["legal_representatives"] = [{"name": "Ana Gómez", "soul": pub}]
pathlib.Path("agent.json").write_text(json.dumps(m, indent=2))
PY
say "mandate set: reserved matters = [transfer, wire, pay_supplier]; representative = Ana Gómez"

write_acta() {  # $1 = tool name, $2 = json input — heredoc avoids nested-quote pitfalls
  mkdir -p traces
  pyx - "$1" "$2" > traces/run.jsonl <<'PY'
import json, sys
print(json.dumps({"role": "assistant", "content": [
    {"type": "tool_use", "name": sys.argv[1], "input": json.loads(sys.argv[2])}]}))
PY
}

# --- Acta 1: a benign KYC check (not a reserved matter) -----------------------
write_acta verify_kyc '{"supplier":"ACME","result":"pass"}'
say "Acta 1 — verify KYC of supplier ACME (routine):"
avcs commit -m "acta: KYC check for ACME" | strip | sed 's/^/  /'

# --- Acta 2: wire money to the supplier (RESERVED, no authorization yet) -------
write_acta wire_transfer '{"to":"ACME","amount_usd":5000,"ref":"INV-42"}'
say "Acta 2 — wire USD 5000 to ACME (a RESERVED matter):"
TRANSFER_COMMIT="$(avcs commit -m "acta: pay supplier ACME 5000" --json | pyx -c "import json,sys; print(json.load(sys.stdin)['commit'])")"
echo "  committed acta $TRANSFER_COMMIT"

say "agentvcs audit   (Libro de Actas Digital — expect OUT OF MANDATE)"
avcs audit | strip | sed 's/^/  /'

# --- the representative authorizes the transfer (signed board resolution) ------
say "Ana signs a board resolution authorizing the transfer:"
avcs approve "$TRANSFER_COMMIT" --seed "$REP_SEED" --name "Ana Gómez" \
  --note "Acta de directorio: pago a proveedor ACME aprobado" | strip | sed 's/^/  /'

say "agentvcs audit   (re-run — expect COMPLIANT, report signed by the entity's Soul)"
avcs audit | strip | sed 's/^/  /'

say "agentvcs verify --all   (every acta is cryptographically the entity's own)"
avcs verify --all | strip | sed 's/^/  /'

say "the Libro de Actas Digital as JSON (what a regulator/court receives):"
avcs audit --json | pyx -m json.tool | sed -n '1,30p' | sed 's/^/  /'

say "done — the autonomous company stayed within its statute, with cryptographic proof."
