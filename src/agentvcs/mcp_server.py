"""A Model Context Protocol (MCP) server for agentvcs — zero dependencies.

Exposes the agentvcs workflow as MCP tools so agents (Claude Code, Cursor, etc.)
can version their own work natively. Implements the MCP stdio transport
(newline-delimited JSON-RPC 2.0) using only the standard library, so it stays as
auditable as the rest of the core.

Run it directly (it talks JSON-RPC on stdin/stdout):

    agentvcs-mcp                 # operates on the repo found from the current dir

Register it with Claude Code:

    claude mcp add agentvcs -- agentvcs-mcp

Tools all operate on the agentvcs repository discovered from the server's working
directory (the project root Claude Code launched it in).
"""
from __future__ import annotations

import json
import sys

from . import __version__
from .crystallize import crystallize
from .diff import diff_commits
from .merge import merge
from .recall import recall
from .replay import replay
from .repository import Repository, RepoError

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "agentvcs", "version": __version__}


# --------------------------------------------------------------- tool impls
def _repo() -> Repository:
    return Repository.open()


def _commit_brief(repo, oid):
    c = repo.objects.read_obj(oid)
    return {"commit": oid, "state": c["state"], "message": c["message"],
            "goal": repo.objects.read_obj(c["goal"])["text"],
            "parents": c.get("parents", [])}


def tool_log(args):
    repo = _repo()
    return {"commits": [_commit_brief(repo, oid) for oid, _ in repo.log()]}


def tool_show(args):
    repo = _repo()
    ref = args.get("commit")
    oid = repo._resolve(ref, expect="commit") if ref else repo.head_commit()
    if not oid:
        return {"commit": None}
    c = repo.objects.read_obj(oid)
    models = [repo.objects.read_obj(m) for m in c["models"]]
    messages = repo.objects.read_obj(c["trace"])["messages"] if c.get("trace") else []
    out = {**_commit_brief(repo, oid), "models": models, "trace_messages": len(messages),
           "metrics": c.get("metrics", {}), "crystal": c.get("crystal")}
    if args.get("trace"):
        out["trace"] = messages
    return out


def tool_trace(args):
    return _repo().trace_info()


def tool_diff(args):
    repo = _repo()
    b = repo._resolve(args["b"], expect="commit") if args.get("b") else repo.head_commit()
    if not b:
        return {"diff": None}
    if args.get("a"):
        a = repo._resolve(args["a"], expect="commit")
    else:
        a = (repo.objects.read_obj(b)["parents"] or [None])[0]
    return {"a": a, "b": b, "diff": diff_commits(repo, a, b)}


def tool_status(args):
    repo = _repo()
    head = repo.head_commit()
    snap = repo.snapshot(write=True)
    pending = repo.objects.write_obj({
        "type": "commit", "parents": [], "tree": snap.tree, "goal": snap.goal,
        "models": snap.models, "trace": snap.trace, "state": snap.state,
        "metrics": {}, "message": "(working tree)", "author": "", "timestamp": 0})
    return {"branch": repo.current_branch(), "head": head,
            "diff": diff_commits(repo, head, pending)}


def tool_commit(args):
    repo = _repo()
    oid = repo.commit(args["message"], author=args.get("author", "agent"))
    return _commit_brief(repo, oid)


def tool_freeze(args):
    repo = _repo()
    new_oid, artifact = crystallize(repo, args.get("commit"), message=args.get("message"))
    return {"commit": new_oid, "state": "crystallized", "recipe_path": str(artifact)}


def tool_rollback(args):
    return _repo().rollback(args.get("ref"), reason=args.get("reason"))


def tool_replay(args):
    return replay(_repo(), args.get("commit"), executor=args.get("exec"))


def tool_branch(args):
    repo = _repo()
    if args.get("name"):
        oid = repo.branch(args["name"])
        return {"created": args["name"], "commit": oid}
    return {"current": repo.current_branch(),
            "branches": [{"name": n, "commit": o} for n, o in sorted(repo.branches().items())]}


def tool_checkout(args):
    repo = _repo()
    return {"ref": args["ref"], "commit": repo.checkout(args["ref"])}


# --- runtime-visibility tools: the state a closed runtime never exposes -------
def tool_runtime(args):
    return {"runtime": _repo().runtime_frame()}


def tool_budget(args):
    return {"budget": _repo().runtime_frame()["budget"]}


def tool_context(args):
    return {"context": _repo().runtime_frame()["context"]}


