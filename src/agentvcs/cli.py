"""Command-line interface for agentvcs.

Designed to be driven by humans *and* by autonomous coding agents. Every command
accepts ``--json`` (or set ``AGENTVCS_JSON=1``) and then emits a single, parseable
JSON object on stdout — no spinners, no colors, no prose. Errors carry a stable
machine ``code`` (see docs/AGENT_MODE.md).

    agentvcs new <dir>            scaffold a new agent project pre-wired with agentvcs
    agentvcs init                 create a repository (scaffolds agent.json + AGENTS.md)
    agentvcs commit -m "msg"      snapshot code + goal + models + trace
    agentvcs log                  show the evolution history
    agentvcs status               show working-tree changes per dimension
    agentvcs show [<commit>]      show one commit across all dimensions (--trace renders the conversation)
    agentvcs trace                show the current trace source (file or auto-discovered session)
    agentvcs diff [<a>] [<b>]     dimensional diff (defaults: parent..HEAD)
    agentvcs branch [<name>]      list branches, or create a live branch
    agentvcs checkout <ref>       restore the working tree from a branch/commit
    agentvcs rollback [<ref>]     undo: restore full prior state (the panic button)
    agentvcs freeze [<commit>]    crystallize a fluid commit into a deterministic recipe
    agentvcs replay [<commit>]    re-execute a crystallized recipe deterministically
    agentvcs ui                   serve a local web dashboard to visualize the evolution
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, views
from .crystallize import crystallize
from .diff import diff_commits
from .merge import merge
from .recall import recall
from .replay import replay
from .repository import Repository, RepoError
from .scaffold import scaffold

C_DIM, C_RST, C_B, C_Y, C_G, C_C, C_R = (
    "\033[2m", "\033[0m", "\033[1m", "\033[33m", "\033[32m", "\033[36m", "\033[31m")


def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"{code}{s}{C_RST}"


def _short(oid: str | None) -> str:
    return oid[:12] if oid else "-"


_iso = views.iso


def _build_manifest(args) -> str | None:
    """Assemble agent.json for the requested runtime + mode. Returns None to let
    the repository scaffold its default file-trace template."""
    runtime_mode = getattr(args, "runtime", False)
    if not (args.claude_code or args.qwen_code or runtime_mode):
        return None
    m: dict = {"goal": "Describe the high-level objective this agent fleet is pursuing.",
               "models": [], "state": "fluid", "metrics": {}}
    if args.claude_code:
        m["models"] = [{"provider": "anthropic", "auto": True}]
        m["trace"] = {"provider": "claude-code", "auto": True}
    elif args.qwen_code:
        m["models"] = [{"provider": "qwen", "model": "qwen3-coder-plus"}]
        m["trace"] = {"provider": "qwen-code", "auto": True, "model": "qwen3-coder-plus"}
    else:
        m["models"] = [{"provider": "anthropic", "model": "claude-opus-4-8",
                        "params": {"temperature": 1.0}}]
        m["trace"] = "traces/run.jsonl"
    if runtime_mode:
        m["mode"] = "runtime"
        m["budget"] = {"ceiling_usd": None}
    return json.dumps(m, indent=2) + "\n"


def _trace_provider(args) -> str | None:
    if args.claude_code:
        return "claude-code"
    if args.qwen_code:
        return "qwen-code"
    return None


def _open(args) -> Repository:
    """Open the repo, honoring a ``--mode`` override for this invocation."""
    repo = Repository.open()
    if getattr(args, "mode", None):
        repo._mode_override = args.mode
    return repo


def _render_content(content) -> list:
    """Flatten a message's content (string or Anthropic block list) to lines."""
    if isinstance(content, str):
        return content.splitlines() or [""]
    if not isinstance(content, list):
        return [json.dumps(content, ensure_ascii=False)]
    lines = []
    for b in content:
        if not isinstance(b, dict):
            lines.append(str(b)); continue
        t = b.get("type")
        if t == "text":
            lines += (b.get("text") or "").splitlines()
        elif t == "thinking":
            lines.append(_color("[thinking] ", C_DIM) + (b.get("thinking") or b.get("text") or "").strip()[:300])
        elif t == "tool_use":
            lines.append(_color(f"[tool_use {b.get('name', '?')}] ", C_C)
                         + json.dumps(b.get("input", {}), ensure_ascii=False)[:300])
        elif t == "tool_result":
            inner = b.get("content")
            text = inner if isinstance(inner, str) else " ".join(
                x.get("text", "") for x in inner if isinstance(x, dict)) if isinstance(inner, list) else json.dumps(inner)
            lines.append(_color("[tool_result] ", C_G) + (text or "").strip()[:300])
        else:
            lines.append(f"[{t}]")
    return lines or [""]


