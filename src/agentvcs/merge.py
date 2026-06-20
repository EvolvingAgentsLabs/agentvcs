"""Three-way multidimensional merge for agentvcs.

Implements ``agentvcs merge <branch>`` with:
  - merge-base computation (LCA over the full parent DAG)
  - three-way code merge (line-level with conflict markers)
  - model-pin union
  - reconciliation bundle + optional --reconcile CMD seam
  - two-parent merge commit
"""
from __future__ import annotations

import difflib
import json
import shlex
import subprocess
import time
from collections import deque
from typing import Optional

from .diff import diff_commits
from .repository import Repository, RepoError


# ------------------------------------------------------------------ merge-base

def merge_base(repo: Repository, a_oid: str, b_oid: str) -> Optional[str]:
    """Lowest common ancestor of two commits over the full parent DAG.

    BFS ancestors of *a* into a set, then BFS from *b* returning the first
    node already in that set (breadth order = nearest ancestor).
    Returns None if no common ancestor exists.
    """
    def ancestors(start: str) -> set:
        visited: set = set()
        q: deque = deque([start])
        while q:
            oid = q.popleft()
            if oid in visited:
                continue
            visited.add(oid)
            try:
                commit = repo.objects.read_obj(oid)
                for p in (commit.get("parents") or []):
                    if p not in visited:
                        q.append(p)
            except Exception:
                pass
        return visited

    a_ancestors = ancestors(a_oid)

    # BFS from b; first node in a_ancestors is the LCA
    q: deque = deque([b_oid])
    visited: set = set()
    while q:
        oid = q.popleft()
        if oid in visited:
            continue
        visited.add(oid)
        if oid in a_ancestors:
            return oid
        try:
            commit = repo.objects.read_obj(oid)
            for p in (commit.get("parents") or []):
                if p not in visited:
                    q.append(p)
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ is-ancestor

def _is_ancestor(repo: Repository, candidate: str, descendant: str) -> bool:
    """Return True if *candidate* is an ancestor of (or equal to) *descendant*."""
    q: deque = deque([descendant])
    seen: set = set()
    while q:
        oid = q.popleft()
        if oid in seen:
            continue
        seen.add(oid)
        if oid == candidate:
            return True
        try:
            commit = repo.objects.read_obj(oid)
            for p in (commit.get("parents") or []):
                if p not in seen:
                    q.append(p)
        except Exception:
            pass
    return False


# ------------------------------------------------------------------ tree helpers

def _tree_entries(repo: Repository, commit_oid: str) -> dict:
    commit = repo.objects.read_obj(commit_oid)
    return repo.objects.read_obj(commit["tree"])["entries"]


# ------------------------------------------------------------------ 3-way text merge

