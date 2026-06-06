"""Content-addressed object store — the storage substrate of agentvcs.

Every object (commit, tree, goal, model pin, trace, crystal recipe) is serialized
to a canonical byte form, hashed with SHA-256, and stored under
``.agentvcs/objects/<aa>/<rest>`` exactly like git's loose objects. Identical
content yields an identical id, so storage is automatically deduplicated and any
dimension shared across commits is stored once.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path


def canonical(obj: dict) -> bytes:
    """Deterministic JSON encoding. Same logical object -> same bytes -> same id."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, oid: str) -> Path:
        return self.root / oid[:2] / oid[2:]

    # --- hashing without writing (used by status/diff dry runs) ---
    def hash_obj(self, obj: dict) -> str:
        return hash_bytes(canonical(obj))

    def hash_blob(self, data: bytes) -> str:
        return hash_bytes(b"blob\0" + data)

    # --- writing ---
    def write_obj(self, obj: dict) -> str:
        oid = self.hash_obj(obj)
        self._store(oid, canonical(obj))
        return oid

    def write_blob(self, data: bytes) -> str:
        oid = self.hash_blob(data)
        self._store(oid, b"blob\0" + data)
        return oid

    def _store(self, oid: str, raw: bytes) -> None:
        path = self._path(oid)
        if path.exists():
            return  # content-addressed: already have it
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zlib.compress(raw))

    # --- reading ---
    def exists(self, oid: str) -> bool:
        return self._path(oid).exists()

    def read_raw(self, oid: str) -> bytes:
        return zlib.decompress(self._path(oid).read_bytes())

    def read_obj(self, oid: str) -> dict:
        return json.loads(self.read_raw(oid))

    def read_blob(self, oid: str) -> bytes:
        raw = self.read_raw(oid)
        if not raw.startswith(b"blob\0"):
            raise ValueError(f"{oid} is not a blob")
        return raw[5:]
