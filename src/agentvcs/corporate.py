"""The corporate dimension — an optional legal/governance layer for autonomous agents.

agentvcs already versions *what an agent did* (code, goal, models, trace) and, with
the opt-in Soul, *who did it* (unforgeable Ed25519 provenance). The corporate layer
adds *under what authority* — the digital **statute** (``mandate``) that bounds an
autonomous agent operating as a legal entity.

This is built for the wave of legislation giving software agents legal personhood —
e.g. Argentina's *Sociedades Automatizadas* draft, where an agent may run a company
within declared limits, with named human representatives, and must keep an auditable
record of every material decision. agentvcs is the technical "libro de actas": each
signed commit is an *acta* (board minute); ``agentvcs audit`` produces the signed
Libro de Actas Digital that proves the agent operated within its mandate.

Like the Soul, it is **opt-in** and off by default. ``agentvcs init --corporate``
writes a ``corporate`` block into ``agent.json`` (so the statute is itself versioned
and signed by the tree hash — it cannot be altered retroactively without breaking
provenance) and generates ``LEGAL.md`` (the human-readable statute). Everything
downstream degrades gracefully when no ``corporate`` block exists.

Design, consistent with the rest of agentvcs:

* The **statute** lives in ``agent.json`` → it is part of the *code* dimension, so
  every commit captures the mandate that was in force, signed by the Soul.
* **Approvals** and the **audit** live in a side-table (``.agentvcs/corporate/``),
  exactly like eval results: a measurement *about* commits, never part of their
  content identity (so re-auditing never rewrites history).
* Enforcement is a **policy gate**, not a fantasy of seeing real-world money: it
  flags commits whose inference cost exceeded the mandate's ceiling, and commits
  whose trace contains tool calls matching the statute's *reserved matters*
  (``requires_human_for``) that lack a valid human authorization.
"""
from __future__ import annotations

import copy
import json
import time

from .objects import canonical

CORP_DIR = "corporate"
APPROVALS_FILE = "approvals.jsonl"
STATUTE_FILE = "LEGAL.md"

# Built-in jurisdiction profiles. `init --corporate` (no value) uses AR_SAS_Auto.
# A profile is only a starting statute — edit agent.json's `corporate` block freely;
# the change is versioned and signed like any other.
PROFILES: dict[str, dict] = {
    "AR_SAS_Auto": {
        "entity_type": "SAS Automatizada",
        "jurisdiction": "AR",
        "legal_name": "",
        "registry_id": "",  # CUIT / IGJ inscription, once registered
        "liability_limits": {
            # ceiling on inference spend per acta (uses the runtime frame's cost_usd)
            "max_inference_usd": None,
            # reserved matters: tool calls matching any of these require a human
            # representative's signed authorization to be in-mandate.
            "requires_human_for": [],
        },
        # Ed25519 public keys of the human legal representatives (the only parties
        # whose signed approval can clear a reserved-matter acta).
        "legal_representatives": [],
    },
}


# --------------------------------------------------------------- manifest access
def config(manifest: dict) -> dict | None:
    """Return the ``corporate`` block of a manifest, or None if this is not a
    corporate repo (the layer is opt-in)."""
    corp = (manifest or {}).get("corporate")
    return corp if isinstance(corp, dict) else None


def is_corporate(manifest: dict) -> bool:
    return config(manifest) is not None


def default_block(profile: str | None = None) -> dict:
    """A fresh ``corporate`` block from a built-in profile (deep-copied so callers
    can mutate it). Unknown profile names fall back to AR_SAS_Auto."""
    base = PROFILES.get(profile or "AR_SAS_Auto") or PROFILES["AR_SAS_Auto"]
    block = copy.deepcopy(base)
    if profile and profile not in PROFILES:
        # treat an unknown profile name as a jurisdiction hint
        block["jurisdiction"] = profile
    return block


