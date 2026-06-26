"""Soulbound Tokens — non-transferable proof of verified machine experience.

In *Decentralized Society* (Weyl, Ohlhaver, Buterin), a Soul accrues **Soulbound
Tokens** (SBTs): non-transferable credentials attesting to what it has done and
who vouches for it. Here the Soul is an agent instance, and an SBT attests to a
*verified* accomplishment: a commit that passed its eval gate and was crystallized
into a deterministic, replayable recipe.

The flow: ``agentvcs freeze`` only crystallizes a commit that passed its eval (the
trust gate in ``crystallize.py`` / ``eval.py``). On a *verified* freeze an SBT is
minted onto the instance's Soul — a signed record of "this Soul solved <goal> with
score <s>, proven by commit <oid> whose trace is signed provenance."

What an SBT does and does NOT prove:
  * **Provenance (proven).** The SBT references a **signed commit** — anyone can
    re-verify that commit's Ed25519 signature against the Soul's public id with no
    secret (see soul.py). And the SBT itself is signed: copy an agent's files and you
    copy its SBT *ledger* but not its out-of-repo seed, so you cannot mint new SBTs in
    its name. Provenance does not transfer with the bytes.
  * **Reputation (only as strong as the issuer).** By default the issuer is the Soul
    *itself* (``self_issued: True``), anchored to a reproducible eval — but that eval
    is declared by the agent's own author, so a self-issued SBT is a *self-graded*
    claim, not Sybil-resistant reputation (Souls are free to mint). Trustworthy
    reputation needs an **external issuer** — an orchestrator, eval oracle, or
    AgentHub/DAO — which signs with ``issuer_seed`` and sets ``self_issued: False``.
    ``verify_sbt`` checks the signature; the *self vs external* distinction is what
    tells a consumer how much to trust it.

SBTs are **soulbound**: append-only, never re-pointed to another Soul without that
Soul's signature. They live in ``.agentvcs/soul/sbt.jsonl`` (one JSON per line); the
guarantee is verification-side (a tampered/forged token fails ``verify_sbt``), not
storage-side.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import soul
from .objects import canonical

SBT_LEDGER = "sbt.jsonl"

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "to", "of", "and", "or", "for", "in", "on", "with",
         "describe", "high", "level", "objective", "this", "agent", "fleet",
         "is", "pursuing", "that", "it", "as", "by", "at", "from", "into"}


def skill_tags(goal_text: str) -> list[str]:
    """Distill a goal string into a small set of normalized skill tags — the unit
    of competence an SBT certifies and ``plural.py`` measures diversity over."""
    words = [w for w in _WORD.findall((goal_text or "").lower())
             if w not in _STOP and len(w) > 2]
    seen, tags = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            tags.append(w)
    return tags[:8]


def _ledger_path(repo) -> Path:
    return repo.dir / soul.SOUL_DIR / SBT_LEDGER


def issue_sbt(repo, commit_oid: str, eval_result: dict | None, *,
              goal_text: str = "", issuer_seed: bytes | None = None,
              timestamp: int | None = None) -> dict | None:
    """Mint a Soulbound Token onto this repo's Soul for a verified commit. Returns
    the SBT dict, or None if the repo has no Soul. Called by ``crystallize`` on a
    verified freeze; can also be driven by an external evolution engine (SkillOpt).

    ``issuer_seed`` lets an *external* oracle sign the credential; omit it for the
    default self-attested issuance (anchored to the independently-verifiable signed
    commit + reproducible eval)."""
    sid = repo.soul_id()
    if sid is None:
        return None

    score = eval_result.get("score") if eval_result else None
    sbt = {
        "type": "sbt",
        "soul": sid,                          # the bearer (this instance)
        "skill": skill_tags(goal_text),
        "goal": goal_text,
        "commit": commit_oid,                 # the signed, verifiable provenance
        "score": score,
        "eval": ({"command": eval_result.get("command"),
                  "passed": eval_result.get("passed"),
                  "total": eval_result.get("total")} if eval_result else None),
        "issued_at": timestamp if timestamp is not None else int(time.time()),
    }

    # sign the credential: external issuer if a seed is given, else the Soul itself
    if issuer_seed is not None:
        from . import _ed25519 as ed
        sbt["issuer"] = ed.publickey(issuer_seed).hex()
        sbt["self_issued"] = False
        sbt["signature"] = ed.sign(_sbt_payload(sbt), issuer_seed).hex()
    else:
        sbt["issuer"] = sid
        sbt["self_issued"] = True
        sbt["signature"] = soul.sign_bytes(repo.dir, _sbt_payload(sbt))

    ledger = _ledger_path(repo)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sbt, ensure_ascii=False) + "\n")
    return sbt


def _sbt_payload(sbt: dict) -> bytes:
    """Canonical bytes the signature covers (everything but the signature)."""
    return canonical({k: v for k, v in sbt.items() if k != "signature"})


def read_sbts(repo) -> list[dict]:
    """All Soulbound Tokens minted onto this repo's Soul, oldest first."""
    ledger = _ledger_path(repo)
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def verify_sbt(sbt: dict) -> bool:
    """True iff the SBT's issuer signature validates. Needs only public keys."""
    issuer = sbt.get("issuer")
    sig = sbt.get("signature")
    if not issuer or not sig:
        return False
    return soul.verify_bytes(issuer, _sbt_payload(sbt), sig)


def skill_profile(repo) -> dict:
    """Aggregate this Soul's SBTs into a skill→weight vector (its résumé). The
    input ``plural.py`` consumes to pick maximally-diverse fleets."""
    profile: dict[str, float] = {}
    for sbt in read_sbts(repo):
        w = sbt.get("score") if isinstance(sbt.get("score"), (int, float)) else 1.0
        for tag in sbt.get("skill", []):
            profile[tag] = profile.get(tag, 0.0) + float(w)
    return profile
