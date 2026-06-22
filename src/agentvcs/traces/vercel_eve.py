"""Vercel eve trace provider — versioning filesystem-first agents.

`eve <https://eve.dev>`_ is Vercel's framework for building durable agents as
ordinary files (``agent.ts``, ``instructions.md``, ``tools/``, ``skills/`` …).
It runs every turn through the open-source **Workflow SDK**, which makes
sessions durable, resumable and crash-safe — but keeps that durable state to
itself: there is no stable on-disk transcript a tool can read, the way Claude
Code or qwen-code leave one.

eve *does* expose the right seam: **hooks**. A hook subscribing to the ``*``
stream event sees every ``session.started`` / ``message.completed`` /
``action.result`` / ``turn.completed`` event as it happens. So the integration
is one tiny hook that appends those events to a JSONL file, plus this provider
that reads them back. We own both sides of that seam, which is exactly why it
survives eve being in beta: when eve's *internal* state format changes, the
hook's event vocabulary does not.

Drop ``examples/eve/agent/hooks/agentvcs.ts`` into an eve project's
``agent/hooks/`` and it writes, by default::

    <project>/.eve/agentvcs/trace.jsonl

one event per line::

    {"ts": 1718900000000, "type": "session.started",
     "data": {"input": {"message": "build a refunds queue"}}}
    {"ts": 1718900001000, "type": "message.completed",
     "data": {"model": "claude-opus-4-8", "message": "On it.",
              "reasoning": "...", "toolCalls": [{"name": "write_file",
              "input": {"path": "agent/tools/refund.ts"}}],
              "usage": {"inputTokens": 1820, "outputTokens": 240}}}
    {"ts": 1718900002000, "type": "action.result",
     "data": {"name": "write_file", "result": {"ok": true}}}

We normalize that to the *same* ``{role, content, model, ts}`` shape the Claude
Code and qwen-code providers emit — ``content`` is a string or a list of
Anthropic-style blocks (``text`` / ``thinking`` / ``tool_use`` / ``tool_result``).
Downstream (diff, render, crystallize, dashboard) never learns it came from eve.

Manifest declaration (all keys optional except ``provider``)::

    "trace": {
      "provider": "vercel-eve",
      "auto":     true,
      "model":    "claude-opus-4-8",   # pin routing if events omit it
      "path":     "/abs/trace.jsonl",  # bypass discovery entirely
      "eve_dir":  ".eve",              # where the hook writes (default ".eve")
      "session":  "sess_abc",          # pin .eve/agentvcs/<session>.jsonl
      "redact":   ["sk-[A-Za-z0-9-]+"]
    }

Resolution is best-effort: no trace yet (brand-new project) → ``pull`` returns
``[]`` rather than erroring. An empty trace is valid.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

_FALLBACK_MODEL = "eve"
_KEEP_DIR = "agentvcs"

# Reuse the exact secret scrubber + default patterns the other providers use.
from .claude_code import _DEFAULT_REDACTIONS, _redact

# action/tool names that mean "the root agent delegated to a specialist" — eve
# organizes those under subagents/. Fan-out shows up as one of these calls.
_DELEGATION = {"delegate", "subagent", "spawn_agent", "task", "handoff"}


def pull(decl: dict, workdir: Path) -> list:
    path = _resolve_log(decl, Path(workdir))
    if path is None or not path.exists():
        return []
    return _redact(_normalize(_events(path), decl.get("model")), _patterns(decl))


def describe(decl: dict, workdir: Path) -> dict:
    path = _resolve_log(decl, Path(workdir))
    if path is None or not path.exists():
        return {"provider": "vercel-eve", "transcript": None, "exists": False,
                "messages": 0, "model": decl.get("model")}
    msgs = pull(decl, Path(workdir))
    model = next((m.get("model") for m in reversed(msgs) if m.get("model")),
                 decl.get("model"))
    return {"provider": "vercel-eve", "transcript": str(path), "exists": True,
            "messages": len(msgs), "model": model}


def runtime(decl: dict, workdir: Path, budget: dict | None = None) -> dict:
    """Reconstruct the operational frame from the captured eve event stream.

    ``message.completed`` / ``turn.completed`` events carry ``data.usage``
    (input/output/cache token counts) and ``data.model`` — the budget and
    context pressure the Workflow SDK tracks but the agent never sees. Delegation
    to subagents shows up as ``action.result`` events whose action name is a
    handoff verb. When usage is absent the frame still reports turns, routing and
    tool usage from the messages — already more than eve surfaces to the agent.
    """
    from ..runtime.frame import build_frame
    path = _resolve_log(decl, Path(workdir))
    if path is None or not path.exists():
        return build_frame([], budget=budget)

    msgs = pull(decl, Path(workdir))
    pinned = decl.get("model")
    usages, subagents = [], Counter()
    for ev in _events(path):
        etype = _etype(ev)
        data = ev.get("data") or {}
        if etype in ("message.completed", "turn.completed"):
            u = data.get("usage") or {}
            if u:
                usages.append({
                    "model": data.get("model") or pinned or _FALLBACK_MODEL,
                    "input": _int(u, "inputTokens", "input", "promptTokens"),
                    "output": _int(u, "outputTokens", "output", "completionTokens"),
                    "cache_read": _int(u, "cacheReadTokens", "cachedTokens"),
                    "cache_creation": _int(u, "cacheCreationTokens"),
                })
        if etype == "action.result":
            name = (data.get("name") or "").lower()
            kind = data.get("kind") or data.get("subagent")
            if kind or name in _DELEGATION:
                subagents[str(kind or name)] += 1
    return build_frame(
        msgs, usages=usages,
        subagents=[{"type": k, "count": c} for k, c in subagents.most_common()],
        budget=budget)


# ----------------------------------------------------------------- log lookup
def _patterns(decl: dict) -> list:
    user = decl.get("redact")
    if user is False:
        return []
    pats = [] if decl.get("redact_defaults") is False else list(_DEFAULT_REDACTIONS)
    if isinstance(user, list):
        pats += user
    return pats


def _eve_root(decl: dict, workdir: Path) -> Path:
    raw = decl.get("eve_dir")
    return (Path(raw).expanduser() if raw and Path(raw).is_absolute()
            else workdir / (raw or ".eve"))


def _resolve_log(decl: dict, workdir: Path):
    # 1. explicit path wins
    if decl.get("path"):
        return Path(decl["path"]).expanduser()

    root = _eve_root(decl, workdir)
    session = decl.get("session")
    if session:
        cand = root / _KEEP_DIR / f"{session}.jsonl"
        return cand if cand.exists() else None

    # 2. canonical location the bundled hook writes to
    canonical = root / _KEEP_DIR / "trace.jsonl"
    if canonical.exists():
        return canonical

    # 3. bulletproof fallback: scan .eve/ for any agentvcs/trace jsonl (the hook
    #    may have been pointed elsewhere); newest wins. Mirrors the scan-by-cwd /
    #    scan-every-project-dir fallbacks in the Claude and qwen providers.
    if not root.is_dir():
        return None
    found = [p for p in root.rglob("*.jsonl")
             if p.stem in ("trace", _KEEP_DIR) or _KEEP_DIR in p.parts]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


# ----------------------------------------------------------------- normalizing
def _events(path: Path):
    """Yield each parsed JSONL event, skipping blanks and unparseable lines."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _etype(ev: dict) -> str:
    return ev.get("type") or ev.get("event") or ev.get("eventType") or ""


