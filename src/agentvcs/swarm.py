"""Swarm versioning — the sub-agent topology as a first-class, mergeable dimension.

An autonomous agent doesn't just rewrite its own code; it *spawns, reshapes and
retires sub-agents* at runtime. agentvcs already glimpsed this — the runtime frame
counts sub-agent fan-out (``classifier×2``) — but a head-count is not something you
can version or merge. Two branches that both touched the swarm (one deleted the
``data-analyst``, the other taught it new skills) cannot be reconciled from a tally.

This module promotes the swarm to a content-addressed object: a graph of nodes,
each a sub-agent with a *role*, a *skill* (its prompt/code, stored as a blob so it
deduplicates and diffs), and a *parent* edge to whoever instantiated it. Because a
node's skill is content-addressed, node identity is stable while its behaviour
evolves — exactly the property merge needs.

``merge_swarms`` reconciles the *lifecycle* of the whole topology with the same
three-way logic the code dimension uses, but per node instead of per file:
created/modified/deleted on each side relative to the merge base. The hard case the
README calls out — *deleted on one side, evolved on the other* — surfaces as an
explicit conflict (the revival is kept, like git's delete/modify), so a human or the
``--reconcile`` brain decides whether the retired sub-agent should come back.

Pure functions over the object store; no LLM, no I/O beyond blob read/write.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_swarm(repo, decl, *, write: bool = True,
                messages: Optional[list] = None) -> Optional[dict]:
    """Materialize the swarm dimension from an ``agent.json`` ``"swarm"`` decl.

    ``decl`` is one of:

    * ``"auto"`` (or ``{"auto": true}``) — **derive** the topology from the
      sub-agent fan-out the trace providers already reconstruct: one node per
      sub-agent type the runtime spawned, with its invocation ``count``. No manual
      declaration needed — the swarm an agent actually ran *is* the versioned one.
    * a relative path to a JSON file, or an inline mapping
      ``{node_id: {"role": str, "skill"|"skill_file": ..., "parent": id|None}}`` —
      an explicit topology.

    Each node's skill text is written as a content-addressed blob so the topology
    diffs and dedups like code. Returns the swarm object dict (``{"type":"swarm",
    "nodes": {...}}``) or ``None`` when no swarm is declared / discovered.
    """
    if not decl:
        return None

    put_blob = repo.objects.write_blob if write else repo.objects.hash_blob

    if decl == "auto" or (isinstance(decl, dict) and decl.get("auto")):
        raw = _derive_from_fanout(repo, messages)
    else:
        raw = _load_decl(repo, decl)
    if not raw:
        return None

    nodes: dict = {}
    for node_id, spec in raw.items():
        spec = spec or {}
        node = {
            "role": spec.get("role", ""),
            "skill": put_blob(_resolve_skill(repo, spec).encode("utf-8")),
            "parent": spec.get("parent"),
        }
        if spec.get("count") is not None:   # auto-derived nodes carry fan-out count
            node["count"] = spec["count"]
        nodes[str(node_id)] = node
    return {"type": "swarm", "nodes": nodes}


def _derive_from_fanout(repo, messages: Optional[list]) -> dict:
    """Reconstruct a topology from the runtime frame's sub-agent fan-out — the
    ``[{type, count}]`` the trace providers count from the native session log. Each
    distinct sub-agent type becomes a node parented to the coordinator."""
    try:
        manifest = repo.read_manifest()
        frame = repo._build_runtime_frame(manifest, messages or [])
    except Exception:
        return {}
    raw: dict = {}
    for s in frame.get("subagents", []) or []:
        kind = s.get("type")
        if not kind:
            continue
        raw[kind] = {"role": kind, "skill": "", "parent": "coordinator",
                     "count": s.get("count")}
    return raw


def _load_decl(repo, decl) -> dict:
    if isinstance(decl, dict):
        return decl
    if isinstance(decl, str):
        path = Path(repo.workdir) / decl
        if not path.exists():
            return {}
        import json
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        # accept either a bare node-map or {"nodes": {...}}
        return data.get("nodes", data) if isinstance(data, dict) else {}
    return {}


def _resolve_skill(repo, spec: dict) -> str:
    """A node's skill is inline ``"skill"`` text, or a ``"skill_file"`` path read
    from the working tree. Empty string when neither is given."""
    if spec.get("skill_file"):
        path = Path(repo.workdir) / spec["skill_file"]
        if path.exists():
            return path.read_text(errors="replace")
        return ""
    skill = spec.get("skill", "")
    return skill if isinstance(skill, str) else ""


# ------------------------------------------------------------------ node merge

def merge_swarms(base: Optional[dict], ours: Optional[dict],
                 theirs: Optional[dict]) -> tuple[Optional[dict], list]:
    """Three-way merge of two swarm topologies, node by node.

    Returns ``(merged_swarm_or_None, conflicts)``. ``conflicts`` entries look like
    ``{"path": "swarm/<node_id>", "reason": ...}`` so they slot into the same
    conflict list the code/model dimensions use.
    """
    if ours is None and theirs is None:
        return None, []

    base_nodes = (base or {}).get("nodes", {}) if base else {}
    ours_nodes = (ours or {}).get("nodes", {})
    theirs_nodes = (theirs or {}).get("nodes", {})

    all_ids = set(base_nodes) | set(ours_nodes) | set(theirs_nodes)
    merged: dict = {}
    conflicts: list = []

    for nid in sorted(all_ids):
        b = base_nodes.get(nid)
        o = ours_nodes.get(nid)
        t = theirs_nodes.get(nid)

        # present on neither side → retired by both (or never existed); drop it
        if o is None and t is None:
            continue

        # present on one side only
        if o is None:
            if b is None:
                merged[nid] = t          # added on theirs only → keep it
            elif b == t:
                pass                     # unchanged on theirs, retired on ours → honor retirement
            else:
                # ours retired it, theirs *evolved* it → revival conflict (keep theirs)
                merged[nid] = t
                conflicts.append({"path": f"swarm/{nid}",
                                  "reason": "retired on ours, evolved on theirs"})
            continue
        if t is None:
            if b is None:
                merged[nid] = o          # added on ours only → keep it
            elif b == o:
                pass                     # unchanged on ours, retired on theirs → honor retirement
            else:
                merged[nid] = o
                conflicts.append({"path": f"swarm/{nid}",
                                  "reason": "retired on theirs, evolved on ours"})
            continue

        # present on both
        if o == t:
            merged[nid] = o
            continue
        if b is not None and b == o:        # ours unchanged → take theirs
            merged[nid] = t
            continue
        if b is not None and b == t:        # theirs unchanged → take ours
            merged[nid] = o
            continue

        # both evolved the same node differently → node-level conflict (keep ours)
        merged[nid] = o
        conflicts.append({"path": f"swarm/{nid}",
                          "reason": "node evolved on both sides"})

    return {"type": "swarm", "nodes": merged}, conflicts