def _render_trace(messages: list) -> str:
    out = []
    for m in messages:
        out.append(_color(f"  {m.get('role', '?')}:", C_B)
                   + (_color(f"  ({m['model']})", C_DIM) if m.get("model") else ""))
        out += ["    " + l for l in _render_content(m.get("content"))]
    return "\n".join(out) if out else _color("  (empty trace)", C_DIM)


def _out(args, data: dict, human: str) -> None:
    """Emit a result as JSON (agent mode) or human text."""
    if args.json:
        print(json.dumps({"ok": True, "command": args.command, **data},
                         ensure_ascii=False))
    else:
        print(human)


# ----------------------------------------------------------------- commands
def cmd_new(args):
    result = scaffold(args.path, claude_code=args.claude_code)
    human = (f"Scaffolded an agentvcs-wired agent project in {_color(result['path'], C_B)}\n"
             f"  files: {', '.join(result['files'])}\n"
             f"  first commit: {_short(result['commit'])}\n"
             f"Open it with a coding agent and just describe what to build — the\n"
             f"project's AGENTS.md and the agentvcs skill take it from there.")
    _out(args, result, human)


def cmd_init(args):
    repo = Repository.init(args.path, manifest=_build_manifest(args))
    provider = _trace_provider(args)
    mode = "runtime" if getattr(args, "runtime", False) else "vcs"
    data = {"repository": str(repo.dir), "manifest": "agent.json", "agents_md": "AGENTS.md",
            "trace_provider": provider, "mode": mode}
    extra = ""
    if provider:
        extra += (f"\nWired the trace to the live {_color(provider, C_C)} session "
                  "— just commit; no trace file to maintain.")
    if mode == "runtime":
        extra += (f"\nMode {_color('runtime', C_C)}: every commit also captures the "
                  "operational frame your runtime hides — budget, context pressure, "
                  "model routing, tools, subagents. See `agentvcs budget`/`context`/`runtime`.")
    human = (f"Initialized empty agentvcs repository in {repo.dir}\n"
             f"Scaffolded {_color('agent.json', C_B)} (your goal/models/trace) and "
             f"{_color('AGENTS.md', C_B)} (agent operating manual)." + extra)
    _out(args, data, human)


def cmd_trace(args):
    repo = Repository.open()
    info = repo.trace_info()
    if info["kind"] == "none":
        _out(args, info, "no trace declared in agent.json")
        return
    if info["kind"] == "path":
        human = (f"trace source: {_color('file', C_B)} {info['path']}\n"
                 f"  exists: {info['exists']}  messages: {info['messages']}")
    else:  # provider
        tr = info.get("transcript") or "(not found yet)"
        human = (f"trace source: {_color('provider', C_B)} {info.get('provider')}\n"
                 f"  transcript: {tr}\n"
                 f"  messages:   {info.get('messages', 0)}"
                 + (f"   model: {info['model']}" if info.get("model") else ""))
    _out(args, info, human)


def cmd_commit(args):
    repo = _open(args)
    oid = repo.commit(args.message, author=args.author)
    commit = repo.objects.read_obj(oid)
    branch = repo.current_branch() or "detached"
    data = {"commit": oid, "branch": branch, "state": commit["state"],
            "message": args.message}
    human = f"[{branch} {_short(oid)}] {_color(commit['state'], C_C)} {args.message}"
    if commit.get("runtime"):
        b = views._runtime_obj(repo, commit)["budget"]
        cost = f"${b['cost_usd']:.4f}" if b["cost_usd"] is not None else "?"
        human += (f"\n  runtime: {b['tokens_total']} tok / {cost}"
                  + (f"  ({_color('OVER BUDGET', C_R)})" if b["over_budget"] else ""))
    _out(args, data, human)


def _commit_summary(repo, oid, commit):
    return views.commit_summary(repo, oid, commit)


def cmd_log(args):
    repo = Repository.open()
    if getattr(args, "reasoning", False):
        _cmd_log_reasoning(args, repo)
        return
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