def representatives(corp: dict) -> list[dict]:
    """Normalize ``legal_representatives`` (entries may be bare hex pubkeys or
    ``{name, soul}`` dicts) to a list of ``{name, soul}``."""
    out = []
    for r in (corp or {}).get("legal_representatives", []) or []:
        if isinstance(r, str):
            out.append({"name": "", "soul": r.strip()})
        elif isinstance(r, dict):
            out.append({"name": r.get("name", ""),
                        "soul": (r.get("soul") or r.get("pubkey") or "").strip()})
    return out


def _limits(corp: dict) -> dict:
    lim = (corp or {}).get("liability_limits")
    return lim if isinstance(lim, dict) else {}


def short_rep(approval: dict) -> str:
    """Human display of who authorized an acta: name if present, else short pubkey."""
    name = approval.get("name")
    rep = approval.get("representative") or ""
    if name:
        return name
    return ("rep:" + rep[:8]) if rep else "(anonymous)"


# --------------------------------------------------------------- reading commits
def manifest_at(repo, commit: dict) -> dict:
    """The ``agent.json`` as it existed at this commit (read from its tree), so an
    acta is judged against the statute that was actually in force then."""
    try:
        tree = repo.objects.read_obj(commit["tree"])["entries"]
        blob = tree.get("agent.json")
        if not blob:
            return {}
        return json.loads(repo.objects.read_blob(blob))
    except Exception:
        return {}


def _messages_at(repo, commit: dict) -> list:
    if not commit.get("trace"):
        return []
    try:
        return repo.objects.read_obj(commit["trace"]).get("messages", [])
    except Exception:
        return []


def _inference_usd(repo, commit: dict):
    """The inference cost captured in the commit's runtime frame (runtime mode),
    or None when no frame was recorded for this commit."""
    rid = commit.get("runtime")
    if not rid:
        return None
    try:
        return repo.objects.read_obj(rid)["budget"]["cost_usd"]
    except Exception:
        return None


def flagged_actions(messages: list, patterns: list) -> list:
    """Tool calls in the trace that match a reserved-matter pattern — the actions
    the statute says a human must authorize. Heuristic by design: matches a pattern
    as a case-insensitive substring of the tool name or its JSON input."""
    pats = [p.lower() for p in (patterns or []) if isinstance(p, str) and p.strip()]
    if not pats:
        return []
    out = []
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name") or "?"
            blob = (name + " " + json.dumps(b.get("input", {}), ensure_ascii=False)).lower()
            for p in pats:
                if p in blob:
                    out.append({"action": name, "pattern": p, "input": b.get("input", {})})
                    break
    return out


# ------------------------------------------------------------------- approvals
# An approval is a human legal representative authorizing a reserved-matter acta.
# It is cryptographic: the representative signs the canonical payload with their own
# Ed25519 key (their personal Soul), exactly as a commit is signed. An unsigned
# attestation is recorded for the record but does NOT clear a breach.
def approval_payload(approval: dict) -> bytes:
    unsigned = {k: v for k, v in approval.items() if k != "signature"}
    return canonical(unsigned)


def record_approval(repo, commit_oid: str, *, representative: str = "", name: str = "",
                    note: str = "", seed_hex: str | None = None,
                    timestamp: int | None = None) -> dict:
    """Record (and, given the representative's seed, cryptographically sign) a human
    authorization for a commit. Appended to ``.agentvcs/corporate/approvals.jsonl``."""
    approval = {
        "type": "approval",
        "commit": commit_oid,
        "representative": representative.strip(),
        "name": name,
        "note": note,
        "timestamp": timestamp if timestamp is not None else int(time.time()),
    }
    if seed_hex:
        from . import _ed25519 as ed
        seed = bytes.fromhex(seed_hex.strip())
        approval["representative"] = ed.publickey(seed).hex()  # derive, authoritative
        approval["signature"] = ed.sign(approval_payload(approval), seed).hex()
    d = repo.dir / CORP_DIR
    d.mkdir(parents=True, exist_ok=True)
    with (d / APPROVALS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(approval, ensure_ascii=False) + "\n")
    return approval


