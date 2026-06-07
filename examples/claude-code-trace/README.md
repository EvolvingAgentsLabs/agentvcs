# Zero-friction trace capture with Claude Code

This example shows the **`claude-code` trace provider**: instead of maintaining a
`traces/run.jsonl` by hand, agentvcs reads Claude Code's *native* session
transcript at commit time. The agent just works; the commit captures the real
conversation — `tool_use` / `tool_result` / `thinking` blocks and all — and the
model pin is detected from the model that actually ran.

> Unlike the other examples, this one is driven by a **real** Claude Code session,
> so its trace dimension is only populated when you run it inside Claude Code (the
> provider reads `~/.claude/projects/<cwd>/…jsonl`).

## The manifest

The only difference from a classic project is `agent.json` (see this folder):

```json
"trace": { "provider": "claude-code", "auto": true },
"models": [{ "provider": "anthropic", "auto": true }]
```

`init --claude-code` / `new --claude-code` scaffold exactly this. Known secrets
are redacted by default; the `redact` list here adds project-specific patterns.

## Run it (inside Claude Code)

```bash
# from this directory, in a Claude Code session
agentvcs init --claude-code        # or copy the agent.json here over a fresh `agentvcs init`
agentvcs trace                     # confirm which session is hooked: path, message count, model

# do some work with the agent (edit files, iterate)...

agentvcs commit -m "v1: triage queue"
agentvcs show --trace              # the commit + the exact conversation that produced it
agentvcs freeze                    # crystallize the real, high-fidelity trace → deterministic recipe
```

## What to notice

- **You never wrote a trace file.** `agentvcs trace` proves a transcript is hooked
  before you commit; `show --trace` proves the conversation is stored *with* the code.
- **`models` was `auto`** — the pin shows the model Claude Code actually used, not a
  hand-typed guess that can drift.
- **`freeze` now means something.** The crystallized recipe is built from the real
  reasoning trace, so replaying it at temperature 0 reproduces a path you actually saw.

## Pinning a specific session

By default the newest transcript for this working directory is used. To pin one:

```json
"trace": { "provider": "claude-code", "session": "<session-uuid>" }
```

or point straight at a file with `"path": "/abs/to/session.jsonl"`, or at an
encoded project dir with `"project_dir": "-Users-me-proj"`.