def _normalize(events, model: str | None) -> list:
    """eve stream events → agentvcs normalized messages.

    The mapping mirrors the Anthropic turn shape every other provider speaks:
    a model turn (``message.completed``) becomes an *assistant* message whose
    content is ``[thinking?, text?, tool_use*]``; each tool return
    (``action.result``) becomes a *user* message carrying a ``tool_result``
    block — exactly the assistant(tool_use)→user(tool_result) interleave the
    renderer, diff and crystallize already understand.
    """
    out = []
    for ev in events:
        etype = _etype(ev)
        data = ev.get("data") or {}
        ts = ev.get("ts") or ev.get("timestamp") or data.get("ts")

        if etype in ("session.started", "message.received", "user.message"):
            text = _user_text(data)
            if text is not None:
                out.append({"role": "user", "content": text,
                            "model": None, "ts": ts})

        elif etype == "message.completed":
            blocks = _assistant_blocks(data)
            content = (blocks[0]["text"] if len(blocks) == 1
                       and blocks[0].get("type") == "text" else blocks)
            out.append({"role": "assistant", "content": content,
                        "model": data.get("model") or model, "ts": ts})

        elif etype == "action.result":
            out.append({"role": "user",
                        "content": [_tool_result_block(data)],
                        "model": None, "ts": ts})

        elif etype in ("turn.failed", "session.failed"):
            # surface where the run broke — this is precisely the step a dev
            # rolls back to, so it must be visible in the trace.
            err = data.get("error") or data.get("message") or "run failed"
            out.append({"role": "assistant",
                        "content": [{"type": "text", "text": f"[{etype}] {err}"}],
                        "model": data.get("model") or model, "ts": ts})
    return out


def _user_text(data: dict):
    """Pull the inbound user message out of a session.started-style payload."""
    inp = data.get("input")
    if isinstance(inp, dict):
        return inp.get("message") or inp.get("text") or inp.get("prompt")
    if isinstance(inp, str):
        return inp
    return data.get("message") or data.get("prompt") or data.get("text")


def _assistant_blocks(data: dict) -> list:
    """message.completed → ordered Anthropic-style blocks."""
    blocks = []
    reasoning = data.get("reasoning") or data.get("thinking")
    if reasoning:
        blocks.append({"type": "thinking", "thinking": str(reasoning)})
    text = data.get("message")
    if isinstance(text, str) and text:
        blocks.append({"type": "text", "text": text})
    elif isinstance(text, list):  # already a block list
        blocks.extend(b for b in text if isinstance(b, dict))
    for call in data.get("toolCalls") or data.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        blocks.append({"type": "tool_use",
                       "name": call.get("name") or "?",
                       "input": call.get("input") or call.get("args") or {}})
    return blocks or [{"type": "text", "text": ""}]


def _tool_result_block(data: dict) -> dict:
    result = data.get("result")
    if result is None:
        result = data.get("output") if "output" in data else data.get("error", "")
    block = {"type": "tool_result", "content": result}
    if data.get("isError") or data.get("error"):
        block["is_error"] = True
    if data.get("name"):
        block["name"] = data["name"]
    return block


def _int(d: dict, *keys) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0