def _cmd_log_reasoning(args, repo):
    """Decision-aware log: goal transitions, eval verdicts, rollback events."""
    import subprocess, shlex, json as _json

    # Collect history
    head = repo.head_commit()
    if not head:
        _out(args, {"ledger": []}, "no commits yet")
        return

    # Walk history; with --all follow merge second-parents too
    seen = set()
    queue = [head]
    ordered = []
    while queue:
        oid = queue.pop(0)
        if oid in seen:
            continue
        seen.add(oid)
        commit = repo.objects.read_obj(oid)
        ordered.append((oid, commit))
        parents = commit.get("parents") or []
        if parents:
            queue.append(parents[0])
        if getattr(args, "all", False) and len(parents) > 1:
            for p in parents[1:]:
                if p not in seen:
                    queue.append(p)

    # Build rollback index: keyed by "to" (commit restored to, in history)
    # and also track unanchored ones (neither from nor to is in history)
    all_rollbacks = repo.read_rollbacks()
    rollbacks_by_to = {}
    for rb in all_rollbacks:
        rollbacks_by_to.setdefault(rb["to"], []).append(rb)

    explain_cmd = getattr(args, "explain", None)
    ledger = []

    for oid, commit in ordered:
        parents = commit.get("parents") or []
        parent_oid = parents[0] if parents else None

        # Goal transition
        goal_text = repo.objects.read_obj(commit["goal"])["text"] if commit.get("goal") else ""
        parent_goal = ""
        if parent_oid:
            try:
                pc = repo.objects.read_obj(parent_oid)
                parent_goal = repo.objects.read_obj(pc["goal"])["text"] if pc.get("goal") else ""
            except Exception:
                pass
        goal_delta = goal_text if goal_text != parent_goal else None

        # Eval verdict
        ev = repo.read_eval(oid)

        # State info
        state = commit.get("state", "fluid")
        is_crystallized = state == "crystallized"
        is_merge = len(parents) == 2

        # Decision text (tier-1: goal delta; tier-2: last assistant message)
        decision = goal_delta or ""
        if not decision and commit.get("trace"):
            try:
                msgs = repo.objects.read_obj(commit["trace"])["messages"]
                for m in reversed(msgs):
                    if m.get("role") == "assistant":
                        content = m.get("content", "")
                        if isinstance(content, list):
                            for blk in content:
                                if isinstance(blk, dict) and blk.get("type") == "text":
                                    content = blk.get("text", "")
                                    break
                        if isinstance(content, str) and content.strip():
                            decision = content.strip()[:120]
                            break
            except Exception:
                pass

        # Optional --explain CMD
        why = ""
        if explain_cmd:
            try:
                thinking_msgs = []
                if commit.get("trace"):
                    msgs = repo.objects.read_obj(commit["trace"])["messages"]
                    thinking_msgs = [m for m in msgs
                                     if m.get("role") in ("assistant", "thinking")]
                payload = _json.dumps({"commit": oid, "messages": thinking_msgs},
                                      ensure_ascii=False)
                cmd_parts = shlex.split(explain_cmd)
                proc = subprocess.run(cmd_parts, input=payload, capture_output=True,
                                      text=True, timeout=30)
                if proc.returncode == 0 and proc.stdout.strip():
                    parsed = _json.loads(proc.stdout.strip())
                    decision = parsed.get("decision", decision)
                    why = parsed.get("why", "")
            except Exception:
                pass

        entry = {
            "commit": oid,
            "state": state,
            "crystallized": is_crystallized,
            "merge": is_merge,
            "timestamp": commit.get("timestamp", 0),
            "message": commit.get("message", ""),
            "goal": goal_text,
            "goal_delta": goal_delta,
            "decision": decision,
            "why": why,
            "eval": _eval_summary_for_reasoning(ev),
        }
        ledger.append(entry)

        # Interleave rollback events (keyed by "to" = the commit restored to)
        for rb in rollbacks_by_to.get(oid, []):
            ledger.append({
                "type": "rollback",
                "from": rb["from"],
                "to": rb["to"],
                "timestamp": rb.get("timestamp", 0),
                "reason": rb.get("reason", ""),
            })

    # Append rollbacks whose "to" commit was not in the history walk
    # (e.g. after two successive rollbacks, the intermediate commit is gone)
    history_oids = {e["commit"] for e in ledger if e.get("type") != "rollback"}
    for rb in all_rollbacks:
        if rb["to"] not in history_oids:
            # Check if already added (anchored to a history commit)
            already = any(
                e.get("type") == "rollback" and e.get("from") == rb["from"]
                for e in ledger
            )
            if not already:
                ledger.append({
                    "type": "rollback",
                    "from": rb["from"],
                    "to": rb["to"],
                    "timestamp": rb.get("timestamp", 0),
                    "reason": rb.get("reason", ""),
                })

    if args.json:
        import json as _json2
        print(_json2.dumps({"ok": True, "command": "log", "ledger": ledger},
                           ensure_ascii=False))
        return

    # Human output
    lines = []
    for entry in ledger:
        if entry.get("type") == "rollback":
            lines.append(_color("  ↩ ROLLBACK OCCURRED HERE", C_R))
            lines.append(f"    from: {_short(entry['from'])}  to: {_short(entry['to'])}")
            lines.append(f"    reason: {entry.get('reason', '')[:80]}")
            continue
        badges = []
        if entry["crystallized"]:
            badges.append(_color("[crystallized]", C_G))
        if entry["merge"]:
            badges.append(_color("[merge]", C_C))
        badge_str = " ".join(badges)
        lines.append(f"commit {_color(_short(entry['commit']), C_Y)} {badge_str}")
        lines.append(f"  Goal:     {entry['goal'][:80]}")
        if entry["decision"]:
            lines.append(f"  Decision: {entry['decision'][:100]}")
        if entry["why"]:
            lines.append(f"  Why:      {entry['why'][:100]}")
        ev = entry.get("eval")
        if ev:
            if ev.get("ok"):
                proof = _color(f"✓ Passed '{ev.get('command','')}' (score {ev.get('score',0)})", C_G)
            else:
                proof = _color(f"✗ Failed '{ev.get('command','')}' (score {ev.get('score',0)})", C_R)
            lines.append(f"  Proof:    {proof}")
        lines.append("")
    _out(args, {"ledger": ledger}, "\n".join(lines))


