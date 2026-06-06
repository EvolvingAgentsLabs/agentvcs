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
    """A user-facing error. ``code`` is a stable machine identifier agents can
    branch on (it never changes across versions, unlike the message)."""

    def __init__(self, message: str, code: str = "ERROR"):
        super().__init__(message)
        self.code = code


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
            raise RepoError(f"{repo.workdir} is already an agentvcs repository",
                            code="ALREADY_REPO")
        (repo.dir / "objects").mkdir(parents=True)
        (repo.dir / "refs" / "heads").mkdir(parents=True)
        (repo.dir / "HEAD").write_text("ref: refs/heads/main\n")
        manifest_path = repo.workdir / MANIFEST
        if not manifest_path.exists():
            manifest_path.write_text(_TEMPLATE_MANIFEST)
        agents_path = repo.workdir / "AGENTS.md"
        if not agents_path.exists():
            agents_path.write_text(_AGENTS_MD)
        return repo

    @classmethod
    def open(cls, start=None) -> "Repository":
        path = Path(start or Path.cwd()).resolve()
        for candidate in [path, *path.parents]:
            if (candidate / AGENTVCS_DIR).is_dir():
                return cls(candidate)
        raise RepoError("not an agentvcs repository (no .agentvcs found)",
                        code="NOT_A_REPO")

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
            raise RepoError("cannot branch before the first commit", code="NO_COMMITS")
        ref = self.dir / "refs" / "heads" / name
        if ref.exists():
            raise RepoError(f"branch '{name}' already exists", code="BRANCH_EXISTS")
        ref.write_text(head + "\n")
        return head

    def checkout(self, target: str) -> str:
        ref = self.dir / "refs" / "heads" / target
        if ref.exists():
            commit_oid = ref.read_text().strip()
            (self.dir / "HEAD").write_text(f"ref: refs/heads/{target}\n")
        else:
            commit_oid = self._resolve(target, expect="commit")
            (self.dir / "HEAD").write_text(commit_oid + "\n")  # detached
        self._restore_tree(commit_oid)
        return commit_oid

    # ----------------------------------------------------------- resolution
    def _safe_type(self, oid: str) -> str | None:
        try:
            return self.objects.read_obj(oid).get("type")
        except Exception:
            return None

    def _resolve(self, ref: str | None, expect: str | None = None) -> str | None:
        """Resolve a branch name, full object id, or unambiguous short prefix."""
        if ref is None:
            return None
        branch = self.dir / "refs" / "heads" / ref
        if branch.exists():
            return branch.read_text().strip()
        candidates: list[str] = []
        if self.objects.exists(ref):
            candidates = [ref]
        elif len(ref) >= 4:
            bucket = self.objects.root / ref[:2]
            if bucket.is_dir():
                candidates = [ref[:2] + p.name for p in bucket.iterdir()
                              if (ref[:2] + p.name).startswith(ref)]
        if expect:
            candidates = [c for c in candidates if self._safe_type(c) == expect]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise RepoError(f"ambiguous ref '{ref}'", code="AMBIGUOUS_REF")
        raise RepoError(f"cannot resolve '{ref}'", code="BAD_REF")

    # -------------------------------------------------------------- rollback
    def rollback(self, target: str | None = None) -> dict:
        """The agent panic button. Restore the full multidimensional state
        (code + goal + models + trace) to a prior commit and move the current
        branch there. The previous head is saved to ROLLBACK_HEAD so the undo
        is itself reversible — nothing is ever lost from the object store."""
        head = self.head_commit()
        if head is None:
            raise RepoError("no commits to roll back", code="NO_COMMITS")
        if target is None:
            parents = self.objects.read_obj(head).get("parents") or []
            if not parents:
                raise RepoError("HEAD has no parent to roll back to", code="NO_PARENT")
            target = parents[0]
        else:
            target = self._resolve(target, expect="commit")
        self._restore_tree(target)
        (self.dir / "ROLLBACK_HEAD").write_text(head + "\n")
        self._set_head_commit(target)
        commit = self.objects.read_obj(target)
        return {
            "restored_to": target,
            "previous_head": head,
            "goal": self.objects.read_obj(commit["goal"])["text"],
            "state": commit["state"],
        }

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


_AGENTS_MD = """# Working in this repository (for coding agents)

This project is versioned with **agentvcs** — a multidimensional VCS that tracks
not just code but the **goal**, the **models**, and the **message trace** of each
iteration, plus a **state** (`fluid` = still evolving, `crystallized` = frozen &
deterministic). Use it instead of (or alongside) git for the agent loop.

## Always use `--json`
Every command accepts `--json` and emits a single parseable object. Prefer it.
Errors become `{"ok": false, "error": {"code": "...", "message": "..."}}` — branch
on the stable `code`, never on the message text.

## The loop you should follow
1. Read `agent.json` — it declares this iteration's `goal`, `models`, and `trace`
   file. Keep it accurate; it IS the non-code state you are versioning.
2. Do your work (edit code, update the goal, append messages to the trace file).
3. `agentvcs commit -m "what changed" --json` after each meaningful iteration.
4. `agentvcs diff --json` to see *which dimension* moved (code vs goal vs models
   vs trace). `agentvcs status --json` for uncommitted changes.
5. Made it worse? `agentvcs rollback --json` restores the full prior state. The
   undo is itself reversible (previous head saved to `.agentvcs/ROLLBACK_HEAD`).
6. Solution is stable and trusted? `agentvcs freeze --json` crystallizes it into a
   deterministic recipe under `crystal/` (models pinned to temperature 0).

## Try alternatives without risk
`agentvcs branch <name>` then `agentvcs checkout <name>` forks the *execution*,
not just the text. Explore a strategy on a branch; keep the winner.

Full contract and error codes: see `docs/AGENT_MODE.md` in the agentvcs project.
"""
