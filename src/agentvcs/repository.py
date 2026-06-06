"""The multidimensional repository.

A traditional VCS versions one dimension: source code. agentvcs versions four,
captured together in every commit:

  * **code**   — a snapshot tree of the working files (the deterministic part)
  * **goal**   — the high-level objective the fleet was pursuing
  * **models** — the exact model pins (provider/model/version/params) in force
  * **trace**  — the inter-agent message log that produced this state

Plus a **state** flag per commit: ``fluid`` (still evolving, probabilistic) or
``crystallized`` (frozen to a deterministic recipe — see crystallize.py).

The goal/models/trace dimensions are declared in ``agent.json`` at the repo root.
"""
from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .objects import ObjectStore

AGENTVCS_DIR = ".agentvcs"
MANIFEST = "agent.json"
IGNORE_FILE = ".agentvcsignore"
DEFAULT_IGNORE = [
    AGENTVCS_DIR, ".git", "__pycache__", "*.pyc", ".venv", "venv",
    "node_modules", ".DS_Store",
]


class RepoError(Exception):
    pass


@dataclass
class Snapshot:
    tree: str
    goal: str
    models: list[str]
    trace: str | None
    state: str
    manifest: dict


class Repository:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.dir = self.workdir / AGENTVCS_DIR
        self.objects = ObjectStore(self.dir / "objects")

    # ------------------------------------------------------------------ setup
    @classmethod
    def init(cls, workdir) -> "Repository":
        repo = cls(Path(workdir))
        if repo.dir.exists():
            raise RepoError(f"{repo.workdir} is already an agentvcs repository")
        (repo.dir / "objects").mkdir(parents=True)
        (repo.dir / "refs" / "heads").mkdir(parents=True)
        (repo.dir / "HEAD").write_text("ref: refs/heads/main\n")
        manifest_path = repo.workdir / MANIFEST
        if not manifest_path.exists():
            manifest_path.write_text(_TEMPLATE_MANIFEST)
        return repo

    @classmethod
    def open(cls, start=None) -> "Repository":
        path = Path(start or Path.cwd()).resolve()
        for candidate in [path, *path.parents]:
            if (candidate / AGENTVCS_DIR).is_dir():
                return cls(candidate)
        raise RepoError("not an agentvcs repository (no .agentvcs found)")

    # ------------------------------------------------------------- references
    def _head_ref(self) -> tuple[str, str]:
        head = (self.dir / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            return "ref", head[4:].strip()
        return "detached", head

    def current_branch(self) -> str | None:
        kind, val = self._head_ref()
        return val.rsplit("/", 1)[-1] if kind == "ref" else None

    def head_commit(self) -> str | None:
        kind, val = self._head_ref()
        if kind == "detached":
            return val
        ref = self.dir / val
        return ref.read_text().strip() if ref.exists() else None

    def _set_head_commit(self, oid: str) -> None:
        kind, val = self._head_ref()
        if kind == "ref":
            ref = self.dir / val
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(oid + "\n")
        else:
            (self.dir / "HEAD").write_text(oid + "\n")

    def branches(self) -> dict[str, str]:
        heads = self.dir / "refs" / "heads"
        return {p.name: p.read_text().strip() for p in heads.glob("*")}

    def branch(self, name: str) -> str:
        head = self.head_commit()
        if head is None:
            raise RepoError("cannot branch before the first commit")
        ref = self.dir / "refs" / "heads" / name
        if ref.exists():
            raise RepoError(f"branch '{name}' already exists")
        ref.write_text(head + "\n")
        return head

    def checkout(self, target: str) -> str:
        ref = self.dir / "refs" / "heads" / target
        if ref.exists():
            commit_oid = ref.read_text().strip()
            (self.dir / "HEAD").write_text(f"ref: refs/heads/{target}\n")
        elif self.objects.exists(target):
            commit_oid = target
            (self.dir / "HEAD").write_text(commit_oid + "\n")  # detached
        else:
            raise RepoError(f"no branch or commit '{target}'")
        self._restore_tree(commit_oid)
        return commit_oid

    # ------------------------------------------------------- ignore handling
    def _ignore_patterns(self) -> list[str]:
        patterns = list(DEFAULT_IGNORE)
        ig = self.workdir / IGNORE_FILE
        if ig.exists():
            patterns += [l.strip() for l in ig.read_text().splitlines()
                         if l.strip() and not l.startswith("#")]
        return patterns

    def _ignored(self, rel: Path, patterns: list[str]) -> bool:
        rel_str = str(rel)
        for pat in patterns:
            if fnmatch.fnmatch(rel_str, pat):
                return True
            if any(fnmatch.fnmatch(part, pat) for part in rel.parts):
                return True
        return False

    # ---------------------------------------------------------- manifest I/O
    def read_manifest(self) -> dict:
        path = self.workdir / MANIFEST
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _read_trace(self, path: Path) -> list:
        if not path.exists():
            return []
        if path.suffix == ".jsonl":
            return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else data.get("messages", [])

    # ------------------------------------------------------------- snapshots
    def snapshot(self, write: bool = True) -> Snapshot:
        put = self.objects.write_obj if write else self.objects.hash_obj
        put_blob = self.objects.write_blob if write else self.objects.hash_blob

        # code dimension
        patterns = self._ignore_patterns()
        entries: dict[str, str] = {}
        for path in sorted(self.workdir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.workdir)
            if self._ignored(rel, patterns):
                continue
            entries[str(rel)] = put_blob(path.read_bytes())
        tree = put({"type": "tree", "entries": entries})

        # goal / models / trace dimensions
        manifest = self.read_manifest()
        goal = put({"type": "goal", "text": manifest.get("goal", ""),
                    "parent": manifest.get("parent_goal")})
        models = [
            put({"type": "modelpin",
                 "provider": m.get("provider", ""),
                 "model": m.get("model", ""),
                 "version": m.get("version"),
                 "params": m.get("params", {})})
            for m in manifest.get("models", [])
        ]
        trace = None
        trace_rel = manifest.get("trace")
        if trace_rel:
            messages = self._read_trace(self.workdir / trace_rel)
            if messages:
                trace = put({"type": "trace", "messages": messages})

        state = manifest.get("state", "fluid")
        return Snapshot(tree, goal, models, trace, state, manifest)

    # --------------------------------------------------------------- commits
    def commit(self, message: str, author: str = "agent", timestamp: int | None = None) -> str:
        snap = self.snapshot(write=True)
        parent = self.head_commit()
        commit = {
            "type": "commit",
            "parents": [parent] if parent else [],
            "tree": snap.tree,
            "goal": snap.goal,
            "models": snap.models,
            "trace": snap.trace,
            "state": snap.state,
            "metrics": snap.manifest.get("metrics", {}),
            "message": message,
            "author": author,
            "timestamp": timestamp if timestamp is not None else int(time.time()),
        }
        oid = self.objects.write_obj(commit)
        self._set_head_commit(oid)
        return oid

    def log(self, start: str | None = None) -> list[tuple[str, dict]]:
        oid = start or self.head_commit()
        history = []
        seen = set()
        while oid and oid not in seen:
            seen.add(oid)
            commit = self.objects.read_obj(oid)
            history.append((oid, commit))
            parents = commit.get("parents") or []
            oid = parents[0] if parents else None
        return history

    # ------------------------------------------------------------- checkout
    def _restore_tree(self, commit_oid: str) -> None:
        commit = self.objects.read_obj(commit_oid)
        tree = self.objects.read_obj(commit["tree"])["entries"]
        patterns = self._ignore_patterns()

        # delete tracked working files not present in the target tree
        for path in list(self.workdir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.workdir)
            if self._ignored(rel, patterns):
                continue
            if str(rel) not in tree:
                path.unlink()

        # write the target tree
        for rel, blob_oid in tree.items():
            dest = self.workdir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.objects.read_blob(blob_oid))


_TEMPLATE_MANIFEST = """{
  "goal": "Describe the high-level objective this agent fleet is pursuing.",
  "models": [
    {
      "provider": "anthropic",
      "model": "claude-opus-4-8",
      "version": null,
      "params": { "temperature": 1.0 }
    }
  ],
  "trace": "traces/run.jsonl",
  "state": "fluid",
  "metrics": {}
}
"""