def read_approvals(repo, commit_oid: str | None = None) -> list[dict]:
    path = repo.dir / CORP_DIR / APPROVALS_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            a = json.loads(line)
        except json.JSONDecodeError:
            continue
        if commit_oid is None or a.get("commit") == commit_oid:
            out.append(a)
    return out


def approval_is_valid(approval: dict, corp: dict) -> bool:
    """True iff the approval is signed by a listed legal representative (when the
    statute names any) and the signature validates. This is what *clears* a
    reserved-matter acta — an unsigned attestation never does."""
    rep = approval.get("representative")
    sig = approval.get("signature")
    if not rep or not sig:
        return False
    from . import soul as _soul
    if not _soul.verify_bytes(rep, approval_payload(approval), sig):
        return False
    reps = {r["soul"] for r in representatives(corp) if r.get("soul")}
    return rep in reps if reps else True


# ------------------------------------------------------------------- the gate
def check_commit(repo, oid: str, commit: dict, corp: dict) -> dict:
    """Check one commit (acta) against the mandate. Returns its compliance record:
    signature provenance, inference spend vs ceiling, reserved-matter actions and
    whether each is covered by a valid human authorization, and the breaches."""
    from . import soul as _soul

    if _soul.is_signed(commit):
        signature = "valid" if _soul.verify_commit(commit) else "FORGED"
    else:
        signature = "unsigned"

    limits = _limits(corp)
    ceiling = limits.get("max_inference_usd")
    spent = _inference_usd(repo, commit)

    messages = _messages_at(repo, commit)
    flagged = flagged_actions(messages, limits.get("requires_human_for", []))

    approvals = read_approvals(repo, oid)
    cleared = any(approval_is_valid(a, corp) for a in approvals)

    breaches = []
    if signature == "FORGED":
        breaches.append({"kind": "forged_signature"})
    if ceiling is not None and spent is not None and spent > ceiling:
        breaches.append({"kind": "over_inference_budget",
                         "spent_usd": spent, "limit_usd": ceiling})
    if flagged and not cleared:
        for f in flagged:
            breaches.append({"kind": "unauthorized_action",
                             "action": f["action"], "pattern": f["pattern"]})

    return {
        "commit": oid,
        "message": commit.get("message", ""),
        "timestamp": commit.get("timestamp", 0),
        "soul": commit.get("soul"),
        "signature": signature,
        "inference_usd": spent,
        "inference_ceiling_usd": ceiling,
        "reserved_actions": flagged,
        "approvals": [{"representative": a.get("representative"), "name": a.get("name"),
                       "valid": approval_is_valid(a, corp), "note": a.get("note", "")}
                      for a in approvals],
        "authorized": cleared,
        "within_mandate": not breaches,
        "breaches": breaches,
    }


def audit(repo) -> dict:
    """The Libro de Actas Digital — a signed, verifiable report of every acta and
    its compliance with the mandate in force at the time. The report itself is
    signed by the entity's Soul, so a regulator (UIF/AFIP/IGJ) can verify it was
    produced by this agent and not tampered with afterward."""
    from . import soul as _soul

    head_manifest = repo.read_manifest()
    head_corp = config(head_manifest)
    history = repo.log()  # newest first

    actas = []
    for oid, commit in history:
        # judge each acta against the statute that was in force at that commit
        corp_then = config(manifest_at(repo, commit)) or head_corp or {}
        actas.append(check_commit(repo, oid, commit, corp_then))

    summary = {
        "actas": len(actas),
        "within_mandate": sum(1 for a in actas if a["within_mandate"]),
        "breached": sum(1 for a in actas if a["breaches"]),
        "signed": sum(1 for a in actas if a["signature"] == "valid"),
        "unsigned": sum(1 for a in actas if a["signature"] == "unsigned"),
        "forged": sum(1 for a in actas if a["signature"] == "FORGED"),
        "compliant": all(a["within_mandate"] for a in actas),
    }

    entity = {}
    if head_corp:
        entity = {
            "entity_type": head_corp.get("entity_type"),
            "jurisdiction": head_corp.get("jurisdiction"),
            "legal_name": head_corp.get("legal_name"),
            "registry_id": head_corp.get("registry_id"),
            "representatives": representatives(head_corp),
        }

    report = {
        "corporate": head_corp is not None,
        "entity": entity,
        "soul": repo.soul_id(),
        "summary": summary,
        "actas": actas,
    }
    # sign the report body so the Libro de Actas is itself unforgeable provenance
    report["report_signature"] = _soul.sign_bytes(repo.dir, canonical(actas))
    return report


