"""Command-line interface for agentvcs.

Designed to be driven by humans *and* by autonomous coding agents. Every command
accepts ``--json`` (or set ``AGENTVCS_JSON=1``) and then emits a single, parseable
JSON object on stdout — no spinners, no colors, no prose. Errors carry a stable
machine ``code`` (see docs/AGENT_MODE.md).

    agentvcs init                 create a repository (scaffolds agent.json + AGENTS.md)
    agentvcs commit -m "msg"      snapshot code + goal + models + trace
    agentvcs log                  show the evolution history
    agentvcs status               show working-tree changes per dimension
    agentvcs show [<commit>]      show one commit across all dimensions
    agentvcs diff [<a>] [<b>]     dimensional diff (defaults: parent..HEAD)
    agentvcs branch [<name>]      list branches, or create a live branch
    agentvcs checkout <ref>       restore the working tree from a branch/commit
    agentvcs rollback [<ref>]     undo: restore full prior state (the panic button)
    agentvcs freeze [<commit>]    crystallize a fluid commit into a deterministic recipe
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .crystallize import crystallize
from .diff import diff_commits
from .repository import Repository, RepoError

C_DIM, C_RST, C_B, C_Y, C_G, C_C, C_R = (
    "\033[2m", "\033[0m", "\033[1m", "\033[33m", "\033[32m", "\033[36m", "\033[31m")


def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"{code}{s}{C_RST}"


def _short(oid: str | None) -> str:
    return oid[:12] if oid else "-"


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _out(args, data: dict, human: str) -> None:
    """Emit a result as JSON (agent mode) or human text."""
    if args.json:
        print(json.dumps({"ok": True, "command": args.command, **data},
                         ensure_ascii=False))
    else:
        print(human)


# ----------------------------------------------------------------- commands
def cmd_init(args):
    repo = Repository.init(args.path)
    data = {"repository": str(repo.dir), "manifest": "agent.json", "agents_md": "AGENTS.md"}
    human = (f"Initialized empty agentvcs repository in {repo.dir}\n"
             f"Scaffolded {_color('agent.json', C_B)} (your goal/models/trace) and "
             f"{_color('AGENTS.md', C_B)} (agent operating manual).")
    _out(args, data, human)


def cmd_commit(args):
    repo = Repository.open()
    oid = repo.commit(args.message, author=args.author)
    commit = repo.objects.read_obj(oid)
    branch = repo.current_branch() or "detached"
    data = {"commit": oid, "branch": branch, "state": commit["state"],
            "message": args.message}
    human = (f"[{branch} {_short(oid)}] {_color(commit['state'], C_C)} {args.message}")
    _out(args, data, human)


def _commit_summary(repo, oid, commit):
    return {
        "commit": oid,
        "state": commit["state"],
        "timestamp": _iso(commit["timestamp"]),
        "message": commit["message"],
        "goal": repo.objects.read_obj(commit["goal"])["text"],
        "parents": commit.get("parents", []),
    }


def cmd_log(args):
    repo = Repository.open()
    history = repo.log()
    entries = [_commit_summary(repo, oid, c) for oid, c in history]
    if not entries:
        _out(args, {"commits": []}, "no commits yet")
        return
    lines = []
    for e in entries:
        badge = _color(e["state"], C_C if e["state"] == "fluid" else C_G)
        lines.append(f"{_color(_short(e['commit']), C_Y)} {badge} "
                     f"{_color(e['timestamp'], C_DIM)}  {e['message']}")
        if e["goal"]:
            lines.append(f"    {_color('goal:', C_DIM)} {e['goal'][:80]}")
    _out(args, {"commits": entries}, "\n".join(lines))


def _diff_human(d: dict) -> str:
    out = []
    code = d["code"]
    if code["added"] or code["removed"] or code["modified"]:
        out.append(_color("code", C_B))
        out += [f"  {_color('+ ' + p, C_G)}" for p in code["added"]]
        out += [f"  {_color('- ' + p, C_R)}" for p in code["removed"]]
        out += [f"  {_color('~ ' + p, C_Y)}" for p in code["modified"]]
    if d["goal"]:
        out.append(_color("goal", C_B))
        out.append(f"  from: {d['goal']['from']}")
        out.append(f"  to:   {d['goal']['to']}")
    if d["models"]:
        out.append(_color("models", C_B))
        out.append(f"  from: {d['models']['from']}")
        out.append(f"  to:   {d['models']['to']}")
    if d["trace"]:
        t = d["trace"]
        out.append(f"{_color('trace', C_B)} {t['from']} -> {t['to']} ({t['delta']:+d})")
    if d["state"]:
        out.append(f"{_color('state', C_B)} {d['state']['from']} -> {d['state']['to']}")
    return "\n".join(out) if out else _color("no changes", C_DIM)


def cmd_status(args):
    repo = Repository.open()
    head = repo.head_commit()
    branch = repo.current_branch() or "detached"
    # snapshot writes dimension objects so diff can read them; wrap in a throwaway
    snap = repo.snapshot(write=True)
    pending = repo.objects.write_obj({
        "type": "commit", "parents": [], "tree": snap.tree, "goal": snap.goal,
        "models": snap.models, "trace": snap.trace, "state": snap.state,
        "metrics": {}, "message": "(working tree)", "author": "", "timestamp": 0})
    d = diff_commits(repo, head, pending)
    data = {"branch": branch, "head": head, "diff": d}
    human = (f"On branch {_color(branch, C_B)}"
             + (f" at {_short(head)}" if head else " (no commits yet)")
             + "\nWorking tree vs HEAD:\n" + _diff_human(d))
    _out(args, data, human)


def cmd_show(args):
    repo = Repository.open()
    oid = repo._resolve(args.commit, expect="commit") if args.commit else repo.head_commit()
    if not oid:
        _out(args, {"commit": None}, "no commits yet")
        return
    commit = repo.objects.read_obj(oid)
    models = [repo.objects.read_obj(m) for m in commit["models"]]
    n_trace = len(repo.objects.read_obj(commit["trace"])["messages"]) if commit.get("trace") else 0
    data = {
        **_commit_summary(repo, oid, commit),
        "author": commit["author"],
        "models": [{"provider": m["provider"], "model": m["model"],
                    "version": m["version"], "params": m["params"]} for m in models],
        "trace_messages": n_trace,
        "metrics": commit.get("metrics", {}),
        "crystal": commit.get("crystal"),
    }
    lines = [
        _color(f"commit {oid}", C_Y),
        f"state:   {commit['state']}",
        f"author:  {commit['author']}",
        f"date:    {_iso(commit['timestamp'])}",
        f"parents: {', '.join(_short(p) for p in commit['parents']) or '(root)'}",
        f"message: {commit['message']}",
        f"\n{_color('goal', C_B)}: {data['goal']}",
        _color("models", C_B) + ":",
    ]
    lines += [f"  - {m['provider']}/{m['model']} params={m['params']}" for m in models]
    lines.append(f"{_color('trace', C_B)}: {n_trace} messages")
    if commit.get("crystal"):
        lines.append(f"{_color('crystal', C_B)}: {_short(commit['crystal'])} (deterministic recipe)")
    _out(args, data, "\n".join(lines))


def cmd_diff(args):
    repo = Repository.open()
    if args.a and args.b:
        a = repo._resolve(args.a, expect="commit")
        b = repo._resolve(args.b, expect="commit")
    elif args.a:
        b = repo.head_commit()
        a = repo._resolve(args.a, expect="commit")
    else:
        b = repo.head_commit()
        if not b:
            _out(args, {"diff": None}, "no commits yet")
            return
        a = (repo.objects.read_obj(b)["parents"] or [None])[0]
    d = diff_commits(repo, a, b)
    data = {"a": a, "b": b, "diff": d}
    human = f"{_color(_short(a) + '..' + _short(b), C_DIM)}\n" + _diff_human(d)
    _out(args, data, human)


def cmd_branch(args):
    repo = Repository.open()
    if not args.name:
        current = repo.current_branch()
        branches = repo.branches()
        data = {"current": current,
                "branches": [{"name": n, "commit": o} for n, o in sorted(branches.items())]}
        lines = [f"{'* ' if n == current else '  '}{n} {_color(_short(o), C_DIM)}"
                 for n, o in sorted(branches.items())]
        _out(args, data, "\n".join(lines))
        return
    oid = repo.branch(args.name)
    _out(args, {"branch": args.name, "commit": oid},
         f"Created live branch {_color(args.name, C_B)} at {_short(oid)}")


def cmd_checkout(args):
    repo = Repository.open()
    oid = repo.checkout(args.ref)
    _out(args, {"ref": args.ref, "commit": oid},
         f"Switched to {_color(args.ref, C_B)} ({_short(oid)})")


def cmd_rollback(args):
    repo = Repository.open()
    result = repo.rollback(args.ref)
    human = (f"Rolled back to {_color(_short(result['restored_to']), C_G)} "
             f"(was {_short(result['previous_head'])})\n"
             f"  goal:  {result['goal']}\n"
             f"  undo this with: agentvcs checkout {_short(result['previous_head'])}")
    _out(args, result, human)


def cmd_freeze(args):
    repo = Repository.open()
    new_oid, artifact = crystallize(repo, args.commit, message=args.message)
    new = repo.objects.read_obj(new_oid)
    data = {"commit": new_oid, "source": new["parents"][0], "state": "crystallized",
            "recipe_path": str(artifact)}
    human = (f"Crystallized -> {_color(_short(new_oid), C_G)}\n"
             f"Deterministic recipe written to {_color(str(artifact), C_B)}")
    _out(args, data, human)


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        help="machine-readable JSON output (for agents)")
    common.add_argument("-C", "--repo", dest="repo", default=None, metavar="DIR",
                        help="run as if started in DIR (robust for agents whose "
                             "shell cwd is not sticky; created by init if absent)")

    p = argparse.ArgumentParser(prog="agentvcs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"agentvcs {__version__}")
    # also accept `agentvcs -C DIR <cmd>` (git-style, before the subcommand)
    p.add_argument("-C", "--repo", dest="repo_global", default=None,
                   metavar="DIR", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    sp = add("init", help="create a repository")
    sp.add_argument("path", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    sp = add("commit", help="snapshot all dimensions")
    sp.add_argument("-m", "--message", required=True)
    sp.add_argument("--author", default="agent")
    sp.set_defaults(func=cmd_commit)

    add("log", help="show evolution history").set_defaults(func=cmd_log)
    add("status", help="working-tree changes per dimension").set_defaults(func=cmd_status)

    sp = add("show", help="show one commit across all dimensions")
    sp.add_argument("commit", nargs="?")
    sp.set_defaults(func=cmd_show)

    sp = add("diff", help="dimensional diff (default parent..HEAD)")
    sp.add_argument("a", nargs="?")
    sp.add_argument("b", nargs="?")
    sp.set_defaults(func=cmd_diff)

    sp = add("branch", help="list or create live branches")
    sp.add_argument("name", nargs="?")
    sp.set_defaults(func=cmd_branch)

    sp = add("checkout", help="restore working tree from a ref")
    sp.add_argument("ref")
    sp.set_defaults(func=cmd_checkout)

    sp = add("rollback", help="undo: restore full prior state (default: HEAD's parent)")
    sp.add_argument("ref", nargs="?")
    sp.set_defaults(func=cmd_rollback)

    sp = add("freeze", help="crystallize a fluid commit (alias: crystallize)")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.set_defaults(func=cmd_freeze)

    sp = add("crystallize", help=argparse.SUPPRESS)
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.set_defaults(func=cmd_freeze)

    return p


def _apply_repo_dir(args):
    """Honor -C/--repo: behave as if the CLI were started in that directory.
    Mirrors `git -C`. For `init`, the directory is created if missing."""
    target = getattr(args, "repo", None) or getattr(args, "repo_global", None)
    if not target:
        return
    path = Path(target)
    if not path.is_dir():
        if args.command == "init":
            path.mkdir(parents=True, exist_ok=True)
        else:
            raise RepoError(f"directory not found: {target}", code="BAD_DIR")
    os.chdir(path)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "json", False) and os.environ.get("AGENTVCS_JSON"):
        args.json = True
    try:
        _apply_repo_dir(args)
        args.func(args)
    except RepoError as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "command": args.command,
                              "error": {"code": e.code, "message": str(e)}}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