def _three_way_text(base_lines: list, ours_lines: list, theirs_lines: list,
                    path: str) -> tuple[list, bool]:
    """Attempt a line-level three-way merge.

    Returns (merged_lines, had_conflict).
    On overlap writes git-style conflict markers.
    """
    # Use SequenceMatcher to find matching blocks between base and each side
    sm_ours = difflib.SequenceMatcher(None, base_lines, ours_lines, autojunk=False)
    sm_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines, autojunk=False)

    # Build opcode maps: base_line_index -> (ours_replacement, theirs_replacement)
    # Simple approach: collect hunks from both sides, detect overlaps
    ours_ops = sm_ours.get_opcodes()
    theirs_ops = sm_theirs.get_opcodes()

    # Convert to a list of (base_start, base_end, ours_lines, theirs_lines) regions
    # We'll walk base line by line and emit merged output
    merged: list = []
    had_conflict = False

    # Build change maps indexed by base line ranges
    # For each base position, record what ours and theirs want
    def build_change_map(ops, side_lines):
        """Returns dict: base_start -> (base_end, replacement_lines)"""
        changes = {}
        for tag, i1, i2, j1, j2 in ops:
            if tag != "equal":
                changes[i1] = (i2, side_lines[j1:j2])
        return changes

    ours_changes = build_change_map(ours_ops, ours_lines)
    theirs_changes = build_change_map(theirs_ops, theirs_lines)

    base_len = len(base_lines)
    i = 0
    while i < base_len:
        ours_change = ours_changes.get(i)
        theirs_change = theirs_changes.get(i)

        if ours_change is None and theirs_change is None:
            # Both sides agree with base
            merged.append(base_lines[i])
            i += 1
        elif ours_change is not None and theirs_change is None:
            # Only ours changed
            ours_end, ours_repl = ours_change
            merged.extend(ours_repl)
            i = ours_end if ours_end > i else i + 1
        elif ours_change is None and theirs_change is not None:
            # Only theirs changed
            theirs_end, theirs_repl = theirs_change
            merged.extend(theirs_repl)
            i = theirs_end if theirs_end > i else i + 1
        else:
            # Both changed — check if they agree
            ours_end, ours_repl = ours_change
            theirs_end, theirs_repl = theirs_change
            if ours_repl == theirs_repl:
                merged.extend(ours_repl)
                i = max(ours_end, theirs_end)
                if i <= (i - 1):
                    i += 1
            else:
                # Conflict
                had_conflict = True
                merged.append("<<<<<<< ours\n")
                merged.extend(ours_repl)
                merged.append("=======\n")
                merged.extend(theirs_repl)
                merged.append(">>>>>>> theirs\n")
                i = max(ours_end, theirs_end)
                if i == 0:
                    i = 1

    # Append any trailing lines from ours/theirs not covered by base changes
    # (insertions at end)
    # Find what ours appended after base
    ours_tail_start = None
    for tag, i1, i2, j1, j2 in ours_ops:
        if tag in ("insert", "replace") and i1 == base_len:
            ours_tail_start = (j1, j2)
    theirs_tail_start = None
    for tag, i1, i2, j1, j2 in theirs_ops:
        if tag in ("insert", "replace") and i1 == base_len:
            theirs_tail_start = (j1, j2)

    if ours_tail_start and theirs_tail_start:
        ours_tail = ours_lines[ours_tail_start[0]:ours_tail_start[1]]
        theirs_tail = theirs_lines[theirs_tail_start[0]:theirs_tail_start[1]]
        if ours_tail == theirs_tail:
            merged.extend(ours_tail)
        else:
            had_conflict = True
            merged.append("<<<<<<< ours\n")
            merged.extend(ours_tail)
            merged.append("=======\n")
            merged.extend(theirs_tail)
            merged.append(">>>>>>> theirs\n")
    elif ours_tail_start:
        merged.extend(ours_lines[ours_tail_start[0]:ours_tail_start[1]])
    elif theirs_tail_start:
        merged.extend(theirs_lines[theirs_tail_start[0]:theirs_tail_start[1]])

    return merged, had_conflict


# ------------------------------------------------------------------ code merge

def _merge_trees(repo: Repository, base_oid: Optional[str],
                 ours_oid: str, theirs_oid: str) -> tuple[dict, list]:
    """Three-way merge of tree entries.

    Returns (merged_entries: {path: blob_oid}, conflicts: [{path, reason}]).
    """
    base_entries = _tree_entries(repo, base_oid) if base_oid else {}
    ours_entries = _tree_entries(repo, ours_oid)
    theirs_entries = _tree_entries(repo, theirs_oid)

    all_paths = set(base_entries) | set(ours_entries) | set(theirs_entries)
    merged: dict = {}
    conflicts: list = []

    for path in sorted(all_paths):
        base_blob = base_entries.get(path)
        ours_blob = ours_entries.get(path)
        theirs_blob = theirs_entries.get(path)

        # Path only in one side
        if ours_blob is None and theirs_blob is None:
            # Only in base — deleted on both sides; omit
            continue
        if ours_blob is None:
            if base_blob is None:
                # Added only on theirs
                merged[path] = theirs_blob
            elif base_blob == theirs_blob:
                # Deleted on ours, unchanged on theirs → take deletion (omit)
                pass
            else:
                # Deleted on ours, modified on theirs → conflict (keep theirs)
                merged[path] = theirs_blob
                conflicts.append({"path": path, "reason": "deleted on ours, modified on theirs"})
            continue
        if theirs_blob is None:
            if base_blob is None:
                # Added only on ours
                merged[path] = ours_blob
            elif base_blob == ours_blob:
                # Deleted on theirs, unchanged on ours → take deletion (omit)
                pass
            else:
                # Deleted on theirs, modified on ours → conflict (keep ours)
                merged[path] = ours_blob
                conflicts.append({"path": path, "reason": "deleted on theirs, modified on ours"})
            continue

        # Both sides have the file
        if ours_blob == theirs_blob:
            merged[path] = ours_blob
            continue
        if base_blob == ours_blob:
            # Ours unchanged, take theirs
            merged[path] = theirs_blob
            continue
        if base_blob == theirs_blob:
            # Theirs unchanged, take ours
            merged[path] = ours_blob
            continue

        # Both sides changed — attempt text merge
        try:
            base_data = repo.objects.read_blob(base_blob) if base_blob else b""
            ours_data = repo.objects.read_blob(ours_blob)
            theirs_data = repo.objects.read_blob(theirs_blob)

            base_text = base_data.decode("utf-8")
            ours_text = ours_data.decode("utf-8")
            theirs_text = theirs_data.decode("utf-8")

            base_lines = base_text.splitlines(keepends=True)
            ours_lines = ours_text.splitlines(keepends=True)
            theirs_lines = theirs_text.splitlines(keepends=True)

            merged_lines, had_conflict = _three_way_text(
                base_lines, ours_lines, theirs_lines, path)
            merged_text = "".join(merged_lines)
            merged_blob = repo.objects.write_blob(merged_text.encode("utf-8"))
            merged[path] = merged_blob
            if had_conflict:
                conflicts.append({"path": path, "reason": "content conflict"})
        except UnicodeDecodeError:
            # Binary conflict — keep ours
            merged[path] = ours_blob
            conflicts.append({"path": path, "reason": "binary conflict"})

    return merged, conflicts


