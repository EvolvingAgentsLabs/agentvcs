"""Anthropic Managed Agents trace provider — versioning agents that run in
Anthropic's managed cloud.

Unlike Claude Code or qwen-code, a *Managed Agent* runs server-side: there is no
local transcript on disk. The seam Anthropic exposes is the **session event
stream** — every ``user.message`` / ``agent.message`` / ``agent.thinking`` /
``agent.tool_use`` / ``agent.tool_result`` / ``span.model_request_end`` event, with
its history persisted server-side and fetchable in full::

    GET https://api.anthropic.com/v1/sessions/{session_id}/events?beta=true
    -> { "data": [ {"type": "...", "content": [...blocks...], "id": "...",
                    "processed_at": "..."}, ... ] }

Headers: ``x-api-key``, ``anthropic-version: 2023-06-01`` and the beta gate
``anthropic-beta: managed-agents-2026-04-01``. Sessions for an agent are listed at
``GET /v1/sessions?agent_id={agent_id}``.

Two ways to feed this provider, mirroring the others:

* **File (offline, the tested path):** export the session events to
  ``.anthropic/agentvcs/<session>.jsonl`` (one event per line) or
  ``.anthropic/agentvcs/events.jsonl`` — a CI step, a webhook, or
  ``ant beta:sessions:events list`` can write it. ``agentvcs commit`` reads it back.
* **Live fetch (``auto_fetch``):** with a ``session`` (or an ``agent_id`` to pick
  its latest session) and an API key (decl ``api_key`` or ``$ANTHROPIC_API_KEY``),
  the provider pulls the event history over HTTPS using only the standard library.
  Best-effort: any network/credential error degrades to the file path, then to ``[]``.

Managed-agent events already speak Anthropic's native block vocabulary, so we
normalize to the *same* ``{role, content, model, ts}`` shape the Claude Code,
qwen-code and eve providers emit — ``content`` is a string or a list of
``text`` / ``thinking`` / ``tool_use`` / ``tool_result`` blocks. Downstream (diff,
render, crystallize, dashboard) never learns it came from a managed agent.

Manifest declaration (all keys optional except ``provider``)::

    "trace": {
      "provider":   "anthropic-managed",
      "auto":       true,
      "session":    "ses_abc",          # pin a session id
      "agent_id":   "ag_123",           # else discover the agent's latest session (live)
      "auto_fetch": true,               # allow live HTTPS fetch (default: file-only)
      "base_url":   "https://api.anthropic.com",
      "api_key":    "sk-ant-...",        # else read $ANTHROPIC_API_KEY
      "anthropic_dir": ".anthropic",     # where exported events live (default ".anthropic")
      "path":       "/abs/events.jsonl", # bypass discovery entirely
      "model":      "claude-opus-4-8",   # pin routing if events omit it
      "redact":     ["sk-[A-Za-z0-9-]+"]
    }
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Reuse the exact secret scrubber + default patterns the other providers use.
from .claude_code import _DEFAULT_REDACTIONS, _redact

_FALLBACK_MODEL = "claude-managed"
_KEEP_DIR = "agentvcs"
_BETA = "managed-agents-2026-04-01"
_API_VERSION = "2023-06-01"
_BASE_URL = "https://api.anthropic.com"

# Production events that build up a single assistant turn (collapsed into one
# assistant message), the tool returns that close it, and the user side.
_THINKING = {"agent.thinking"}
_MESSAGE = {"agent.message"}
_TOOL_USE = {"agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"}
_TOOL_RESULT = {"agent.tool_result", "agent.mcp_tool_result"}
_USER = {"user.message"}
_ERROR = {"session.status_terminated", "session.error"}
# coordinator → subagent hand-off in a multiagent session (fan-out)
_DELEGATION = {"agent.thread_message_sent", "session.thread_created"}


def pull(decl: dict, workdir: Path) -> list:
    events = _events(decl, Path(workdir))
    if not events:
        return []
    return _redact(_normalize(events, decl.get("model")), _patterns(decl))


def describe(decl: dict, workdir: Path) -> dict:
    events = _events(decl, Path(workdir))
    if not events:
        return {"provider": "anthropic-managed", "transcript": None, "exists": False,
                "messages": 0, "model": decl.get("model"),
                "session": decl.get("session"), "agent_id": decl.get("agent_id")}
    msgs = _redact(_normalize(events, decl.get("model")), _patterns(decl))
    model = next((m.get("model") for m in reversed(msgs) if m.get("model")),
                 decl.get("model"))
    return {"provider": "anthropic-managed", "transcript": _source(decl, Path(workdir)),
            "exists": True, "messages": len(msgs), "model": model,
            "session": decl.get("session"), "agent_id": decl.get("agent_id")}


def runtime(decl: dict, workdir: Path, budget: dict | None = None) -> dict:
    """Reconstruct the operational frame from the managed session event stream.

    ``span.model_request_end`` events carry ``model_usage`` (input/output/cache
    token counts) and the model that ran — the budget and context pressure the
    managed harness tracks but the agent never sees. Coordinator→subagent
    hand-offs (``agent.thread_message_sent``) reveal multiagent fan-out.
    """
    from ..runtime.frame import build_frame
    events = _events(decl, Path(workdir))
    if not events:
        return build_frame([], budget=budget)

    msgs = _redact(_normalize(events, decl.get("model")), _patterns(decl))
    pinned = decl.get("model")
    usages, subagents = [], Counter()
    for ev in events:
        etype = _etype(ev)
        if etype == "span.model_request_end":
            u = ev.get("model_usage") or ev.get("usage") or {}
            if u:
                usages.append({
                    "model": u.get("model") or ev.get("model") or pinned or _FALLBACK_MODEL,
                    "input": _int(u, "input_tokens", "inputTokens", "input", "prompt_tokens"),
                    "output": _int(u, "output_tokens", "outputTokens", "output", "completion_tokens"),
                    "cache_read": _int(u, "cache_read_input_tokens", "cacheReadInputTokens",
                                       "cache_read_tokens", "cached_tokens"),
                    "cache_creation": _int(u, "cache_creation_input_tokens",
                                           "cacheCreationInputTokens", "cache_creation_tokens"),
                })
        elif etype in _DELEGATION:
            data = ev.get("data") or {}
            target = data.get("thread") or data.get("to") or data.get("agent") or "subagent"
            subagents[str(target)] += 1
    return build_frame(
        msgs, usages=usages,
        subagents=[{"type": k, "count": c} for k, c in subagents.most_common()],
        budget=budget)


# ----------------------------------------------------------------- redaction
def _patterns(decl: dict) -> list:
    user = decl.get("redact")
    if user is False:
        return []
    pats = [] if decl.get("redact_defaults") is False else list(_DEFAULT_REDACTIONS)
    if isinstance(user, list):
        pats += user
    return pats


# ----------------------------------------------------------------- event source
def _anthropic_root(decl: dict, workdir: Path) -> Path:
    raw = decl.get("anthropic_dir")
    return (Path(raw).expanduser() if raw and Path(raw).is_absolute()
            else workdir / (raw or ".anthropic"))


def _resolve_file(decl: dict, workdir: Path):
    """Locate an exported events file, mirroring the discovery the other providers
    do (explicit path → pinned session → canonical name → scan)."""
    if decl.get("path"):
        return Path(decl["path"]).expanduser()
    root = _anthropic_root(decl, workdir)
    session = decl.get("session")
    if session:
        cand = root / _KEEP_DIR / f"{session}.jsonl"
        if cand.exists():
            return cand
    canonical = root / _KEEP_DIR / "events.jsonl"
    if canonical.exists():
        return canonical
    if root.is_dir():
        found = [p for p in root.rglob("*.jsonl")
                 if _KEEP_DIR in p.parts or p.stem in ("events", "trace")]
        found += [p for p in root.rglob("*.json") if _KEEP_DIR in p.parts]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
    return None


def _source(decl: dict, workdir: Path):
    f = _resolve_file(decl, workdir)
    if f is not None:
        return str(f)
    if decl.get("session"):
        return f"managed-session:{decl['session']}"
    if decl.get("agent_id"):
        return f"managed-agent:{decl['agent_id']}"
    return None


def _events(decl: dict, workdir: Path) -> list:
    """The raw managed event list: exported file first, then a live API fetch when
    ``auto_fetch`` is on and credentials are present. Best-effort; never raises."""
    f = _resolve_file(decl, workdir)
    if f is not None and f.exists():
        return _load_events_file(f)
    if decl.get("auto_fetch"):
        fetched = _fetch_events(decl)
        if fetched:
            return fetched
    return []


def _load_events_file(path: Path) -> list:
    """Read an exported events file: JSONL (one event/line), a ``{"data":[...]}``
    envelope, or a bare JSON array."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    text = text.strip()
    if not text:
        return []
    # whole-file JSON (array or {"data": [...]})
    if text[0] in "[{":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, list):
            return [e for e in obj if isinstance(e, dict)]
        if isinstance(obj, dict):
            data = obj.get("data") or obj.get("events")
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
    # JSONL
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _fetch_events(decl: dict) -> list:
    """Pull a managed session's event history over HTTPS using only the standard
    library. Returns [] on any error (missing key, network, bad status)."""
    import os
    import urllib.error
    import urllib.request

    api_key = decl.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []
    base = (decl.get("base_url") or _BASE_URL).rstrip("/")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _API_VERSION,
        "anthropic-beta": _BETA,
    }

    def _get(url: str):
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (https only)
            return json.loads(resp.read().decode("utf-8"))

    session = decl.get("session")
    try:
        if not session and decl.get("agent_id"):
            listing = _get(f"{base}/v1/sessions?agent_id={decl['agent_id']}")
            sessions = listing.get("data") or []
            if not sessions:
                return []
            # newest last in a forward listing; fall back to the first entry
            session = (sessions[-1].get("id") or sessions[0].get("id"))
        if not session:
            return []
        result = _get(f"{base}/v1/sessions/{session}/events?beta=true")
    except (urllib.error.URLError, ValueError, KeyError, OSError):
        return []
    data = result.get("data") if isinstance(result, dict) else None
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


