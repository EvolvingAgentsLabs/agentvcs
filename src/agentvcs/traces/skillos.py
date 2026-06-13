"""SkillOS trace provider — auto-discovers a SkillOS agent-runtime session log.

SkillOS runs an agent as a *cognitive pipeline*
(ingress → routing → planning → execution → memory → egress) and can drive it
with a mid-tier open model such as **Gemma 4** (local via Ollama) or a hosted
one such as **Gemini**. Each phase emits events; persisting them as JSONL gives
agentvcs the same high-fidelity, zero-effort trace it gets from Claude Code —
the agent just runs, and ``agentvcs commit`` reads what really happened.

This provider does **not** import SkillOS (the core stays zero-dependency); it
reads the session log off disk. The session is a JSONL file, one event per line.
Every key is optional except a content field; the provider is tolerant of the
several shapes a SkillOS run can emit::

    {"phase":"planning","role":"planner","agent":"hwm-macro-planner",
     "content":"Decompose into subgoals: ...","model":"gemini-2.0-flash",
     "provider":"google","ts":"2026-06-13T18:10:00Z"}
    {"phase":"execution","role":"tool","agent":"sandbox-runner",
     "text":"ran tool.py -> top keywords: ...","model":"gemma4"}

Content is taken from ``content`` → ``text`` → ``message`` (first present). The
phase (ingress/routing/planning/execution/memory/egress) and agent name are kept
so ``agentvcs show --trace`` and ``agentvcs ui`` can render the pipeline.

Manifest declaration (all keys optional except ``provider``)::

    "trace": {
      "provider":  "skillos",
      "auto":      true,
      "path":      "/abs/path/to/session.jsonl", # bypass discovery entirely
      "dir":       ".skillos/sessions",          # pick the newest *.jsonl here
      "session":   "20260613T181000",            # pin a session by file stem
      "redact":    ["(?i)api[_-]?key\\s*[=:]\\s*\\S+"]
    }

Resolution is best-effort: if no session is found yet (e.g. brand-new repo),
``pull`` returns ``[]`` rather than erroring — an empty trace is valid.
"""
from __future__ import annotations

import json
from pathlib import Path

# Reuse the safe-by-default secret scrubbing from the Claude Code provider — the
# on-disk redaction contract is identical, so there is no reason to duplicate it.
from .claude_code import _patterns, _redact

# Where a SkillOS run typically drops its session log, relative to the repo. The
# first existing directory with a *.jsonl wins; an explicit ``dir``/``path`` in
# the manifest always takes precedence over this search.
_SEARCH_DIRS = (
    ".skillos/sessions",
    ".skillos",
    "sessions",
    "runs",
    "traces",
)

# Keys that may carry the message body, in priority order.
_CONTENT_KEYS = ("content", "text", "message", "output")


def pull(decl: dict, workdir: Path) -> list:
    path = _resolve_session(decl, Path(workdir))
    if path is None or not path.exists():
        return []
    return _redact(_parse(path), _patterns(decl))


def describe(decl: dict, workdir: Path) -> dict:
    """Which session would be captured right now, and what's in it."""
    path = _resolve_session(decl, Path(workdir))
    if path is None or not path.exists():
        return {"provider": "skillos", "session": None,
                "exists": False, "messages": 0, "model": None}
    messages = _redact(_parse(path), _patterns(decl))
    model = next((m.get("model") for m in reversed(messages) if m.get("model")), None)
    return {"provider": "skillos", "session": str(path), "exists": True,
            "messages": len(messages), "model": model}


# ------------------------------------------------------------- session lookup
def _resolve_session(decl: dict, workdir: Path):
    # 1. explicit session file path wins
    if decl.get("path"):
        return Path(decl["path"]).expanduser()

    # 2. candidate directories: an explicit pin, else the known SkillOS locations
    if decl.get("dir"):
        dirs = [Path(decl["dir"]).expanduser()]
        if not dirs[0].is_absolute():
            dirs = [workdir / decl["dir"]]
    else:
        dirs = [workdir / d for d in _SEARCH_DIRS]

    sessions = [p for d in dirs if d.is_dir() for p in d.glob("*.jsonl")]
    if not sessions:
        return None

    session = decl.get("session")
    if session:
        return next((p for p in sessions if p.stem == session), None)
    return max(sessions, key=lambda p: p.stat().st_mtime)


# ----------------------------------------------------------------- normalizing
def _content(o: dict):
    for k in _CONTENT_KEYS:
        if o.get(k) is not None:
            return o[k]
    return None


def _parse(path: Path) -> list:
    """Read the session log, normalizing each event to the agentvcs trace shape.

    Skips blank lines and anything we can't parse — a partially written session
    (the agent is still running) must never break a commit."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(o, dict):
            continue
        content = _content(o)
        if content is None:
            continue
        out.append({
            "role": o.get("role") or o.get("phase") or "agent",
            "content": content,
            "model": o.get("model"),
            "provider": o.get("provider"),
            "phase": o.get("phase"),
            "agent": o.get("agent"),
            "ts": o.get("ts") or o.get("timestamp"),
        })
    return out
