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
    runtime: str | None = None  # the operational frame, only captured in runtime mode
    swarm: str | None = None    # the sub-agent topology, only when agent.json declares one


class Repository:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.dir = self.workdir / AGENTVCS_DIR
        self.objects = ObjectStore(self.dir / "objects")

    # ------------------------------------------------------------------ setup
    @classmethod
    def init(cls, workdir, manifest: str | None = None,
             with_soul: bool = False) -> "Repository":
        repo = cls(Path(workdir))
        if repo.dir.exists():
            raise RepoError(f"{repo.workdir} is already an agentvcs repository",
                            code="ALREADY_REPO")
        (repo.dir / "objects").mkdir(parents=True)
        (repo.dir / "refs" / "heads").mkdir(parents=True)
        (repo.dir / "HEAD").write_text("ref: refs/heads/main\n")
        # Soul birth is **opt-in** (the DeSoc/crypto layer). By default agentvcs is
        # a pure multidimensional VCS — zero crypto surface, commits are unsigned.
        # `init(with_soul=True)` (CLI `--with-soul`/`--enable-crypto`) gives the
        # instance an Ed25519 identity so its signed history is unforgeable
        # provenance (see soul.py). Everything downstream already degrades
        # gracefully when no Soul exists: sign_commit() returns the commit
        # unchanged, verify reads "unsigned", freeze mints no SBT.
        if with_soul:
            from . import soul as _soul
            _soul.birth(repo.dir)
        manifest_path = repo.workdir / MANIFEST
        if not manifest_path.exists():
            manifest_path.write_text(manifest or _TEMPLATE_MANIFEST)
        agents_path = repo.workdir / "AGENTS.md"
        if not agents_path.exists():
            agents_path.write_text(_AGENTS_MD + (_AGENTS_MD_SOUL if with_soul else ""))
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
    def rollback(self, target: str | None = None, reason: str | None = None) -> dict:
        """The agent panic button. Restore the full multidimensional state
        (code + goal + models + trace) to a prior commit and move the current
        branch there. The previous head is saved to ROLLBACK_HEAD so the undo
        is itself reversible — nothing is ever lost from the object store.

        ``reason`` records *why* the rollback happened in the durable ledger
        (e.g. an eval regression: "success_rate 0.4 < 0.75"). When omitted it
        falls back to the restored commit's goal text, preserving prior
        behavior byte-for-byte."""
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
        goal_text = self.objects.read_obj(commit["goal"])["text"] if commit.get("goal") else ""
        # Append to the durable rollback ledger (.agentvcs/rollbacks.jsonl)
        ledger_path = self.dir / "rollbacks.jsonl"
        with ledger_path.open("a", encoding="utf-8") as _lf:
            _lf.write(json.dumps({
                "from": head,
                "to": target,
                "timestamp": int(time.time()),
                "reason": reason if reason is not None else goal_text,
            }, ensure_ascii=False) + "\n")
        return {
            "restored_to": target,
            "previous_head": head,
            "goal": goal_text,
            "state": commit["state"],
        }

    def read_rollbacks(self) -> list[dict]:
        """Return all rollback events from the durable ledger, oldest first."""
        ledger_path = self.dir / "rollbacks.jsonl"
        if not ledger_path.exists():
            return []
        result = []
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return result

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

    # -------------------------------------------------------------- mode/runtime
    def mode(self) -> str:
        """``vcs`` (version code+goal+models+trace — the original proposal) or
        ``runtime`` (additionally capture the operational frame the agent's
        closed runtime hides). A ``-C``-level override beats the manifest."""
        return getattr(self, "_mode_override", None) or self.read_manifest().get("mode", "vcs")

    def _build_runtime_frame(self, manifest: dict, messages: list) -> dict:
        """Reconstruct the operational frame. A provider that knows its native
        log's token/usage fields (claude-code, qwen-code) gives the high-fidelity
        version; otherwise we derive what we can from the normalized messages."""
        from .runtime.frame import build_frame
        budget = manifest.get("budget", {})
        decl = manifest.get("trace")
        if isinstance(decl, dict):
            from .traces import pull_runtime
            frame = pull_runtime(decl, self.workdir, budget=budget)
            if frame is not None:
                return frame
        return build_frame(messages, budget=budget)

    def runtime_frame(self) -> dict:
        """The live operational frame for the *current* working state — what an
        agent gets back from ``agentvcs budget`` / ``context`` / ``runtime``
        before it even commits. This is the visibility the runtime denies it."""
        manifest = self.read_manifest()
        messages = self._resolve_trace(manifest.get("trace"))
        return self._build_runtime_frame(manifest, messages)

    # -------------------------------------------------------------- eval gate
    # Eval results live in a side-table keyed by commit id, NOT in the commit
    # object: a measurement about a commit, not part of its content identity.
    def write_eval(self, oid: str, result: dict) -> None:
        d = self.dir / "evals"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{oid}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    def read_eval(self, oid: str | None) -> dict | None:
        if not oid:
            return None
        path = self.dir / "evals" / f"{oid}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _read_trace(self, path: Path) -> list:
        if not path.exists():
            return []
        if path.suffix == ".jsonl":
            return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else data.get("messages", [])

    def _resolve_trace(self, decl) -> list:
        """Materialize the trace dimension. ``decl`` is either a relative path
        (classic — ``"traces/run.jsonl"``) or a provider object
        (``{"provider": "claude-code", ...}``) that auto-discovers the agent's
        native session log. Returns the ordered message list (maybe empty)."""
        if not decl:
            return []
        if isinstance(decl, str):
            return self._read_trace(self.workdir / decl)
        if isinstance(decl, dict):
            from .traces import pull_trace
            return pull_trace(decl, self.workdir)
        raise RepoError(f"invalid 'trace' in agent.json: {type(decl).__name__}",
                        code="BAD_TRACE")

    def trace_info(self) -> dict:
        """Describe the current trace source without committing — which file or
        native transcript will be captured, and how many messages it holds. Lets
        an agent (or a human) confirm auto-discovery hooked the right session."""
        decl = self.read_manifest().get("trace")
        if not decl:
            return {"kind": "none", "messages": 0}
        if isinstance(decl, str):
            path = self.workdir / decl
            return {"kind": "path", "path": str(path), "exists": path.exists(),
                    "messages": len(self._read_trace(path))}
        if isinstance(decl, dict):
            from .traces import describe_trace
            return {"kind": "provider", **describe_trace(decl, self.workdir)}
        return {"kind": "invalid"}

    def _resolve_models(self, declared: list, messages: list) -> list:
        """Fill any model pin marked ``"auto": true`` from the model that
        actually produced the trace, so the pin can't drift from reality."""
        if not any(isinstance(m, dict) and m.get("auto") for m in declared):
            return declared
        detected = next((m.get("model") for m in reversed(messages)
                         if isinstance(m, dict) and m.get("model")), None)
        out = []
        for m in declared:
            if isinstance(m, dict) and m.get("auto"):
                m = {**m, "model": m.get("model") or detected or ""}
                m.setdefault("provider", "anthropic")
            out.append(m)
        return out

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

        # goal / trace / models dimensions
        manifest = self.read_manifest()
        goal = put({"type": "goal", "text": manifest.get("goal", ""),
                    "parent": manifest.get("parent_goal")})

        # trace may be a relative path (classic) or a provider declaration that
        # auto-discovers the agent's native session log (e.g. Claude Code).
        messages = self._resolve_trace(manifest.get("trace"))
        trace = put({"type": "trace", "messages": messages}) if messages else None

        # models may be declared explicitly, or marked "auto" to be detected from
        # the trace — pinning the model that actually ran, not a hand-typed guess.
        models = [
            put({"type": "modelpin",
                 "provider": m.get("provider", ""),
                 "model": m.get("model", ""),
                 "version": m.get("version"),
                 "params": m.get("params", {})})
            for m in self._resolve_models(manifest.get("models", []), messages)
        ]

        state = manifest.get("state", "fluid")

        # runtime dimension: only in runtime mode, capture the operational frame
        # (budget, context pressure, model routing, tool & subagent usage) the
        # closed runtime never exposes — reconstructed from the same session log.
        runtime_oid = None
        if self.mode() == "runtime":
            frame = self._build_runtime_frame(manifest, messages)
            runtime_oid = put({"type": "runtime", **frame})

        # swarm dimension: the versioned sub-agent topology. Only captured when
        # agent.json declares "swarm", so commits without one stay byte-identical.
        swarm_oid = None
        swarm_decl = manifest.get("swarm")
        if swarm_decl:
            from .swarm import build_swarm
            swarm_obj = build_swarm(self, swarm_decl, write=write, messages=messages)
            if swarm_obj:
                swarm_oid = put(swarm_obj)

        return Snapshot(tree, goal, models, trace, state, manifest, runtime_oid,
                        swarm_oid)

    # ------------------------------------------------------------------ soul
    def soul_id(self) -> str | None:
        """This instance's public identity (Ed25519 pubkey), or None for a repo
        created before the Soul layer existed."""
        from . import soul
        return soul.soul_id(self.dir)

    def write_commit(self, commit: dict) -> str:
        """Sign a commit object with this instance's Soul (binding identity into
        the signed content) and write it to the store. The single choke-point all
        commit-creators go through, so every code path produces signed provenance."""
        from . import soul
        return self.objects.write_obj(soul.sign_commit(self.dir, commit))

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
        # keep vcs-mode commits byte-identical to before: only add the pointer
        # when a runtime frame was actually captured.
        if snap.runtime:
            commit["runtime"] = snap.runtime
        # same byte-compat rule for the swarm dimension.
        if snap.swarm:
            commit["swarm"] = snap.swarm
        oid = self.write_commit(commit)
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

