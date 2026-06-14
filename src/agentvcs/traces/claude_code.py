"""Claude Code trace provider — auto-discovers the native session transcript.

Claude Code already records every session as JSONL at::

    ~/.claude/projects/<cwd-with-"/"-replaced-by-"-">/<session-uuid>.jsonl

Each line is one event; ``type`` ``user`` / ``assistant`` lines wrap the full
Anthropic message — including ``tool_use`` / ``tool_result`` blocks, ``thinking``
blocks, and the exact ``model`` that ran. That is the high-fidelity trace, with
zero work asked of the agent: it commits, and agentvcs reads what really
happened.

Manifest declaration (all keys optional except ``provider``)::

    "trace": {
      "provider":    "claude-code",
      "auto":        true,
      "session":     "c27aa057-...",      # pin a session uuid (else newest is used)
      "project_dir": "-Users-me-proj",    # pin the encoded projects subdir
      "projects_dir": "~/.claude/projects",
      "path":        "/abs/path/to.jsonl",# bypass discovery entirely
      "redact":      ["(?i)api[_-]?key\\s*[=:]\\s*\\S+"]
    }

Resolution is best-effort: if no transcript is found yet (e.g. brand-new repo),
``pull`` returns ``[]`` rather than erroring — an empty trace is valid.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

_DEFAULT_PROJECTS = Path.home() / ".claude" / "projects"
_KEEP_TYPES = ("user", "assistant")

# Always-on scrubbing: transcripts routinely contain live credentials. These run
# by default so capture is safe-by-default; disable with "redact_defaults": false.
_DEFAULT_REDACTIONS = [
    r"sk-ant-[A-Za-z0-9_-]{16,}",                       # Anthropic keys
    r"sk-[A-Za-z0-9_-]{20,}",                           # OpenAI-style keys
    r"AKIA[0-9A-Z]{16}",                                # AWS access key id
    r"gh[pousr]_[A-Za-z0-9]{16,}",                      # GitHub tokens
    r"xox[baprs]-[A-Za-z0-9-]{10,}",                    # Slack tokens
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}",  # JWTs
    r"(?i)(api[_-]?key|secret|password|token|authorization)"
    r"\b\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{8,}",           # key=value secrets
]


def pull(decl: dict, workdir: Path) -> list:
    path = _resolve_transcript(decl, Path(workdir))
    if path is None or not path.exists():
        return []
    return _redact(_parse(path), _patterns(decl))


def describe(decl: dict, workdir: Path) -> dict:
    """Which transcript would be captured right now, and what's in it."""
    path = _resolve_transcript(decl, Path(workdir))
    if path is None or not path.exists():
        return {"provider": "claude-code", "transcript": None,
                "exists": False, "messages": 0, "model": None}
    messages = _redact(_parse(path), _patterns(decl))
    model = next((m.get("model") for m in reversed(messages) if m.get("model")), None)
    return {"provider": "claude-code", "transcript": str(path), "exists": True,
            "messages": len(messages), "model": model}