def _eval_summary_for_reasoning(ev):
    if not ev:
        return None
    return {"ok": ev.get("ok"), "passed": ev.get("passed"), "total": ev.get("total"),
            "score": ev.get("score"), "command": ev.get("command")}


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
    messages = repo.objects.read_obj(commit["trace"])["messages"] if commit.get("trace") else []
    n_trace = len(messages)
    data = views.commit_view(repo, oid, include_trace=args.trace)
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
    if args.trace and messages:
        lines.append(_render_trace(messages))
    if commit.get("crystal"):
        lines.append(f"{_color('crystal', C_B)}: {_short(commit['crystal'])} (deterministic recipe)")
    if data.get("eval"):
        ev = data["eval"]
        verdict = _color("✓ passed", C_G) if ev["ok"] else _color("✗ failed", C_R)
        lines.append(f"{_color('eval', C_B)}: {verdict} {ev['passed']}/{ev['total']} "
                     f"score {ev['score']} ($ {ev['command']})")
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


def _step_label(step):
    if isinstance(step, dict) and "role" in step and "content" in step:
        return f"{step['role']}: {step['content']}"
    return json.dumps(step, ensure_ascii=False)


def cmd_replay(args):
    repo = Repository.open()
    result = replay(repo, args.commit, executor=args.exec)
    lines = [f"replay {_short(result['commit'])} {_color('[crystallized]', C_G)}",
             f"goal: {result['goal']}", _color("models", C_B) + ":"]
    lines += [f"  - {m['provider']}/{m['model']} params={m['params']}" for m in result["models"]]
    lines.append(_color(f"steps ({len(result['steps'])})", C_B) + ":")
    for s in result["steps"]:
        lines.append(f"  [{s['index']}] {_step_label(s['step'])}")
        if result["executed"]:
            tag = C_G if s.get("exit_code") == 0 else C_R
            lines.append(f"      {_color('->', tag)} exit={s.get('exit_code')} {s.get('output','').strip()[:200]}")
    _out(args, result, "\n".join(lines))


def _fmt_usd(v) -> str:
    return f"${v:.4f}" if isinstance(v, (int, float)) else "—"


def cmd_runtime(args):
    """The full operational frame your closed runtime never shows you."""
    repo = _open(args)
    frame = repo.runtime_frame()
    b, c = frame["budget"], frame["context"]
    lines = [_color("runtime frame", C_B) + _color("  (what your runtime hides)", C_DIM),
             f"  turns:     {frame['turns']}",
             f"  budget:    {b['tokens_total']} tok  "
             f"(in {b['tokens_in']} / out {b['tokens_out']})  {_fmt_usd(b['cost_usd'])}"
             + (f" / ceiling {_fmt_usd(b['ceiling_usd'])}" if b['ceiling_usd'] is not None else ""),
             f"  context:   {c['used'] or '?'}/{c['window'] or '?'} tok"
             + (f"  ({c['pct']}%)" if c['pct'] is not None else "")
             + f"  compactions={c['compactions']}"]
    if frame["models"]:
        lines.append(_color("  model routing:", C_B))
        for m in frame["models"]:
            lines.append(f"    {m['model']}: {m['turns']} turns, "
                         f"{m['tokens_in']}+{m['tokens_out']} tok, {_fmt_usd(m['cost_usd'])}")
    if frame["tools"]:
        lines.append("  tools:     " + ", ".join(f"{t['name']}×{t['count']}" for t in frame["tools"]))
    if frame["subagents"]:
        lines.append("  subagents: " + ", ".join(f"{s['type']}×{s['count']}" for s in frame["subagents"]))
    _out(args, {"runtime": frame}, "\n".join(lines))


