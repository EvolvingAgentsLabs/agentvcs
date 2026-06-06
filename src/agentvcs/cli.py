"""Command-line interface for agentvcs.

    agentvcs init                 create a repository (writes a template agent.json)
    agentvcs commit -m "msg"      snapshot code + goal + models + trace
    agentvcs log                  show the evolution history
    agentvcs status               show working-tree changes per dimension
    agentvcs show [<commit>]      show one commit across all dimensions
    agentvcs diff [<a>] [<b>]     dimensional diff (defaults: parent..HEAD)
    agentvcs branch [<name>]      list branches, or create a live branch
    agentvcs checkout <ref>       restore the working tree from a branch/commit
    agentvcs freeze [<commit>]    crystallize a fluid commit into a deterministic recipe
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .crystallize import crystallize
from .diff import diff_commits
from .repository import Repository, RepoError

C_DIM, C_RST, C_B, C_Y, C_G, C_C = "\033[2m", "\033[0m", "\033[1m", "\033[33m", "\033[32m", "\033[36m"


def _short(oid: str | None) -> str:
    return oid[:12] if oid else "-"


def _ts(commit: dict) -> str:
    return datetime.fromtimestamp(commit["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _state_badge(state: str) -> str:
    color = C_C if state == "fluid" else C_G
    return f"{color}{state}{C_RST}"


def cmd_init(args):
    repo = Repository.init(args.path)
    print(f"Initialized empty agentvcs repository in {repo.dir}")
    print(f"Edit {C_B}agent.json{C_RST} to declare your goal, models and trace, then `agentvcs commit`.")


def cmd_commit(args):
    repo = Repository.open()
    oid = repo.commit(args.message, author=args.author)
    commit = repo.objects.read_obj(oid)
    print(f"[{repo.current_branch() or 'detached'} {_short(oid)}] {_state_badge(commit['state'])} {args.message}")


def cmd_log(args):
    repo = Repository.open()
    history = repo.log()
    if not history:
        print("no commits yet")
        return
    for oid, commit in history:
        goal = repo.objects.read_obj(commit["goal"])["text"]
        print(f"{C_Y}{_short(oid)}{C_RST} {_state_badge(commit['state'])} {C_DIM}{_ts(commit)}{C_RST}  {commit['message']}")
        if goal:
            print(f"    {C_DIM}goal:{C_RST} {goal[:80]}")


def _print_diff(d: dict):
    code = d["code"]
    if code["added"] or code["removed"] or code["modified"]:
        print(f"  {C_B}code{C_RST}")
        for p in code["added"]:
            print(f"    {C_G}+ {p}{C_RST}")
        for p in code["removed"]:
            print(f"    \033[31m- {p}{C_RST}")
        for p in code["modified"]:
            print(f"    {C_Y}~ {p}{C_RST}")
    if d["goal"]:
        print(f"  {C_B}goal{C_RST}\n    {C_DIM}from:{C_RST} {d['goal']['from']}\n    {C_DIM}to:  {C_RST} {d['goal']['to']}")
    if d["models"]:
        print(f"  {C_B}models{C_RST}\n    {C_DIM}from:{C_RST} {d['models']['from']}\n    {C_DIM}to:  {C_RST} {d['models']['to']}")
    if d["trace"]:
        t = d["trace"]
        print(f"  {C_B}trace{C_RST} {t['from']} -> {t['to']} messages ({t['delta']:+d})")
    if d["state"]:
        print(f"  {C_B}state{C_RST} {d['state']['from']} -> {_state_badge(d['state']['to'])}")
    if not any([code["added"], code["removed"], code["modified"], d["goal"], d["models"], d["trace"], d["state"]]):
        print(f"  {C_DIM}no changes{C_RST}")


def cmd_status(args):
    repo = Repository.open()
    head = repo.head_commit()
    branch = repo.current_branch() or "detached"
    print(f"On branch {C_B}{branch}{C_RST}" + (f" at {_short(head)}" if head else " (no commits yet)"))
    # snapshot writes the dimension objects so diff can read them, then we wrap
    # them in a throwaway commit representing the working tree.
    snap = repo.snapshot(write=True)
    pending = repo.objects.write_obj({
        "type": "commit", "parents": [], "tree": snap.tree, "goal": snap.goal,
        "models": snap.models, "trace": snap.trace, "state": snap.state,
        "metrics": {}, "message": "(working tree)", "author": "", "timestamp": 0,
    })
    print("Working tree vs HEAD:")
    _print_diff(diff_commits(repo, head, pending))


def cmd_show(args):
    repo = Repository.open()
    oid = args.commit or repo.head_commit()
    if not oid:
        print("no commits yet")
        return
    commit = repo.objects.read_obj(oid)
    goal = repo.objects.read_obj(commit["goal"])["text"]
    print(f"{C_Y}commit {oid}{C_RST}")
    print(f"state:   {_state_badge(commit['state'])}")
    print(f"author:  {commit['author']}")
    print(f"date:    {_ts(commit)}")
    print(f"parents: {', '.join(_short(p) for p in commit['parents']) or '(root)'}")
    print(f"message: {commit['message']}")
    print(f"\n{C_B}goal{C_RST}: {goal}")
    print(f"{C_B}models{C_RST}:")
    for moid in commit["models"]:
        m = repo.objects.read_obj(moid)
        print(f"  - {m['provider']}/{m['model']} params={m['params']}")
    n = len(repo.objects.read_obj(commit["trace"])["messages"]) if commit.get("trace") else 0
    print(f"{C_B}trace{C_RST}: {n} messages")
    if commit.get("crystal"):
        print(f"{C_B}crystal{C_RST}: {_short(commit['crystal'])} (deterministic recipe)")


def cmd_diff(args):
    repo = Repository.open()
    if args.a and args.b:
        a, b = args.a, args.b
    elif args.a:
        b = repo.head_commit(); a = args.a
    else:
        b = repo.head_commit()
        commit = repo.objects.read_obj(b)
        a = (commit["parents"] or [None])[0]
    print(f"{C_DIM}{_short(a)}..{_short(b)}{C_RST}")
    _print_diff(diff_commits(repo, a, b))


def cmd_branch(args):
    repo = Repository.open()
    if not args.name:
        current = repo.current_branch()
        for name, oid in sorted(repo.branches().items()):
            mark = "* " if name == current else "  "
            print(f"{mark}{name} {C_DIM}{_short(oid)}{C_RST}")
        return
    oid = repo.branch(args.name)
    print(f"Created live branch {C_B}{args.name}{C_RST} at {_short(oid)}")


def cmd_checkout(args):
    repo = Repository.open()
    oid = repo.checkout(args.ref)
    print(f"Switched to {C_B}{args.ref}{C_RST} ({_short(oid)})")


def cmd_freeze(args):
    repo = Repository.open()
    new_oid, artifact = crystallize(repo, args.commit, message=args.message)
    print(f"Crystallized -> {C_G}{_short(new_oid)}{C_RST}")
    print(f"Deterministic recipe written to {C_B}{artifact}{C_RST}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentvcs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a repository")
    sp.add_argument("path", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("commit", help="snapshot all dimensions")
    sp.add_argument("-m", "--message", required=True)
    sp.add_argument("--author", default="agent")
    sp.set_defaults(func=cmd_commit)

    sp = sub.add_parser("log", help="show evolution history")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("status", help="working-tree changes per dimension")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("show", help="show one commit across all dimensions")
    sp.add_argument("commit", nargs="?")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("diff", help="dimensional diff (default parent..HEAD)")
    sp.add_argument("a", nargs="?")
    sp.add_argument("b", nargs="?")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("branch", help="list or create live branches")
    sp.add_argument("name", nargs="?")
    sp.set_defaults(func=cmd_branch)

    sp = sub.add_parser("checkout", help="restore working tree from a ref")
    sp.add_argument("ref")
    sp.set_defaults(func=cmd_checkout)

    sp = sub.add_parser("freeze", help="crystallize a fluid commit (alias: crystallize)")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.set_defaults(func=cmd_freeze)

    sp = sub.add_parser("crystallize", help=argparse.SUPPRESS)
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.set_defaults(func=cmd_freeze)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except RepoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
