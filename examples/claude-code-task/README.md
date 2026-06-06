# Claude Code validation harness (the real PMF test)

The `agent-loop-demo` *simulates* an agent. This harness puts a **real** agent
(Claude Code) in front of agentvcs and measures whether it adopts the workflow.

## What it tests

> Does a real coding agent, given a normal task, choose to version its work with
> agentvcs — iterate, inspect per dimension, roll back a mistake, and freeze the
> result — because the tool makes its job easier?

If yes, you have signal for the B2A bet.

## Run it

```bash
# 1. build a fresh sandbox (installs the agentvcs skill + MCP server config)
bash examples/claude-code-task/setup.sh

# 2. drive the real agent
cd examples/claude-code-task/sandbox
claude               # paste the task from ../PROMPT.md

# 3. score what it actually did
python3 ../score.py .
```

(If the CLI isn't installed, run `pip install -e .` at the repo root first so
`avcs`/`agentvcs`/`agentvcs-mcp` are on PATH.)

## Two modes

- **Guided** (functional test): give `PROMPT.md` as-is. It asks the agent to use
  agentvcs. Confirms the tool is *usable* by an agent end-to-end.
- **Blind** (PMF signal): delete the "Working agreement" section from `PROMPT.md`
  first. The agent only has the self-advertising `agentvcs` skill. If it adopts
  agentvcs unprompted, that's the strong signal.

## Automated scorecard (`score.py`)

Reads the agentvcs repo the agent produced and scores 6 behaviors:

| ✓ | behavior | measured by |
|---|----------|-------------|
| 1 | adopted agentvcs | `.agentvcs/` exists |
| 2 | committed at least once | `agentvcs log` |
| 3 | iterated (≥3 commits) | one commit per feature |
| 4 | evolved the goal dimension | distinct `goal`s across commits |
| 5 | used `rollback` to recover | `.agentvcs/ROLLBACK_HEAD` present |
| 6 | crystallized the final solution | a crystallized commit / `crystal/` recipe |

`≥5/6` = strong adoption. Exit code is `0` on a pass, `1` otherwise (CI-friendly).

## Also watch qualitatively (the things a score can't capture)

- Did it use `agentvcs diff` to **decide** what to do, or just commit blindly?
- Did its commit messages and `agent.json` `goal` stay meaningful?
- On a failure, did it reach for `rollback` naturally, or hand-edit files back?
- Did it prefer the MCP tools or the CLI? Either is fine — note which felt natural.
- Did it *suggest* agentvcs to you (blind mode) before using it?

Capture the transcript; the friction points it hits are your highest-value backlog.