def cmd_budget(args):
    """Token + dollar accounting — the number the runtime keeps to itself."""
    repo = _open(args)
    b = repo.runtime_frame()["budget"]
    data = {"budget": b}
    over = _color("  OVER BUDGET", C_R) if b["over_budget"] else ""
    human = (f"{_color('budget', C_B)}\n"
             f"  tokens:    {b['tokens_total']} (in {b['tokens_in']} / out {b['tokens_out']})\n"
             f"  cost:      {_fmt_usd(b['cost_usd'])}\n"
             f"  ceiling:   {_fmt_usd(b['ceiling_usd']) if b['ceiling_usd'] is not None else 'none set'}\n"
             f"  remaining: {_fmt_usd(b['remaining_usd']) if b['remaining_usd'] is not None else '—'}{over}")
    _out(args, data, human)


def cmd_context(args):
    """Context-window pressure + how often the runtime silently compacted."""
    repo = _open(args)
    c = repo.runtime_frame()["context"]
    data = {"context": c}
    bar = ""
    if c["pct"] is not None:
        filled = int(c["pct"] / 5)
        bar = "  [" + "█" * filled + "·" * (20 - filled) + f"] {c['pct']}%"
    human = (f"{_color('context window', C_B)}\n"
             f"  used:        {c['used'] or '?'} / {c['window'] or '?'} tok{bar}\n"
             f"  compactions: {c['compactions']}  "
             + _color("(context the runtime silently dropped)", C_DIM))
    _out(args, data, human)


def cmd_recall(args):
    """Have I solved this before? Rank frozen recipes to replay for ~$0."""
    repo = _open(args)
    query = args.goal or repo.read_manifest().get("goal", "")
    hits = recall(repo, query, limit=args.limit, min_score=0.01,
                  verified_only=getattr(args, "verified_only", False))
    data = {"query": query, "hits": hits}
    if not hits:
        _out(args, data, f"no crystallized recipe matches {_color(query[:60], C_B)} "
                         "— this is new work, no cache hit")
        return
    lines = [f"{_color('recall', C_B)} for: {query[:70]}"]
    for h in hits:
        sid = _color(_short(h["commit"]), C_Y)
        score = _color("score %.2f" % h["score"], C_G)
        trust = (_color("✓verified", C_G) if h.get("verified")
                 else _color("unverified", C_DIM))
        lines.append(f"  {sid} {score} {trust}  {h['goal'][:60]}")
    lines.append(_color("  -> replay the top hit: agentvcs replay "
                        + _short(hits[0]["commit"]), C_DIM))
    _out(args, data, "\n".join(lines))


def cmd_watch(args):
    """Live, in-terminal runtime feedback (like a runtime status panel, plus the
    budget/context/recall feedback agentvcs adds)."""
    from . import monitor
    repo = _open(args)
    if args.once:
        frame = repo.runtime_frame()
        if args.json:
            from .recall import recall as _recall
            goal = repo.read_manifest().get("goal", "")
            _out(args, {"runtime": frame,
                        "recall": _recall(repo, goal, min_score=0.1) if goal else []},
                 monitor.render_panel(repo, color=sys.stdout.isatty(), width=args.width))
        else:
            print(monitor.render_panel(repo, color=sys.stdout.isatty(), width=args.width), end="")
        return
    monitor.watch(repo, interval=args.interval,
                  color=sys.stdout.isatty(), width=args.width)


def cmd_statusline(args):
    """Emit a single compact line for your runtime's own status line. Drains (and
    ignores) any session JSON your runtime pipes in on stdin — non-blocking, so a
    status line can never hang waiting on it."""
    from . import monitor
    if not sys.stdin.isatty():
        try:
            import select
            if select.select([sys.stdin], [], [], 0.25)[0]:
                sys.stdin.read()
        except Exception:
            pass  # no select (e.g. Windows) — just skip the drain
    repo = _open(args)
    print(monitor.statusline(repo, color=not args.no_color and sys.stdout.isatty()))


def cmd_ui(args):
    from .ui import serve
    repo = Repository.open()

    def announce(url: str):
        port = int(url.rsplit(":", 1)[1])
        host = url.split("://", 1)[1].rsplit(":", 1)[0]
        if args.json:
            print(json.dumps({"ok": True, "command": "ui", "url": url,
                              "host": host, "port": port}, ensure_ascii=False),
                  flush=True)
        else:
            print(f"agentvcs dashboard serving {_color(url, C_B)}  "
                  f"{_color('(Ctrl-C to stop)', C_DIM)}", flush=True)

    serve(repo, host=args.host, port=args.port,
          open_browser=not args.no_open, on_ready=announce)


