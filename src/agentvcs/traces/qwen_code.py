"""qwen-code trace provider — proves agentvcs is a *neutral* substrate.

qwen-code (QwenLM/qwen-code) is a fork of Google's gemini-cli, so it persists
conversations the same way: under a per-project temp dir keyed by a hash of the
project root::

    ~/.qwen/tmp/<sha256(project-root)>/checkpoint-<tag>.json   # saved chat
    ~/.qwen/tmp/<sha256(project-root)>/logs.json               # message log

A checkpoint is a JSON array of Gemini ``Content`` objects::

    [ {"role": "user",  "parts": [{"text": "build a refunds queue"}]},
      {"role": "model", "parts": [{"text": "on it"},
                                  {"functionCall": {"name": "edit", "args": {...}}}]},
      {"role": "user",  "parts": [{"functionResponse": {"name": "edit",
                                                        "response": {...}}}]} ]

We normalize that to the *same* message shape the Claude Code provider emits —
``{role, content, model, ts}`` where ``content`` is either a string or a list of
Anthropic-style blocks (``text`` / ``tool_use`` / ``tool_result``). Downstream —
the renderer, the diff, crystallize, the dashboard — none of it knows or cares
which runtime produced the trace. That is the whole point: one on-disk format,
many runtimes.

Manifest declaration (all keys optional except ``provider``)::

    "trace": {
      "provider":     "qwen-code",
      "auto":         true,
      "model":        "qwen3-coder-plus",   # routing isn't in the chat history; pin it
      "project_hash": "ab12…",              # else computed from the workdir
      "qwen_dir":     "~/.qwen",
      "path":         "/abs/checkpoint.json",
      "redact":       ["sk-[A-Za-z0-9-]+"]
    }
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

# qwen-code stores model name / usage on the *response*, not in the saved chat
# history, so a checkpoint usually can't tell us which model ran. Pin it in the
# manifest; otherwise we label the routing generically.
_FALLBACK_MODEL = "qwen"

_DEFAULT_REDACTIONS = [
    r"sk-[A-Za-z0-9_-]{20,}",
    r"sk-ant-[A-Za-z0-9_-]{16,}",
    r"AKIA[0-9A-Z]{16}",
    r"gh[pousr]_[A-Za-z0-9]{16,}",
    r"(?i)(api[_-]?key|secret|password|token|authorization)"
    r"\b\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{8,}",
]


def pull(decl: dict, workdir: Path) -> list:
    path = _resolve_checkpoint(decl, Path(workdir))
    if path is None or not path.exists():
        return []
    from .claude_code import _redact  # reuse the exact same scrubber
    return _redact(_normalize(_load(path), decl.get("model")), _patterns(decl))


def describe(decl: dict, workdir: Path) -> dict:
    path = _resolve_checkpoint(decl, Path(workdir))
    if path is None or not path.exists():
        return {"provider": "qwen-code", "transcript": None, "exists": False,
                "messages": 0, "model": decl.get("model")}
    msgs = pull(decl, Path(workdir))
    return {"provider": "qwen-code", "transcript": str(path), "exists": True,
            "messages": len(msgs), "model": decl.get("model") or _FALLBACK_MODEL}


def runtime(decl: dict, workdir: Path, budget: dict | None = None) -> dict:
    """Reconstruct the operational frame from a qwen-code checkpoint.

    Gemini-style ``usageMetadata`` (promptTokenCount/candidatesTokenCount) is
    only present if the fork persisted it next to the history; when it is, budget
    and context pressure light up exactly like Claude Code. When it isn't, the
    frame still reports turns, model routing and tool usage — which is already
    more than the runtime ever told the agent.
    """
    from ..runtime.frame import build_frame
    path = _resolve_checkpoint(decl, Path(workdir))
    if path is None or not path.exists():
        return build_frame([], budget=budget)

    msgs = pull(decl, Path(workdir))
    model = decl.get("model") or _FALLBACK_MODEL
    usages, subagents = [], Counter()
    for item in _load(path):
        if not isinstance(item, dict):
            continue
        um = item.get("usageMetadata") or {}
        if item.get("role") == "model":
            usages.append({
                "model": model,
                "input": um.get("promptTokenCount", 0),
                "output": um.get("candidatesTokenCount", 0),
                "cache_read": um.get("cachedContentTokenCount", 0),
            })
        for part in item.get("parts") or []:
            fc = isinstance(part, dict) and part.get("functionCall")
            if fc and fc.get("name") in ("task", "subagent", "spawn_agent"):
                kind = (fc.get("args") or {}).get("type") or "subagent"
                subagents[kind] += 1
    return build_frame(
        msgs, usages=usages,
        subagents=[{"type": k, "count": c} for k, c in subagents.most_common()],
        budget=budget)


# ------------------------------------------------------------- checkpoint lookup
def _patterns(decl: dict) -> list:
    user = decl.get("redact")
    if user is False:
        return []
    pats = [] if decl.get("redact_defaults") is False else list(_DEFAULT_REDACTIONS)
    if isinstance(user, list):
        pats += user
    return pats


def _qwen_root(decl: dict) -> Path:
    raw = decl.get("qwen_dir")
    return (Path(raw).expanduser() if raw else Path.home() / ".qwen") / "tmp"


def _project_hash(workdir: Path) -> str:
    """gemini-cli/qwen-code key the temp dir by sha256 of the project root."""
    return hashlib.sha256(str(workdir.resolve()).encode()).hexdigest()


def _resolve_checkpoint(decl: dict, workdir: Path):
    if decl.get("path"):
        return Path(decl["path"]).expanduser()

    root = _qwen_root(decl)
    if not root.is_dir():
        return None

    # 1. computed/declared project hash dir
    h = decl.get("project_hash") or _project_hash(workdir)
    dirs = [root / h]
    # 2. bulletproof fallback: scan every project temp dir (hash scheme may drift
    #    across qwen-code versions — same philosophy as the Claude provider's
    #    scan-by-cwd). Newest checkpoint across all of them wins.
    dirs += [d for d in root.glob("*") if d.is_dir() and d.name != h]

    candidates = []
    for d in dirs:
        candidates += list(d.glob("checkpoint*.json"))
        candidates += [p for p in d.glob("logs.json")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ----------------------------------------------------------------- normalizing
def _load(path: Path) -> list:
    """Read a checkpoint (array of Content, or wrapped) or a logs.json array."""
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("history") or data.get("messages") or data.get("checkpoint") or []
    return data if isinstance(data, list) else []


def _normalize(items: list, model: str | None) -> list:
    """Gemini ``Content`` (role/parts) → agentvcs normalized messages. Also
    tolerates logs.json rows (``{type, message, timestamp}``)."""
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # logs.json row
        if "parts" not in item and ("message" in item or "type" in item):
            out.append({"role": _role(item.get("type", "user")),
                        "content": item.get("message", ""),
                        "model": None, "ts": item.get("timestamp")})
            continue
        role = _role(item.get("role", "user"))
        blocks = _parts_to_blocks(item.get("parts") or [])
        # collapse a single plain-text part to a string (matches file traces)
        content = (blocks[0]["text"] if len(blocks) == 1 and blocks[0].get("type") == "text"
                   else blocks)
        out.append({"role": role, "content": content,
                    "model": model if role == "assistant" else None, "ts": None})
    return out


def _role(r: str) -> str:
    return "assistant" if r in ("model", "assistant") else "user"


def _parts_to_blocks(parts: list) -> list:
    """Map Gemini parts to the Anthropic-style block vocabulary the renderer and
    UI already speak, so qwen traces display identically to Claude ones."""
    blocks = []
    for p in parts:
        if not isinstance(p, dict):
            blocks.append({"type": "text", "text": str(p)})
            continue
        if "text" in p:
            blocks.append({"type": "text", "text": p["text"]})
        elif "functionCall" in p:
            fc = p["functionCall"] or {}
            blocks.append({"type": "tool_use", "name": fc.get("name", "?"),
                           "input": fc.get("args", {})})
        elif "functionResponse" in p:
            fr = p["functionResponse"] or {}
            blocks.append({"type": "tool_result",
                           "content": fr.get("response", fr)})
        elif "thought" in p or p.get("thinking"):
            blocks.append({"type": "thinking",
                           "thinking": p.get("thought") or p.get("thinking")})
    return blocks or [{"type": "text", "text": ""}]