## If your shell cwd is not sticky, use `-C`
Pass `-C <project-dir>` (like `git -C`) so the command runs against that repo
regardless of the current directory — e.g. `agentvcs -C /path/to/proj commit -m "..." --json`.
`init` creates the directory if needed. This avoids accidentally writing into the
wrong folder between commands.

## The loop you should follow
1. Read `agent.json` — it declares this iteration's `goal`, `models`, and `trace`
   file. Keep it accurate; it IS the non-code state you are versioning.
2. Do your work (edit code, update the goal, append messages to the trace file).
3. `agentvcs commit -m "what changed" --json` after each meaningful iteration.
4. `agentvcs diff --json` to see *which dimension* moved (code vs goal vs models
   vs trace). `agentvcs status --json` for uncommitted changes.
5. Made it worse? `agentvcs rollback --json` restores the full prior state. The
   undo is itself reversible (previous head saved to `.agentvcs/ROLLBACK_HEAD`).
6. Prove it works: if `agent.json` declares an `eval`, run `agentvcs eval --json`
   (it runs your check, e.g. `pytest -q`, and records the pass/score for HEAD).
7. Solution is stable and *verified*? `agentvcs freeze --json` crystallizes it into a
   deterministic recipe under `crystal/` (models pinned to temperature 0). When an
   `eval` is declared, freeze refuses unless it passed — so a frozen recipe is a
   proven one. `--force` overrides the gate.