def cmd_eval(args):
    from .eval import run_eval
    repo = _open(args)
    r = run_eval(repo, args.commit)
    data = {"commit": r["commit"], "passing": r["ok"], "passed": r["passed"],
            "total": r["total"], "score": r["score"], "command": r["command"]}
    verdict = _color("PASS", C_G) if r["ok"] else _color("FAIL", C_R)
    human = (f"eval {verdict}  {r['passed']}/{r['total']} runs  score {r['score']}\n"
             f"  $ {r['command']}  (commit {_short(r['commit'])})")
    if not r["ok"]:
        tail = (r["results"][-1].get("stderr_tail") or r["results"][-1].get("stdout_tail") or "").strip()
        if tail:
            human += "\n  " + _color(tail.splitlines()[-1][:200], C_DIM)
    _out(args, data, human)


def cmd_freeze(args):
    repo = Repository.open()
    new_oid, artifact = crystallize(repo, args.commit, message=args.message,
                                    force=getattr(args, "force", False))
    new = repo.objects.read_obj(new_oid)
    recipe = repo.objects.read_obj(new["crystal"])
    data = {"commit": new_oid, "source": new["parents"][0], "state": "crystallized",
            "recipe_path": str(artifact), "verified": recipe.get("verified", False)}
    badge = (_color("verified ✓", C_G) if recipe.get("verified")
             else _color("unverified", C_Y))
    human = (f"Crystallized -> {_color(_short(new_oid), C_G)} ({badge})\n"
             f"Deterministic recipe written to {_color(str(artifact), C_B)}")
    _out(args, data, human)


def cmd_merge(args):
    repo = Repository.open()
    try:
        result = merge(repo, args.branch,
                       reconcile=getattr(args, "reconcile", None),
                       force=getattr(args, "force", False))
    except RepoError as e:
        if args.json:
            import json as _json
            print(_json.dumps({"ok": False, "command": "merge",
                               "error": {"code": e.code, "message": str(e)}}))
        else:
            print(f"error: {e}", file=__import__("sys").stderr)
        return 1
    status = result.get("status", "merged")
    if status == "up_to_date":
        _out(args, result, f"Already up to date.")
    elif status == "fast_forward":
        _out(args, result, f"Fast-forward: {_short(result.get('commit', ''))}")
    elif status == "conflict":
        conflicts = result.get("conflicts", [])
        lines = [_color("CONFLICT", C_R) + f" — {len(conflicts)} conflict(s); resolve then commit"]
        for c in conflicts:
            lines.append(f"  {_color('!', C_R)} {c['path']}: {c['reason']}")
        if args.json:
            import json as _json
            print(_json.dumps({"ok": False, "command": "merge", **result}))
        else:
            print("\n".join(lines))
        return 1
    else:
        commit_oid = result.get("commit", "")
        lines = [f"Merged {_color(args.branch, C_B)} -> {_short(commit_oid)}"]
        if result.get("conflicts"):
            lines.append(_color(f"  (forced with {len(result['conflicts'])} conflict(s))", C_Y))
        _out(args, result, "\n".join(lines))


def cmd_soul(args):
    """The agent's curriculum vitae: its cryptographic identity and the verified
    accomplishments (SBTs) minted onto its Soul."""
    from . import soul as soul_mod
    from .sbt import read_sbts, skill_profile
    repo = Repository.open()
    sid = repo.soul_id()
    if sid is None:
        _out(args, {"soul": None},
             "this repo predates the Soul layer (no identity) — re-init to mint one")
        return
    sbts = read_sbts(repo)
    profile = skill_profile(repo)
    # count signed commits in history as a provenance measure
    history = repo.log()
    signed = sum(1 for _, c in history if soul_mod.is_signed(c))
    data = {
        "soul": sid,
        "soul_short": soul_mod.short(sid),
        "commits_signed": signed,
        "commits_total": len(history),
        "sbts": sbts,
        "skill_profile": profile,
    }
    top = sorted(profile.items(), key=lambda kv: -kv[1])[:6]
    lines = [f"{_color(soul_mod.short(sid), C_B)}  ({_color('soul_id', C_DIM)} {sid})",
             f"  signed history: {signed}/{len(history)} commits",
             f"  soulbound tokens: {_color(str(len(sbts)), C_G)}"]
    for s in sbts[-5:]:
        sk = ", ".join(s.get("skill", [])[:4]) or "(general)"
        sc = s.get("score")
        lines.append(f"    {_color('◆', C_G)} {sk}"
                     + (f"  score {sc}" if sc is not None else "")
                     + _color(f"  ({_short(s.get('commit'))})", C_DIM))
    if top:
        lines.append("  skills: " + ", ".join(f"{k}×{v:g}" for k, v in top))
    _out(args, data, "\n".join(lines))