# ------------------------------------------------------------------ model merge

def _merge_models(repo: Repository, ours_models: list, theirs_models: list,
                  conflicts: list) -> list:
    """Union of model pins, dedup by provider/model.

    Same model with differing params → keep ours, record a conflict note.
    """
    seen: dict = {}  # (provider, model) -> oid
    result: list = []

    def add_pin(oid):
        m = repo.objects.read_obj(oid)
        key = (m.get("provider", ""), m.get("model", ""))
        if key not in seen:
            seen[key] = oid
            result.append(oid)
        else:
            existing = repo.objects.read_obj(seen[key])
            if existing.get("params") != m.get("params"):
                conflicts.append({
                    "path": f"models/{key[0]}/{key[1]}",
                    "reason": f"model params conflict: keeping ours"
                })

    for oid in ours_models:
        add_pin(oid)
    for oid in theirs_models:
        add_pin(oid)

    return result


# ------------------------------------------------------------------ reconcile

def _run_reconcile(cmd: str, bundle: dict) -> Optional[dict]:
    """Run the reconcile command, write bundle to stdin, parse stdout.

    Returns parsed dict or None on failure.
    """
    try:
        cmd_parts = shlex.split(cmd)
        payload = json.dumps(bundle, ensure_ascii=False)
        proc = subprocess.run(
            cmd_parts, input=payload, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        parsed = json.loads(proc.stdout.strip())
        # Validate shape
        if not isinstance(parsed.get("goal"), str):
            return None
        if not isinstance(parsed.get("trace"), list):
            return None
        return parsed
    except Exception:
        return None


def _mechanical_reconcile(ours_branch: str, ours_oid: str,
                           theirs_branch: str, theirs_oid: str,
                           ours_goal: str, theirs_goal: str) -> dict:
    """Deterministic fallback reconciliation (no LLM)."""
    merged_goal = f"[merge] {ours_goal} + {theirs_goal}"
    merged_trace = [{
        "role": "system",
        "content": (
            f"KNOWLEDGE RECONCILIATION (mechanical): merged "
            f"{ours_branch}@{ours_oid[:8]} + {theirs_branch}@{theirs_oid[:8]}. "
            f"Both parent traces are preserved and reachable via this commit's "
            f"two parents; no semantic reconciliation was performed."
        )
    }]
    return {"goal": merged_goal, "trace": merged_trace, "notes": ""}


# ------------------------------------------------------------------ main merge

def merge(repo: Repository, branch: str, reconcile: Optional[str] = None,
          force: bool = False) -> dict:
    """Merge *branch* into HEAD.

    Returns a dict with at minimum ``{"status": ...}``.
    Possible statuses: "up_to_date", "fast_forward", "conflict", "merged".
    """
    # Resolve refs
    ours_oid = repo.head_commit()
    if ours_oid is None:
        raise RepoError("cannot merge before the first commit", code="NO_COMMITS")

    theirs_oid = repo._resolve(branch, expect="commit")
    if theirs_oid is None:
        raise RepoError(f"cannot resolve branch '{branch}'", code="BAD_REF")

    current_branch = repo.current_branch() or "HEAD"

    # Fast-path: already merged
    if theirs_oid == ours_oid:
        return {"status": "up_to_date"}

    # Check ancestry
    if _is_ancestor(repo, theirs_oid, ours_oid):
        # theirs is an ancestor of ours → already merged
        return {"status": "up_to_date"}

    if _is_ancestor(repo, ours_oid, theirs_oid):
        # ours is an ancestor of theirs → fast-forward
        ref = repo.dir / "refs" / "heads" / current_branch
        if ref.exists():
            ref.write_text(theirs_oid + "\n")
        else:
            repo._set_head_commit(theirs_oid)
        repo._restore_tree(theirs_oid)
        return {"status": "fast_forward", "commit": theirs_oid}

    # Find merge base
    base_oid = merge_base(repo, ours_oid, theirs_oid)

    # Three-way merge of trees
    conflicts: list = []
    merged_entries, tree_conflicts = _merge_trees(repo, base_oid, ours_oid, theirs_oid)
    conflicts.extend(tree_conflicts)

    # Merge model pins
    ours_commit = repo.objects.read_obj(ours_oid)
    theirs_commit = repo.objects.read_obj(theirs_oid)
    merged_models = _merge_models(
        repo, ours_commit.get("models", []), theirs_commit.get("models", []), conflicts)

    # Build reconciliation bundle
    ours_goal_obj = repo.objects.read_obj(ours_commit["goal"]) if ours_commit.get("goal") else {}
    theirs_goal_obj = repo.objects.read_obj(theirs_commit["goal"]) if theirs_commit.get("goal") else {}
    ours_goal_text = ours_goal_obj.get("text", "")
    theirs_goal_text = theirs_goal_obj.get("text", "")

    ours_trace_msgs = []
    if ours_commit.get("trace"):
        try:
            ours_trace_msgs = repo.objects.read_obj(ours_commit["trace"])["messages"]
        except Exception:
            pass

    theirs_trace_msgs = []
    if theirs_commit.get("trace"):
        try:
            theirs_trace_msgs = repo.objects.read_obj(theirs_commit["trace"])["messages"]
        except Exception:
            pass

    base_goal_text = ""
    base_trace_msgs = []
    if base_oid:
        try:
            base_commit = repo.objects.read_obj(base_oid)
            if base_commit.get("goal"):
                base_goal_text = repo.objects.read_obj(base_commit["goal"]).get("text", "")
            if base_commit.get("trace"):
                base_trace_msgs = repo.objects.read_obj(base_commit["trace"])["messages"]
        except Exception:
            pass

    ours_code_diff = diff_commits(repo, base_oid, ours_oid)["code"] if base_oid else {}
    theirs_code_diff = diff_commits(repo, base_oid, theirs_oid)["code"] if base_oid else {}

    bundle = {
        "base": {
            "commit": base_oid,
            "goal": base_goal_text,
            "trace_messages": base_trace_msgs,
        },
        "ours": {
            "branch": current_branch,
            "commit": ours_oid,
            "goal": ours_goal_text,
            "trace_messages": ours_trace_msgs,
            "code_diff": ours_code_diff,
        },
        "theirs": {
            "branch": branch,
            "commit": theirs_oid,
            "goal": theirs_goal_text,
            "trace_messages": theirs_trace_msgs,
            "code_diff": theirs_code_diff,
        },
        "conflicts": conflicts,
    }

    # Reconcile goal + trace
    reconciled = None
    if reconcile:
        reconciled = _run_reconcile(reconcile, bundle)

    if reconciled is None:
        reconciled = _mechanical_reconcile(
            current_branch, ours_oid, branch, theirs_oid,
            ours_goal_text, theirs_goal_text)

    # If conflicts and not force → write conflict markers to working tree, return
    if conflicts and not force:
        # Write conflict-marked files to working tree
        for path, blob_oid in merged_entries.items():
            dest = repo.workdir / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(repo.objects.read_blob(blob_oid))
        return {"status": "conflict", "conflicts": conflicts, "ok": False}

    # Write the merged tree object
    merged_tree_oid = repo.objects.write_obj({"type": "tree", "entries": merged_entries})

    # Write goal and trace objects
    new_goal_oid = repo.objects.write_obj({
        "type": "goal",
        "text": reconciled["goal"],
        "parent": None,
    })
    new_trace_msgs = reconciled.get("trace") or []
    new_trace_oid = repo.objects.write_obj({
        "type": "trace",
        "messages": new_trace_msgs,
    }) if new_trace_msgs else None

    # Write the merge commit (two parents)
    merge_commit = {
        "type": "commit",
        "parents": [ours_oid, theirs_oid],
        "tree": merged_tree_oid,
        "goal": new_goal_oid,
        "models": merged_models,
        "trace": new_trace_oid,
        "state": "fluid",
        "metrics": {},
        "message": f"merge {branch} into {current_branch}",
        "author": "agent",
        "timestamp": int(time.time()),
    }
    new_oid = repo.write_commit(merge_commit)
    repo._set_head_commit(new_oid)

    # Restore working tree to merged state
    for path, blob_oid in merged_entries.items():
        dest = repo.workdir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(repo.objects.read_blob(blob_oid))

    return {
        "status": "merged",
        "commit": new_oid,
        "conflicts": conflicts,
        "goal": reconciled["goal"],
        "notes": reconciled.get("notes", ""),
    }