# ----------------------------------------------------------------- normalizing
def _etype(ev: dict) -> str:
    return ev.get("type") or ev.get("event") or ev.get("eventType") or ""


def _blocks(ev: dict) -> list:
    """The Anthropic-style content blocks carried by an event (defensive: events
    may put text directly or under content/message)."""
    content = ev.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    msg = ev.get("message") or ev.get("text")
    if isinstance(msg, str):
        return [{"type": "text", "text": msg}]
    return []


def _normalize(events, model: str | None) -> list:
    """Managed event stream → agentvcs normalized messages.

    Consecutive agent production events (thinking → message → tool_use) collapse
    into one *assistant* message whose content is the ordered block list; each
    tool return becomes a *user* message with a ``tool_result`` block — the exact
    assistant(tool_use)→user(tool_result) interleave the renderer/diff/crystallize
    already understand. ``user.message`` events are user turns.
    """
    out: list = []
    pending: list = []
    pending_ts = None
    last_model = model

    def flush():
        nonlocal pending, pending_ts
        if not pending:
            return
        content = (pending[0]["text"] if len(pending) == 1
                   and pending[0].get("type") == "text" else list(pending))
        out.append({"role": "assistant", "content": content,
                    "model": last_model, "ts": pending_ts})
        pending = []
        pending_ts = None

    for ev in events:
        etype = _etype(ev)
        ts = ev.get("processed_at") or ev.get("ts") or ev.get("timestamp")
        # track the most recent model we can see, to stamp assistant turns
        m = ev.get("model") or (ev.get("model_usage") or {}).get("model")
        if m:
            last_model = m

        if etype in _USER:
            flush()
            blocks = _blocks(ev)
            text = (blocks[0]["text"] if len(blocks) == 1
                    and blocks[0].get("type") == "text"
                    else (blocks or _text_of(ev)))
            out.append({"role": "user", "content": text, "model": None, "ts": ts})

        elif etype in _THINKING:
            if pending_ts is None:
                pending_ts = ts
            for b in _blocks(ev):
                t = b.get("type")
                if t == "thinking":
                    pending.append(b)
                elif t == "text":
                    pending.append({"type": "thinking", "thinking": b.get("text", "")})
            if not _blocks(ev):
                pending.append({"type": "thinking", "thinking": _text_of(ev)})

        elif etype in _MESSAGE:
            if pending_ts is None:
                pending_ts = ts
            pending.extend(_blocks(ev) or [{"type": "text", "text": _text_of(ev)}])

        elif etype in _TOOL_USE:
            if pending_ts is None:
                pending_ts = ts
            for b in _blocks(ev):
                pending.append({"type": "tool_use",
                                "name": b.get("name") or ev.get("name") or "?",
                                "input": b.get("input") or b.get("args") or {},
                                **({"id": b["id"]} if b.get("id") else {})})
            if not _blocks(ev) and ev.get("name"):
                pending.append({"type": "tool_use", "name": ev["name"],
                                "input": ev.get("input") or {}})

        elif etype in _TOOL_RESULT:
            flush()
            out.append({"role": "user", "content": [_tool_result_block(ev)],
                        "model": None, "ts": ts})

        elif etype in _ERROR:
            flush()
            err = _text_of(ev) or (ev.get("error") or {}).get("message") or "session error"
            out.append({"role": "assistant",
                        "content": [{"type": "text", "text": f"[{etype}] {err}"}],
                        "model": last_model, "ts": ts})

    flush()
    return out


def _text_of(ev: dict) -> str:
    for b in _blocks(ev):
        if b.get("type") == "text":
            return b.get("text", "")
    msg = ev.get("message") or ev.get("text")
    return msg if isinstance(msg, str) else ""


def _tool_result_block(ev: dict) -> dict:
    blocks = _blocks(ev)
    for b in blocks:
        if b.get("type") == "tool_result":
            return b
    # event without an explicit tool_result block: synthesize from common fields
    result = ev.get("result")
    if result is None:
        result = ev.get("output") if "output" in ev else ev.get("error", "")
    block = {"type": "tool_result", "content": result}
    if ev.get("is_error") or ev.get("error"):
        block["is_error"] = True
    if ev.get("name"):
        block["name"] = ev["name"]
    return block


def _int(d: dict, *keys) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0