def cmd_verify(args):
    """Verify the Ed25519 provenance of commits — that this Soul, and no other,
    authored them. Needs only the public soul_id; no secret."""
    from . import soul as soul_mod
    from .sbt import read_sbts, verify_sbt
    repo = Repository.open()
    if getattr(args, "all", False):
        history = repo.log()
    else:
        oid = repo._resolve(args.commit, expect="commit") if args.commit else repo.head_commit()
        if not oid:
            raise RepoError("nothing to verify (no commits yet)", code="NO_COMMITS")
        history = [(oid, repo.objects.read_obj(oid))]
    checked = []
    for oid, c in history:
        if soul_mod.is_signed(c):
            status = "valid" if soul_mod.verify_commit(c) else "FORGED"
        else:
            status = "unsigned"
        checked.append({"commit": oid, "soul": c.get("soul"), "status": status})
    sbts = read_sbts(repo)
    sbt_ok = sum(1 for s in sbts if verify_sbt(s))
    all_ok = all(x["status"] in ("valid", "unsigned") for x in checked) and sbt_ok == len(sbts)
    data = {"ok_chain": all_ok, "commits": checked,
            "sbts_total": len(sbts), "sbts_valid": sbt_ok}
    lines = []
    for x in checked:
        c = (C_G if x["status"] == "valid" else
             C_R if x["status"] == "FORGED" else C_DIM)
        lines.append(f"  {_color(x['status'].ljust(8), c)} {_short(x['commit'])}"
                     + (f"  {soul_mod.short(x['soul'])}" if x["soul"] else ""))
    if sbts:
        lines.append(f"  SBTs: {_color(f'{sbt_ok}/{len(sbts)} signatures valid', C_G if sbt_ok==len(sbts) else C_R)}")
    verdict = _color("PROVENANCE OK", C_G) if all_ok else _color("PROVENANCE FAILED", C_R)
    lines.append(verdict)
    _out(args, data, "\n".join(lines))


