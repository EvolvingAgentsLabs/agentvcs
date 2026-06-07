"""Scaffold a new agent project that is pre-wired with agentvcs.

This is the adoption lever: validation showed agents drive agentvcs well *once a
project already uses it* (has .agentvcs / agent.json / AGENTS.md / the skill), but
don't reach for it unprompted on a blank task. `agentvcs new <dir>` materializes
exactly that starting context — manifest, agent operating manual, the Claude Code
skill, the MCP config, a starter agent and trace — then inits the repo and makes
the first commit.
"""
from __future__ import annotations

from pathlib import Path

from .repository import Repository, RepoError

_AGENT_JSON = """{
  "goal": "Triage incoming support messages: classify them, route to a queue, and flag urgent ones.",
  "models": [
    { "provider": "anthropic", "model": "claude-opus-4-8", "version": null, "params": { "temperature": 1.0 } }
  ],
  "trace": "traces/run.jsonl",
  "state": "fluid",
  "metrics": {}
}
"""

# Provider-wired variant: the trace is the live Claude Code session, so there is
# no traces/run.jsonl to maintain and the model pin is detected from what ran.
_AGENT_JSON_CC = """{
  "goal": "Triage incoming support messages: classify them, route to a queue, and flag urgent ones.",
  "models": [
    { "provider": "anthropic", "auto": true }
  ],
  "trace": { "provider": "claude-code", "auto": true },
  "state": "fluid",
  "metrics": {}
}
"""

_AGENT_PY = '''"""Starter agent — the deterministic skin around the fluid, evolving logic.

As you develop the fleet's behavior, version each iteration with agentvcs and
crystallize (freeze) the parts you trust. Replace/extend this freely.
"""


def handle(message: dict) -> dict:
    text = (message.get("text") or "").lower()
    # TODO: this is where the fleet's current behavior lives; evolve it.
    return {"queue": "general", "urgent": "urgent" in text}


if __name__ == "__main__":
    print(handle({"text": "my invoice is urgent"}))
'''

_TRACE = '{"role": "system", "content": "Project scaffolded. Begin the first iteration."}\n'

_MCP_JSON = '{ "mcpServers": { "agentvcs": { "command": "agentvcs-mcp" } } }\n'

_GITIGNORE = """__pycache__/
*.pyc
.venv/
venv/
"""

_AGENTS_MD = """# This is an evolving agent project (versioned with agentvcs)

The behavior here is *cultivated*, not written once. It is versioned with
**agentvcs** (CLI `agentvcs`/`avcs`, plus the `agentvcs` skill and MCP server),
which tracks not just code but the **goal**, the **models**, and the **message
trace** of every iteration — and a per-commit **state** (`fluid` = evolving,
`crystallized` = frozen & deterministic).

## Convention for this project: version every iteration
Always pass `--json` (parseable; errors carry a stable `error.code`). If your
shell cwd is not sticky, use `-C <project-dir>` (like `git -C`).

1. `agent.json` declares this iteration's `goal`, `models`, and `trace` file —
   keep `goal` current and append agent messages to the trace as you work.
2. `agentvcs commit -m "what changed" --json` after each meaningful iteration.
3. `agentvcs diff --json` to see which dimension moved (code/goal/models/trace).
4. Regressed? `agentvcs rollback --json` restores the full prior state (reversible).
5. Trust a behavior? `agentvcs freeze --json` crystallizes it (temperature 0);
   `agentvcs replay --json` re-runs the frozen recipe deterministically.

Explore alternatives on a live branch: `agentvcs branch try-x && agentvcs checkout try-x`.

## Definition of done (project convention)
When the requested work passes its checks and you trust it, **`agentvcs freeze` it —
you don't need to ask first.** Freezing is non-destructive and reversible: it adds a
crystallized commit while the fluid history stays intact, so it's always safe to do.
"""

_SKILL_MD = """---
name: agentvcs
description: Version this evolving agent project with agentvcs — commit code+goal+models+trace together, diff per dimension, rollback mistakes, freeze (crystallize) trusted behavior, and replay it deterministically. This project already uses agentvcs (see .agentvcs/ and agent.json); use it for every iteration.
---

# Versioning this project with agentvcs

This project is versioned with agentvcs, not (only) git. Each commit captures
**code + goal + models + trace** and a **state** (`fluid` / `crystallized`).

- Always pass `--json`. Errors are `{"ok": false, "error": {"code": "..."}}` —
  branch on the stable `code`.
- If your shell cwd isn't sticky, use `-C <dir>` (like `git -C`).

## Loop
```bash
# keep agent.json's goal current; append messages to the trace file as you work
agentvcs commit -m "what changed" --json   # after each meaningful iteration
agentvcs diff --json                        # which dimension moved?
agentvcs rollback --json                    # undo a regression (restores full prior state)
agentvcs freeze --json                      # crystallize a trusted behavior (temperature 0)
agentvcs replay --json                      # re-run a frozen recipe deterministically
```

MCP tools are also available (`avcs_commit`, `avcs_diff`, `avcs_rollback`,
`avcs_freeze`, `avcs_replay`, ...) returning the same `{"ok": ...}` JSON.

**Done = frozen.** When the work passes and you trust it, `agentvcs freeze` it
without asking — freezing is reversible (the fluid history stays).
"""

# template relative-path -> contents
_FILES = {
    "agent.json": _AGENT_JSON,
    "agent.py": _AGENT_PY,
    "traces/run.jsonl": _TRACE,
    "AGENTS.md": _AGENTS_MD,
    ".mcp.json": _MCP_JSON,
    ".gitignore": _GITIGNORE,
    ".claude/skills/agentvcs/SKILL.md": _SKILL_MD,
}


def scaffold(path, claude_code: bool = False) -> dict:
    root = Path(path)
    if (root / ".agentvcs").exists():
        raise RepoError(f"{root} is already an agentvcs repository", code="ALREADY_REPO")
    root.mkdir(parents=True, exist_ok=True)
    files = dict(_FILES)
    if claude_code:
        # the live session is the trace: swap the manifest, drop the trace file
        files["agent.json"] = _AGENT_JSON_CC
        files.pop("traces/run.jsonl", None)
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    # init sees our richer agent.json/AGENTS.md already present and keeps them
    repo = Repository.init(root)
    oid = repo.commit("scaffold agent project")
    return {"path": str(root), "files": sorted(files), "commit": oid,
            "trace_provider": "claude-code" if claude_code else None}