## Try alternatives without risk
`agentvcs branch <name>` then `agentvcs checkout <name>` forks the *execution*,
not just the text. Explore a strategy on a branch; keep the winner.

## Runtime mode — see what your runtime hides, and don't repeat work
If this repo is in **runtime mode** (`"mode": "runtime"` in agent.json), agentvcs
reconstructs the operational state your closed runtime never shows you — from the
same native session log it already keeps. Use it to work within your means:
- `agentvcs recall "<goal>" --json` — **do this first.** If a crystallized recipe
  already solves this goal, `agentvcs replay <commit>` re-runs it deterministically
  for ~$0 instead of you re-deriving it.
- `agentvcs budget --json` — tokens + dollars spent, and how much of the ceiling
  remains. Check before launching expensive work; stop if you're over budget.
- `agentvcs context --json` — how full your context window is and how many times
  it was silently compacted (context you can no longer see).
- `agentvcs runtime --json` — the full frame: budget, context, model routing,
  tool usage, subagent fan-out. Every `commit` in runtime mode versions it, so
  `agentvcs diff` shows whether a change spiked cost or context pressure.

This works the same whether you are Claude Code, qwen-code, or anything else —
agentvcs is the neutral substrate, not your runtime.

Full contract and error codes: see `docs/AGENT_MODE.md` in the agentvcs project.
"""


# Appended to AGENTS.md only when the repo is initialized with the opt-in crypto
# layer (`agentvcs init --with-soul`). A default repo never mentions Souls/SBTs —
# the core is a pure VCS; this section exists only when the identity layer is on.
_AGENTS_MD_SOUL = """
## Your Soul: identity, provenance & reputation (crypto layer — enabled for this repo)
This repo was initialized with `--with-soul`, so this instance was born with an
Ed25519 **Soul**. Every commit you make is signed by it, so your history of traces
is unforgeable provenance. The secret seed lives in `.agentvcs/soul/` — never commit
it, never share it; the public `soul_id` is safe to publish.
- `agentvcs verify [--all] --json` — confirm your commits (and SBTs) validate; a
  tampered commit reads `FORGED`.
- `agentvcs soul --json` — your CV: identity + the Soulbound Tokens (SBTs) you've
  earned. A *verified* `freeze` mints one — proof you solved a goal, tied to a signed
  commit. Reputation is bound to your Soul, not copyable with your files.
"""