def cmd_fleet(args):
    """Plural Intelligence: from a pool of Soul skill-profiles, select the maximally
    diverse fleet via correlation discounting. Reads a JSON file of
    ``[{"soul": id, "profile": {tag: weight}}, ...]``."""
    from .plural import select_fleet
    from . import soul as soul_mod
    pool = json.loads(Path(args.profiles).read_text())
    result = select_fleet(pool, args.size, discount=args.discount)
    div = _color(f"{result['diversity']:.3f}", C_G)
    n = _color(str(len(result["fleet"])), C_B)
    lines = [f"selected {n} of {len(pool)} souls "
             f"(diversity {div}, discount {result['discount']})"]
    for m in result["fleet"]:
        lines.append(f"  {_color('◆', C_G)} {soul_mod.short(m['soul'])}  "
                     f"competence {m['competence']:g}")
    _out(args, result, "\n".join(lines))


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        help="machine-readable JSON output (for agents)")
    common.add_argument("-C", "--repo", dest="repo", default=None, metavar="DIR",
                        help="run as if started in DIR (robust for agents whose "
                             "shell cwd is not sticky; created by init if absent)")
    common.add_argument("--mode", choices=["vcs", "runtime"], default=None,
                        help="override agent.json's mode for this command: 'vcs' "
                             "(code+goal+models+trace) or 'runtime' (also capture "
                             "the budget/context/routing frame your runtime hides)")

    p = argparse.ArgumentParser(prog="agentvcs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"agentvcs {__version__}")
    # also accept `agentvcs -C DIR <cmd>` (git-style, before the subcommand)
    p.add_argument("-C", "--repo", dest="repo_global", default=None,
                   metavar="DIR", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    sp = add("new", help="scaffold a new agent project pre-wired with agentvcs")
    sp.add_argument("path")
    sp.add_argument("--claude-code", action="store_true", dest="claude_code",
                    help="wire the trace to the live Claude Code session (no trace file)")
    sp.set_defaults(func=cmd_new)

    sp = add("init", help="create a repository")
    sp.add_argument("path", nargs="?", default=".")
    sp.add_argument("--claude-code", action="store_true", dest="claude_code",
                    help="wire agent.json's trace to the live Claude Code session")
    sp.add_argument("--qwen-code", action="store_true", dest="qwen_code",
                    help="wire agent.json's trace to the live qwen-code session")
    sp.add_argument("--runtime", action="store_true", dest="runtime",
                    help="start in runtime mode (capture budget/context/routing frame)")
    sp.set_defaults(func=cmd_init)

    add("trace", help="show the current trace source (file or auto-discovered session)").set_defaults(func=cmd_trace)

    sp = add("commit", help="snapshot all dimensions")
    sp.add_argument("-m", "--message", required=True)
    sp.add_argument("--author", default="agent")
    sp.set_defaults(func=cmd_commit)

    sp = add("log", help="show evolution history")
    sp.add_argument("--reasoning", action="store_true",
                    help="decision-aware log: goal transitions, eval verdicts, rollback events")
    sp.add_argument("--all", action="store_true",
                    help="with --reasoning, follow merge second-parents too")
    sp.add_argument("--explain", metavar="CMD",
                    help="pipe each commit's thinking to CMD and read back {decision,why}")
    sp.set_defaults(func=cmd_log)
    add("status", help="working-tree changes per dimension").set_defaults(func=cmd_status)

    sp = add("show", help="show one commit across all dimensions")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("--trace", action="store_true",
                    help="also render the captured conversation (trace messages)")
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

    sp = add("merge", help="three-way merge a branch into HEAD")
    sp.add_argument("branch", metavar="branch")
    sp.add_argument("--reconcile", metavar="CMD",
                    help="pipe the reconciliation bundle to CMD and read back "
                         "{goal, trace, notes}")
    sp.add_argument("--force", action="store_true",
                    help="commit even when conflicts exist (markers written to files)")
    sp.set_defaults(func=cmd_merge)

    sp = add("rollback", help="undo: restore full prior state (default: HEAD's parent)")
    sp.add_argument("ref", nargs="?")
    sp.set_defaults(func=cmd_rollback)

    sp = add("eval", help="run agent.json's eval and record the score for a commit")
    sp.add_argument("commit", nargs="?")
    sp.set_defaults(func=cmd_eval)

    sp = add("freeze", help="crystallize a fluid commit (alias: crystallize)")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.add_argument("--force", action="store_true",
                    help="bypass the eval gate (crystallize even if unverified/failing)")
    sp.set_defaults(func=cmd_freeze)

    sp = add("replay", help="deterministically re-execute a crystallized recipe")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("--exec", metavar="CMD",
                    help="pipe each step (JSON) to CMD and collect its output")
    sp.set_defaults(func=cmd_replay)

    sp = add("crystallize", help=argparse.SUPPRESS)
    sp.add_argument("commit", nargs="?")
    sp.add_argument("-m", "--message")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_freeze)

    add("soul", help="show this instance's cryptographic identity and its SBTs (its CV)"
        ).set_defaults(func=cmd_soul)

    sp = add("verify", help="verify the Ed25519 provenance of commits (and SBTs)")
    sp.add_argument("commit", nargs="?")
    sp.add_argument("--all", action="store_true", help="verify the whole history chain")
    sp.set_defaults(func=cmd_verify)

    sp = add("fleet", help="select a maximally-diverse fleet of souls (correlation discounting)")
    sp.add_argument("profiles", help="JSON file: [{\"soul\": id, \"profile\": {tag: weight}}, ...]")
    sp.add_argument("--size", type=int, default=3, help="fleet size to select")
    sp.add_argument("--discount", type=float, default=1.0,
                    help="correlation-discount strength (0=ignore overlap, 1=DeSoc default)")
    sp.set_defaults(func=cmd_fleet)

    add("runtime", help="show the operational frame your runtime hides "
        "(budget/context/routing/tools/subagents)").set_defaults(func=cmd_runtime)
    add("budget", help="token + dollar accounting for the current state").set_defaults(func=cmd_budget)
    add("context", help="context-window pressure + compaction count").set_defaults(func=cmd_context)

    sp = add("recall", help="rank frozen recipes matching a goal — replay instead of re-deriving")
    sp.add_argument("goal", nargs="?", help="goal to match (defaults to agent.json's goal)")
    sp.add_argument("--limit", type=int, default=5)
    sp.add_argument("--verified-only", action="store_true", dest="verified_only",
                    help="only recipes that passed their eval gate")
    sp.set_defaults(func=cmd_recall)

    sp = add("watch", help="live in-terminal runtime feedback (redraws like top)")
    sp.add_argument("--interval", type=float, default=2.0, help="seconds between refreshes")
    sp.add_argument("--width", type=int, default=72)
    sp.add_argument("--once", action="store_true", help="render a single frame and exit")
    sp.set_defaults(func=cmd_watch)

    sp = add("statusline", help="one compact line for your runtime's status line")
    sp.add_argument("--no-color", action="store_true", dest="no_color")
    sp.set_defaults(func=cmd_statusline)

    sp = add("ui", help="serve a local web dashboard to visualize the evolution")
    sp.add_argument("--host", default="127.0.0.1",
                    help="interface to bind (default loopback-only)")
    sp.add_argument("--port", type=int, default=8080,
                    help="port to bind; the next free one is used if taken")
    sp.add_argument("--no-open", action="store_true", dest="no_open",
                    help="do not open a browser; just serve and report the URL")
    sp.set_defaults(func=cmd_ui)

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
