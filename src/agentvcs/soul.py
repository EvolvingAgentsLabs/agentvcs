"""The Soul — cryptographic identity and provenance for an agent instance.

A traditional agent is fungible: copy its files and you have copied the agent,
reputation and all. agentvcs already versions *what an agent did* (code, goal,
models, trace); the Soul makes *who did it* unforgeable.

On ``agentvcs init`` an instance is born with an Ed25519 keypair — its **Soul**.
The 32-byte public key is the agent's identity (its ``soul_id``); it is written to
``.agentvcs/soul/soul.pub`` (safe to publish). The **secret seed is stored outside
the repository** — under ``$AGENTVCS_SOUL_HOME`` / ``$XDG_CONFIG_HOME/agentvcs/souls``
/ ``~/.config/agentvcs/souls/<soul_id>/seed.secret`` — exactly like an SSH key in
``~/.ssh``. So copying a repo's files carries only the public id and the SBT ledger,
**never the seed**: an impostor cannot sign in the Soul's name. Every commit is then
**signed**, so the agent's signed history becomes provenance nobody can forge without
the seed, yet anybody can verify holding only the public ``soul_id``.

This implements the **provenance and diversity primitives** of *Decentralized
Society: Finding Web3's Soul* (Weyl, Ohlhaver, Buterin): the instance is the Soul,
and its signed traces are the captured line of its life. Note the scope: signing
proves *provenance* ("these bytes were authored by Soul X"), not Sybil-resistant
*reputation* — anyone can mint Souls for free, so trustworthy reputation depends on
**external issuers** (see ``sbt.py`` ``self_issued`` vs an oracle-signed SBT).

Layout::

    .agentvcs/soul/soul.pub   hex 32-byte public key (the soul_id; safe to publish)
    .agentvcs/soul/sbt.jsonl  ledger of Soulbound Tokens (public; see sbt.py)
    <soul-home>/<soul_id>/seed.secret   hex 32-byte Ed25519 seed (private; OUTSIDE the repo)
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from . import _ed25519 as ed
from .objects import canonical

SOUL_DIR = "soul"
SEED_FILE = "seed.secret"
PUB_FILE = "soul.pub"
SOUL_HOME_ENV = "AGENTVCS_SOUL_HOME"


def _soul_path(agentvcs_dir: Path) -> Path:
    return Path(agentvcs_dir) / SOUL_DIR


def _soul_home() -> Path:
    """Base directory for secret seeds — kept OUTSIDE any repo so a copy of the
    repo's files cannot carry the private key. Honors ``AGENTVCS_SOUL_HOME`` (tests
    and custom setups), then ``XDG_CONFIG_HOME``, else ``~/.config``."""
    override = os.environ.get(SOUL_HOME_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "agentvcs" / "souls"


def _external_seed_path(soul_id_hex: str) -> Path:
    return _soul_home() / soul_id_hex / SEED_FILE


def birth(agentvcs_dir: Path) -> str:
    """Generate the agent's Soul (an Ed25519 keypair) on repository init. Idempotent:
    if a Soul already exists it is left untouched. Returns the public ``soul_id``.

    The public id is written into the repo (``.agentvcs/soul/soul.pub``); the secret
    seed is written **outside** the repo under :func:`_soul_home`, so copying the
    repo never copies the key."""
    sdir = _soul_path(agentvcs_dir)
    pub_path = sdir / PUB_FILE
    if pub_path.exists():
        return pub_path.read_text().strip()
    sdir.mkdir(parents=True, exist_ok=True)
    seed = secrets.token_bytes(32)
    soul_id_hex = ed.publickey(seed).hex()

    # the seed is a private key — store it outside the repo, 0o600, dir 0o700.
    seed_path = _external_seed_path(soul_id_hex)
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        seed_path.parent.chmod(0o700)
    except OSError:
        pass
    seed_path.write_text(seed.hex() + "\n")
    try:
        seed_path.chmod(0o600)
    except OSError:
        pass

    pub_path.write_text(soul_id_hex + "\n")
    return soul_id_hex


def soul_id(agentvcs_dir: Path) -> str | None:
    """The public identity of the agent whose repo this is (full 64-hex pubkey),
    or None if this repo predates the Soul layer."""
    pub_path = _soul_path(agentvcs_dir) / PUB_FILE
    return pub_path.read_text().strip() if pub_path.exists() else None


def _seed(agentvcs_dir: Path) -> bytes | None:
    """Load this repo's secret seed, or None if it isn't on this machine (e.g. the
    repo was copied without the out-of-repo key — exactly the case we want to fail
    closed). Reads the external store first, then falls back to a legacy in-repo
    seed for Souls born before relocation."""
    sid = soul_id(agentvcs_dir)
    if sid:
        ext = _external_seed_path(sid)
        if ext.exists():
            try:
                return bytes.fromhex(ext.read_text().strip())
            except ValueError:
                return None
    legacy = _soul_path(agentvcs_dir) / SEED_FILE   # backward-compat
    if legacy.exists():
        try:
            return bytes.fromhex(legacy.read_text().strip())
        except ValueError:
            return None
    return None


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