def tool_recall(args):
    repo = _repo()
    query = args.get("goal") or repo.read_manifest().get("goal", "")
    return {"query": query, "hits": recall(repo, query, limit=args.get("limit", 5),
                                           verified_only=args.get("verified_only", False))}


def tool_eval(args):
    from .eval import run_eval
    r = run_eval(_repo(), args.get("commit"))
    return {"commit": r["commit"], "passing": r["ok"], "passed": r["passed"],
            "total": r["total"], "score": r["score"], "command": r["command"]}


def tool_merge(args):
    repo = _repo()
    result = merge(repo, args["branch"],
                   reconcile=args.get("reconcile"),
                   force=args.get("force", False))
    return result


def tool_price(args):
    from .dynamics import price
    return price(_repo(), since=args.get("since"), trait=args.get("trait", "score"))


def tool_health(args):
    from .dynamics import health
    return health(_repo())


def tool_infobits(args):
    from .dynamics import infobits
    return infobits(_repo())


def tool_contain(args):
    from .dynamics import contain
    return contain(_repo(), fanout=args.get("fanout"), prob=args.get("prob"))


_REF = {"type": "string", "description": "branch name, full id, or short prefix"}
TOOLS = [
    {"name": "avcs_log", "description": "List the evolution history (commits with state, goal, message).",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_log},
    {"name": "avcs_show", "description": "Show one commit across all dimensions (code/goal/models/trace). Set trace=true to include the captured conversation.",
     "inputSchema": {"type": "object", "properties": {"commit": _REF,
         "trace": {"type": "boolean", "description": "include the full trace messages"}}}, "_fn": tool_show},
    {"name": "avcs_trace", "description": "Show the current trace source — which file or auto-discovered native session (e.g. Claude Code) will be captured, and how many messages it holds.",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_trace},
    {"name": "avcs_diff", "description": "Dimensional diff between two commits (defaults to parent..HEAD).",
     "inputSchema": {"type": "object", "properties": {"a": _REF, "b": _REF}}, "_fn": tool_diff},
    {"name": "avcs_status", "description": "Show uncommitted working-tree changes, per dimension.",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_status},
    {"name": "avcs_commit", "description": "Snapshot code + goal + models + trace into a new commit.",
     "inputSchema": {"type": "object", "properties": {
         "message": {"type": "string"}, "author": {"type": "string"}},
         "required": ["message"]}, "_fn": tool_commit},
    {"name": "avcs_freeze", "description": "Crystallize a fluid commit into a deterministic recipe (temperature 0).",
     "inputSchema": {"type": "object", "properties": {"commit": _REF, "message": {"type": "string"}}},
     "_fn": tool_freeze},
    {"name": "avcs_replay", "description": "Deterministically re-execute a crystallized recipe; optionally pipe each step to an executor command.",
     "inputSchema": {"type": "object", "properties": {
         "commit": _REF, "exec": {"type": "string", "description": "command to pipe each step JSON to"}}},
     "_fn": tool_replay},
    {"name": "avcs_rollback", "description": "Undo: restore the full prior state. Defaults to HEAD's parent. Reversible. Pass 'reason' to record WHY in the durable rollback ledger (e.g. an eval regression) — it shows up in `log --reasoning`.",
     "inputSchema": {"type": "object", "properties": {"ref": _REF,
         "reason": {"type": "string", "description": "why you rolled back (recorded in the ledger)"}}}, "_fn": tool_rollback},
    {"name": "avcs_branch", "description": "List branches, or create a live branch when 'name' is given.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}, "_fn": tool_branch},
    {"name": "avcs_checkout", "description": "Restore the working tree from a branch or commit.",
     "inputSchema": {"type": "object", "properties": {"ref": _REF}, "required": ["ref"]}, "_fn": tool_checkout},
    {"name": "avcs_runtime", "description": "Show your operational frame your runtime hides: token budget, dollar cost, context-window pressure, model routing, tool usage and subagent fan-out — reconstructed from the native session log.",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_runtime},
    {"name": "avcs_budget", "description": "How many tokens and dollars you have spent, and how much of your ceiling remains. Check before doing expensive work.",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_budget},
    {"name": "avcs_context", "description": "How full your context window is and how many times it was silently compacted (context you can no longer see).",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_context},
    {"name": "avcs_recall", "description": "Have I solved this before? Rank crystallized (frozen, deterministic) recipes whose goal matches — verified recipes (passed their eval) rank first. Replay a proven solution for ~$0 instead of re-deriving it. Check this FIRST.",
     "inputSchema": {"type": "object", "properties": {
         "goal": {"type": "string", "description": "goal to match (defaults to agent.json's goal)"},
         "limit": {"type": "integer"},
         "verified_only": {"type": "boolean", "description": "only recipes that passed their eval gate"}}}, "_fn": tool_recall},
    {"name": "avcs_eval", "description": "Run the eval declared in agent.json and record the pass/score for a commit. freeze requires a passing eval (the trust gate), so run this before freezing.",
     "inputSchema": {"type": "object", "properties": {"commit": _REF}}, "_fn": tool_eval},
    {"name": "avcs_merge", "description": "Three-way merge a branch into HEAD. Returns status: merged, fast_forward, up_to_date, or conflict.",
     "inputSchema": {"type": "object", "properties": {
         "branch": {"type": "string", "description": "branch name to merge into HEAD"},
         "reconcile": {"type": "string", "description": "command to pipe reconciliation bundle to"},
         "force": {"type": "boolean", "description": "commit even when conflicts exist"}},
         "required": ["branch"]}, "_fn": tool_merge},
    {"name": "avcs_price", "description": "Is my self-improvement loop working? Price-equation decomposition over the commit graph: how much of the trait change came from selecting between branches (Cov(w,z)) vs editing within a lineage (E[w·Δz]), plus the Eigen error-catastrophe verdict (degradation outrunning selection). trait = score | size | cost.",
     "inputSchema": {"type": "object", "properties": {
         "since": {**_REF, "description": "only decompose commits descended from this ref"},
         "trait": {"type": "string", "enum": ["score", "size", "cost"],
                   "description": "the trait to track (default: eval score)"}}}, "_fn": tool_price},
    {"name": "avcs_health", "description": "Evolution-health rollup: Price verdict + critical-slowing-down early warning (rising variance/autocorrelation in the eval-score series) + Muller's-ratchet load on long unmerged branches. Returns a flat warnings[] to act on.",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_health},
    {"name": "avcs_infobits", "description": "How many bits do my decisions actually carry? Estimates the decision channel from recorded traces: H(action) over tool selections and I(previous action; next action), the Kelly/Kussell-Leibler bound on the value of context. A low figure bounds what more retrieval can buy and justifies compressing context. (A lower-bound proxy — context = previous action — not a full I(context;action) measurement.)",
     "inputSchema": {"type": "object", "properties": {}}, "_fn": tool_infobits},
    {"name": "avcs_contain", "description": "Is shared-memory poisoning self-limiting? Branching-process test R0 = n·p (n downstream readers, p per-read escape probability) with n measured from subagents/swarm and p from the empirical failed-eval rate; returns whether corruption is contained and the verification rate needed to contain it. Override with fanout/prob.",
     "inputSchema": {"type": "object", "properties": {
         "fanout": {"type": "number", "description": "downstream readers n (default: measured)"},
         "prob": {"type": "number", "description": "per-read escape probability p (default: failed-eval rate)"}}}, "_fn": tool_contain},
]
_TOOL_FNS = {t["name"]: t["_fn"] for t in TOOLS}
_PUBLIC_TOOLS = [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]


# ----------------------------------------------------------- JSON-RPC layer
def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(message: dict):
    """Return a response dict, or None for notifications (no reply)."""
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        version = params.get("protocolVersion", PROTOCOL_VERSION)
        return _result(req_id, {"protocolVersion": version,
                                "capabilities": {"tools": {}},
                                "serverInfo": SERVER_INFO})
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": _PUBLIC_TOOLS})
    if method == "tools/call":
        name = params.get("name")
        fn = _TOOL_FNS.get(name)
        if fn is None:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            data = fn(params.get("arguments") or {})
            payload = {"ok": True, **data}
            is_error = False
        except RepoError as e:
            payload = {"ok": False, "error": {"code": e.code, "message": str(e)}}
            is_error = True
        except Exception as e:  # surface unexpected failures to the agent, don't crash
            payload = {"ok": False, "error": {"code": "INTERNAL", "message": str(e)}}
            is_error = True
        return _result(req_id, {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": is_error})

    if req_id is None:
        return None  # unknown notification
    return _error(req_id, -32601, f"method not found: {method}")


def main(argv=None):
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as e:
            out.write(json.dumps(_error(None, -32700, f"parse error: {e}")) + "\n")
            out.flush()
            continue
        response = handle(message)
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