# --------------------------------------------------------------- statute / docs
def statute_markdown(corp: dict, soul_id: str | None = None) -> str:
    """Render LEGAL.md — the human-readable digital statute, generated from the
    machine-binding ``corporate`` block in agent.json."""
    limits = _limits(corp)
    reps = representatives(corp)
    rep_lines = "\n".join(
        f"- {r['name'] or '(unnamed representative)'} — `{r['soul'] or 'PENDING — add Ed25519 pubkey'}`"
        for r in reps) or "- _(none declared yet — add at least one before operating)_"
    reserved = limits.get("requires_human_for") or []
    reserved_lines = "\n".join(f"- `{p}`" for p in reserved) or "- _(none — declare reserved matters)_"
    ceiling = limits.get("max_inference_usd")
    ceiling_str = f"USD {ceiling}" if ceiling is not None else "_(no ceiling declared)_"
    return f"""# Estatuto Digital — Digital Statute

> This file is the human-readable statute of an **autonomous legal entity**.
> The machine-binding source of truth is the `corporate` block in `agent.json`,
> which is versioned and Ed25519-signed by the entity's Soul on every commit.
> Do not hand-edit this file expecting enforcement — edit `agent.json`.

## Entity
- **Type:** {corp.get('entity_type') or '(unspecified)'}
- **Jurisdiction:** {corp.get('jurisdiction') or '(unspecified)'}
- **Legal name:** {corp.get('legal_name') or '(pending registration)'}
- **Registry id (CUIT/IGJ):** {corp.get('registry_id') or '(pending registration)'}
- **Soul (entity public key):** `{soul_id or '(no Soul — re-init with --corporate)'}`

## Legal representatives
The only parties whose **signed** authorization can clear a reserved-matter acta:

{rep_lines}

## Liability limits (mandate)
- **Max inference spend per acta:** {ceiling_str}
- **Reserved matters (require a human representative's signed authorization):**

{reserved_lines}

## How this is enforced (the libro de actas técnico)
1. Every decision the agent commits is an **acta** — signed by the entity's Soul.
2. `agentvcs audit` walks every acta and checks it against the mandate in force at
   that commit: signature provenance, inference spend vs ceiling, and whether any
   reserved-matter tool call lacks a valid human authorization.
3. A human representative authorizes a reserved acta with
   `agentvcs approve <commit> --seed <their-ed25519-seed>` — a signed board
   resolution recorded in `.agentvcs/corporate/approvals.jsonl`.
4. `agentvcs audit --json` emits the **Libro de Actas Digital**, itself signed by
   the entity's Soul — the artifact to present to a regulator (UIF/AFIP/IGJ) or a
   court as cryptographic proof the agent operated within its statute.
"""


AGENTS_MD_CORPORATE = """
## You operate as an autonomous legal entity (corporate layer — enabled for this repo)
This repo was initialized with `--corporate`, so your actions are bound by a digital
**statute**: the `corporate` block in `agent.json` (and the human-readable `LEGAL.md`).
You operate within a **mandate** — spending limits and *reserved matters* that require
a human legal representative's authorization.
- Treat each `agentvcs commit` as an **acta** (board minute): it is signed by the
  entity's Soul and becomes immutable legal evidence of what you decided and why.
- Before performing a *reserved matter* (see `liability_limits.requires_human_for`),
  a human representative must record a signed authorization with
  `agentvcs approve <commit> --seed <their-seed>`. Without it the acta is a breach.
- `agentvcs audit --json` is the **Libro de Actas Digital** — run it to see whether
  every acta is within mandate. Stay compliant: an out-of-mandate acta is a liability.
"""
