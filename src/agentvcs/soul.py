"""The Soul — cryptographic identity and provenance for an agent instance.

A traditional agent is fungible: copy its files and you have copied the agent,
reputation and all. agentvcs already versions *what an agent did* (code, goal,
models, trace); the Soul makes *who did it* unforgeable.

On ``agentvcs init`` an instance is born with an Ed25519 keypair — its **Soul**.
The 32-byte public key is the agent's identity (its ``soul_id``); the secret seed
never leaves ``.agentvcs/soul/`` (it is not part of the versioned tree, like an SSH
key). Every commit is then **signed**: the agent's signed history of reasoning
traces becomes a provenance chain nobody can forge without the secret seed, yet
anybody can verify holding only the public ``soul_id``.

This is the agentvcs realization of *Decentralized Society: Finding Web3's Soul*
(Weyl, Ohlhaver, Buterin): the instance is the Soul, and its signed traces are the
captured line of its life — enough to reconstruct it, evaluate it, and validate it
as a decentralized entity. Verified accomplishments are minted onto the Soul as
Soulbound Tokens (see ``sbt.py``).

Layout under ``.agentvcs/soul/``::

    seed.secret   hex 32-byte Ed25519 seed     (private — never versioned, never shared)
    soul.pub      hex 32-byte public key       (the soul_id; safe to publish)
    sbt.jsonl     ledger of Soulbound Tokens   (see sbt.py)
"""
from __future__ import annotations

import secrets
from pathlib import Path

from . import _ed25519 as ed
from .objects import canonical

SOUL_DIR = "soul"
SEED_FILE = "seed.secret"
PUB_FILE = "soul.pub"


def _soul_path(agentvcs_dir: Path) -> Path:
    return Path(agentvcs_dir) / SOUL_DIR


def birth(agentvcs_dir: Path) -> str:
    """Generate the agent's Soul (an Ed25519 keypair) on repository init. Idempotent:
    if a Soul already exists it is left untouched. Returns the public ``soul_id``."""
    sdir = _soul_path(agentvcs_dir)
    pub_path = sdir / PUB_FILE
    if pub_path.exists():
        return pub_path.read_text().strip()
    sdir.mkdir(parents=True, exist_ok=True)
    seed = secrets.token_bytes(32)
    pub = ed.publickey(seed)
    # 0o600-style intent: the seed is a private key. Best-effort chmod.
    seed_path = sdir / SEED_FILE
    seed_path.write_text(seed.hex() + "\n")
    try:
        seed_path.chmod(0o600)
    except OSError:
        pass
    soul_id = pub.hex()
    pub_path.write_text(soul_id + "\n")
    return soul_id


def soul_id(agentvcs_dir: Path) -> str | None:
    """The public identity of the agent whose repo this is (full 64-hex pubkey),
    or None if this repo predates the Soul layer."""
    pub_path = _soul_path(agentvcs_dir) / PUB_FILE
    return pub_path.read_text().strip() if pub_path.exists() else None


def _seed(agentvcs_dir: Path) -> bytes | None:
    seed_path = _soul_path(agentvcs_dir) / SEED_FILE
    if not seed_path.exists():
        return None
    return bytes.fromhex(seed_path.read_text().strip())


def short(soul_id_hex: str | None) -> str:
    """Human display form: ``soul:1a2b3c4d`` (the first 8 hex of the pubkey)."""
    if not soul_id_hex:
        return "anonymous"
    return "soul:" + soul_id_hex[:8]


# --------------------------------------------------------------- signing core
def sign_bytes(agentvcs_dir: Path, payload: bytes) -> str | None:
    """Sign arbitrary bytes with this repo's Soul. Returns a hex signature, or
    None if the repo has no Soul (older repos / signing intentionally disabled)."""
    seed = _seed(agentvcs_dir)
    if seed is None:
        return None
    return ed.sign(payload, seed).hex()


def verify_bytes(soul_id_hex: str, payload: bytes, signature_hex: str) -> bool:
    """Verify a signature against a public ``soul_id`` — the third-party check that
    needs no secret. Returns False on any malformed input rather than raising."""
    if not soul_id_hex or not signature_hex:
        return False
    try:
        pk = bytes.fromhex(soul_id_hex)
        sig = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    return ed.verify(sig, payload, pk)


# ----------------------------------------------------------- commit signatures
# A commit is signed over the canonical encoding of the commit object *without*
# its own signature field (the signature can't cover itself). The ``soul`` field
# IS covered, binding the identity into the signed content.
def commit_payload(commit: dict) -> bytes:
    unsigned = {k: v for k, v in commit.items() if k != "signature"}
    return canonical(unsigned)


def sign_commit(agentvcs_dir: Path, commit: dict) -> dict:
    """Return a copy of ``commit`` stamped with this repo's ``soul`` id and an
    Ed25519 ``signature`` over its canonical content. If the repo has no Soul the
    commit is returned unchanged (so legacy/un-souled repos still work)."""
    sid = soul_id(agentvcs_dir)
    if sid is None:
        return commit
    signed = {**commit, "soul": sid}
    sig = sign_bytes(agentvcs_dir, commit_payload(signed))
    if sig is not None:
        signed["signature"] = sig
    return signed


def verify_commit(commit: dict) -> bool:
    """True iff this commit carries a ``soul``+``signature`` that validates. An
    unsigned commit (no soul) returns False — use ``is_signed`` to distinguish
    'unsigned' from 'forged'."""
    sid = commit.get("soul")
    sig = commit.get("signature")
    if not sid or not sig:
        return False
    return verify_bytes(sid, commit_payload(commit), sig)


def is_signed(commit: dict) -> bool:
    return bool(commit.get("soul") and commit.get("signature"))
