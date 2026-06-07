# Tutorial: version a Claude Code project with agentvcs

A 6-step walkthrough that builds a tiny support-triage bot **with Claude Code**
and versions every iteration with agentvcs — capturing the agent's real
conversation, not just the code. By the end you'll have committed across all four
dimensions, seen a dimensional diff, undone a bad iteration, and frozen a trusted
solution into a deterministic recipe.

> **Two kinds of block below.** Lines you run in a normal shell are shown as
> shell commands with their real output. Lines that happen *inside a Claude Code
> session* are called out as **▶ In Claude Code** — that's where the agent writes
> code and reasons, and where the trace comes from.

## Prerequisites

```bash
pip install agentvcs          # or, from a clone:  pip install -e .
claude mcp add agentvcs -- agentvcs-mcp   # optional: exposes avcs_* tools to Claude Code
```

`agentvcs`, `avcs`, and `agentvcs-mcp` are now on your PATH. Add `--json` to any
command for machine-readable output.

---

## Step 1 — Scaffold a project wired to the live session

```bash
mkdir triage-bot && cd triage-bot
agentvcs init --claude-code
```
```
Initialized empty agentvcs repository in .agentvcs
Scaffolded agent.json (your goal/models/trace) and AGENTS.md (agent operating manual).
Wired the trace to the live Claude Code session (provider claude-code) — just commit; no trace file to maintain.
```

`--claude-code` writes an `agent.json` whose `trace` is a *provider*, not a file:

```json
"trace": { "provider": "claude-code", "auto": true },
"models": [{ "provider": "anthropic", "auto": true }]
```

That's the whole point: you will **never write a trace file**. (Prefer scaffolding
a richer starter? `agentvcs new triage-bot --claude-code` adds an `AGENTS.md`,
the skill, and an MCP config too.)

---

## Step 2 — Confirm which session is hooked

Before you trust the capture, check what agentvcs sees:

```bash
agentvcs trace
```
```
trace source: provider claude-code
  transcript: /Users/you/.claude/projects/-Users-you-triage-bot/3f9c….jsonl
  messages:   4   model: claude-opus-4-8
```

It found your active Claude Code transcript, counted the turns, and detected the
model — all without you logging anything. (Multiple sessions? Pin one with
`"session": "<uuid>"` in `agent.json`.)

---

## Step 3 — Build something, then commit

**▶ In Claude Code**, give the agent a normal task:

> Create a simple support-triage queue in `app.py`: classify a message and flag
> urgent ones.

It writes `app.py` and explains what it did. Now snapshot the iteration:

```bash
agentvcs commit -m "v1: triage queue"
```
```
[main 0714ea158c51] fluid v1: triage queue
```

No `traces/run.jsonl`, no flags to remember — the commit pulled the conversation
straight from the session.

---

## Step 4 — See the conversation stored *with* the code (the payoff)

```bash
agentvcs show --trace
```
```
commit 0714ea158c51c84f076282a03039df1fa60ed9bd0a75f57c04677e6665f50279
state:   fluid
author:  agent
message: v1: triage queue

goal: Build a simple support-triage queue
models:
  - anthropic/claude-opus-4-8 params={}
trace: 4 messages
  user:
    Create a simple support-triage queue in app.py: classify a message and flag urgent ones.
  assistant:  (claude-opus-4-8)
    [thinking] Start minimal: a keyword classifier with an 'urgent' flag, one function handle().
    I'll add a small triage function.
    [tool_use Write] {"content": "def handle(msg): ...", "file_path": "app.py"}
  user:
    [tool_result] File written: app.py
  assistant:  (claude-opus-4-8)
    Done — app.py routes refunds to billing and flags urgent messages.
```

That's the high-fidelity trace: the model's actual `thinking`, the `tool_use` it
issued, and the `tool_result` it got back — pinned to this exact commit. No git
can show you *why* the code looks the way it does. This can.

---

## Step 5 — Make it worse, then undo in full

**▶ In Claude Code**, ask for a change *and* redirect the goal (edit `agent.json`'s
`goal` to "Build a triage queue with fraud escalation"), commit it as `v2`, then
diff:

```bash
agentvcs diff
```
```
0714ea158c51..7eac94d90def
code
  ~ agent.json
  ~ app.py
goal
  from: Build a simple support-triage queue
  to:   Build a triage queue with fraud escalation
```

The diff tells you *which dimension moved*: code **and** the goal — a goal
redirect is now a first-class, visible event, not buried in a text diff. Don't
like v2? Hit the panic button:

```bash
agentvcs rollback
```
```
Rolled back to 0714ea158c51 (was 7eac94d90def)
  goal:  Build a simple support-triage queue
  undo this with: agentvcs checkout 7eac94d90def
```

`rollback` restores the **entire** prior state — code, goal, models, and trace —
and is itself reversible (note the recovery hint). `app.py` is back to v1.

---

## Step 6 — Freeze a trusted solution

Once v1 is the version you trust, crystallize it:

```bash
agentvcs freeze
```
```
Crystallized -> 28c18c784574
Deterministic recipe written to /…/triage-bot/crystal/0714ea158c51.json
```

```bash
agentvcs log
```
```
28c18c784574 crystallized  crystallize 0714ea158c51
    goal: Build a simple support-triage queue
0714ea158c51 fluid         v1: triage queue
    goal: Build a simple support-triage queue
```

Freeze adds a `crystallized` commit (the fluid history stays intact). Because the
recipe was built from the **real** captured trace, replaying it is meaningful —
every model is pinned to temperature 0:

```bash
agentvcs replay
```
```
replay 28c18c784574 [crystallized]
goal: Build a simple support-triage queue
models:
  - anthropic/claude-opus-4-8 params={'temperature': 0, 'top_p': 1}
steps (4):
  [0] user: Create a simple support-triage queue ...
  [1] assistant: [thinking ...][tool_use Write ...]
  ...
```

Pipe each step to your own runtime with `agentvcs replay --exec "my-runner"` to
re-execute the frozen path deterministically.

---

## What you just learned

- The `trace` is captured **passively** from Claude Code's native session — zero
  tokens spent logging, nothing for the agent to forget.
- A commit versions **code + goal + models + trace**, and `diff` isolates which one
  moved.
- `rollback` undoes a whole bad iteration; `freeze` + `replay` turn a trusted,
  high-fidelity run into a cheap deterministic recipe.

## Next steps

- Secrets are scrubbed by default; tune with `"redact": [...]` or `"redact": false`.
- The `trace` dimension is **pluggable** — `claude-code` is the first provider; the
  same interface works for any tool that records a session. See
  [`docs/SPEC.md`](SPEC.md) and the [trace-providers epic](https://github.com/EvolvingAgentsLabs/agentvcs/issues/1).
- Full agent contract and error codes: [`docs/AGENT_MODE.md`](AGENT_MODE.md).
