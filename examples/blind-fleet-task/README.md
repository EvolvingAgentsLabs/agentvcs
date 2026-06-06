# Fair blind test (the real adoption question)

The naive blind test ([`../claude-code-task/`](../claude-code-task/) in blind mode)
starts from an **empty** directory and a throwaway task. A real agent scored **0/6**
there — and that's correct: nobody reaches for a "VCS for agents" to write a 30-line
script from scratch, and the skill's trigger rightly didn't fire.

This harness tests the question that actually matters for adoption:

> When an agent works in a project that **already uses agentvcs** (the realistic
> case once `agentvcs new` / a template / the cloud onboarded it), does the
> pre-wired context — `agent.json`, `AGENTS.md`, the skill, `.mcp.json`, existing
> history — make it adopt the loop **without being told to**?

## Run it

```bash
bash examples/blind-fleet-task/setup.sh         # scaffolds sandbox/ via `agentvcs new`
cd examples/blind-fleet-task/sandbox
claude                                           # paste ../TASK.md — add NO agentvcs hint
python3 ../../claude-code-task/score.py .        # 6-point adoption scorecard
```

(Install the CLI first — `pip install -e .` at the repo root — so `agentvcs`/
`agentvcs-mcp` are on PATH for the agent and the MCP server.)

## What makes this fair

- The task ([`TASK.md`](TASK.md)) is a genuine **multi-step, evolving** change to an
  existing agent — agentvcs's actual use case — not a blank one-shot script.
- It never mentions agentvcs. Adoption can only come from the project's context.
- The skill's trigger (“this project already uses agentvcs”) now legitimately
  matches, because `.agentvcs/` and `agent.json` exist.

A strong result here (≥5/6) is the real signal: **agentvcs's wedge is being present
in the project, and `agentvcs new` is how it gets there.**