def runtime(decl: dict, workdir: Path, budget: dict | None = None) -> dict:
    """Reconstruct the operational frame Claude Code keeps to itself.

    Every assistant line in the transcript carries ``message.usage`` (the exact
    input/output/cache token counts) and ``message.model`` (the model that
    actually ran — routing the agent never sees). Subagent fan-out shows up as
    ``Task``/``Agent`` tool calls and ``isSidechain`` lines; context compaction
    as ``isCompactSummary`` summaries. We surface all of it.
    """
    from ..runtime.frame import build_frame
    path = _resolve_transcript(decl, Path(workdir))
    if path is None or not path.exists():
        return build_frame([], budget=budget)

    messages = _redact(_parse(path), _patterns(decl))
    usages, compactions, subagents = [], 0, Counter()
    for o in _raw_objects(path):
        if o.get("isCompactSummary") or o.get("type") == "summary":
            compactions += 1
        msg = o.get("message") or {}
        if o.get("type") == "assistant" and isinstance(msg.get("usage"), dict):
            u = msg["usage"]
            usages.append({
                "model": msg.get("model") or "",
                "input": u.get("input_tokens", 0),
                "output": u.get("output_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_creation": u.get("cache_creation_input_tokens", 0),
            })
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" \
                    and b.get("name") in ("Task", "Agent"):
                kind = (b.get("input") or {}).get("subagent_type") or "subagent"
                subagents[kind] += 1
    return build_frame(
        messages, usages=usages, compactions=compactions,
        subagents=[{"type": k, "count": c} for k, c in subagents.most_common()],
        budget=budget)


def _raw_objects(path: Path):
    """Yield every parsed JSONL record (not just conversation turns) so runtime
    reconstruction can see usage/sidechain/compaction housekeeping lines."""
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _patterns(decl: dict) -> list:
    """Combine built-in redactions with any declared in the manifest. ``redact:
    false`` disables everything; ``redact_defaults: false`` keeps only the
    user-supplied patterns."""
    user = decl.get("redact")
    if user is False:
        return []
    pats = [] if decl.get("redact_defaults") is False else list(_DEFAULT_REDACTIONS)
    if isinstance(user, list):
        pats += user
    return pats


# ----------------------------------------------------------- transcript lookup
def _encode(p: Path) -> str:
    """Claude Code's project-dir key: the absolute path with '/' -> '-'."""
    return str(p).replace("/", "-")


def _projects_root(decl: dict) -> Path:
    raw = decl.get("projects_dir")
    return Path(raw).expanduser() if raw else _DEFAULT_PROJECTS


def _resolve_transcript(decl: dict, workdir: Path):
    # 1. explicit transcript path wins
    if decl.get("path"):
        return Path(decl["path"]).expanduser()

    root = _projects_root(decl)
    session = decl.get("session")

    # 2. candidate project dirs: an explicit pin, else workdir and its parents
    #    (Claude Code may have been launched in a parent of the agentvcs repo).
    if decl.get("project_dir"):
        candidates = [root / decl["project_dir"]]
    else:
        candidates = [root / _encode(c) for c in [workdir, *workdir.parents]]

    transcripts = [t for d in candidates if d.is_dir() for t in d.glob("*.jsonl")]

    # 3. fall back to scanning every project, matching the recorded cwd — this
    #    is encoding-agnostic and bulletproof when the fast path misses.
    if not transcripts:
        transcripts = _scan_by_cwd(root, workdir)

    if session:
        return next((t for t in transcripts if t.stem == session), None)
    if not transcripts:
        return None
    return max(transcripts, key=lambda p: p.stat().st_mtime)


def _scan_by_cwd(root: Path, workdir: Path):
    """Find transcripts whose recorded ``cwd`` is the workdir or an ancestor of
    it (i.e. the session that was launched here or one directory up)."""
    if not root.is_dir():
        return []
    wd = workdir.resolve()
    matches = []
    for jsonl in root.glob("*/*.jsonl"):
        cwd = _first_cwd(jsonl)
        if cwd is None:
            continue
        c = Path(cwd).resolve()
        if c == wd or c in wd.parents:
            matches.append(jsonl)
    return matches


def _first_cwd(jsonl: Path):
    try:
        with jsonl.open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("cwd"):
                    return o["cwd"]
    except OSError:
        return None
    return None


# ----------------------------------------------------------------- normalizing
def _parse(path: Path) -> list:
    """Read the transcript, keeping only real conversation turns and dropping
    Claude Code's housekeeping lines (mode / permission-mode / ai-title / ...)."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") not in _KEEP_TYPES:
            continue
        msg = o.get("message") or {}
        content = msg.get("content")
        if content is None:
            continue
        out.append({
            "role": msg.get("role") or o["type"],
            "content": content,
            "model": msg.get("model"),
            "ts": o.get("timestamp"),
            "uuid": o.get("uuid"),
        })
    return out


# -------------------------------------------------------------------- redaction
def _redact(messages: list, patterns: list) -> list:
    """Scrub secrets before they enter the object store. Transcripts can contain
    keys, tokens, and paths; capture must never leak them by default."""
    if not patterns:
        return messages
    regexes = [re.compile(p) for p in patterns]

    def scrub(v):
        if isinstance(v, str):
            for r in regexes:
                v = r.sub("[REDACTED]", v)
            return v
        if isinstance(v, list):
            return [scrub(x) for x in v]
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items()}
        return v

    return [scrub(m) for m in messages]
