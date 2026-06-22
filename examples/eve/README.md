# agentvcs × Vercel eve — Time-Travel Debugging for filesystem-first agents

[Vercel **eve**](https://eve.dev) builds durable agents as ordinary files
(`agent.ts`, `instructions.md`, `tools/`, `skills/`, `hooks/`). eve solves
*writing and running* an agent. **agentvcs** adds the missing piece: when an eve
agent hallucinates on turn 7 of a 10-tool chain, the developer can `rollback` to
turn 6 — **code and trace restored together in one commit** — fix the tool file,
and **resume the eve session** instead of restarting it.

The fit is structural, not cosmetic. eve already splits an agent into the same
dimensions agentvcs versions:

| agentvcs dimension | eve files |
| --- | --- |
| `code`   | `agent/tools/`, `agent/hooks/`, `agent/subagents/` |
| `goal`   | `agent/instructions.md`, `agent/skills/` |
| `models` | `agent/agent.ts` |
| `trace`  | the Workflow SDK durable run — captured via the hook below |

## See it now (no Vercel account needed)

```bash
bash examples/eve/demo.sh
```

It replays a captured eve session where the agent adds a refund tool (turn 1,
green), then **hallucinates `@vercel/magic-dedupe`** and the build fails
(turn 2). You'll watch `agentvcs show --trace` surface the failure, `agentvcs
rollback` restore the good turn, and the session resume with a real fix. This is
the 60-second demo to record.

## How the trace is captured (the real integration)

eve keeps its durable state inside the [Workflow SDK](https://workflow-sdk.dev)
— there is no stable on-disk transcript to read, the way Claude Code or qwen-code
leave one. eve *does* expose the right seam: **hooks**. The bundled
[`agent/hooks/agentvcs.ts`](agent/hooks/agentvcs.ts) subscribes to the `*` stream
event and appends every `session.started` / `message.completed` / `action.result`
/ `turn.failed` event to:

```
<project>/.eve/agentvcs/trace.jsonl
```

We own **both sides** of that seam — the hook writes the events, the
`vercel-eve` provider reads them — so the integration survives eve being in
beta: when eve's *internal* state format changes, the hook's event vocabulary
does not.

### Wire it into a real eve project

```bash
# 1. drop the bridge hook into your eve agent
cp examples/eve/agent/hooks/agentvcs.ts <your-eve-app>/agent/hooks/agentvcs.ts

# 2. version it — this writes agent.json with the vercel-eve trace provider
cd <your-eve-app>
agentvcs init --eve

# 3. run your eve agent as usual; then snapshot whenever you like
agentvcs commit -m "turn N"     # captures code + goal + models + the eve trace
agentvcs show --trace           # render the conversation that actually ran
agentvcs rollback               # undo a bad turn; resume the eve session from here
```

`.eve/` is in [`.agentvcsignore`](.agentvcsignore) on purpose: the event log is
captured as the **trace** dimension (normalized messages), so it must not also
be tracked as **code**. That keeps `code` to your agent's source and lets
`rollback` restore source files without clobbering eve's live, append-only log.

## What the provider maps

[`src/agentvcs/traces/vercel_eve.py`](../../src/agentvcs/traces/vercel_eve.py)
normalizes eve events into the exact `{role, content, model, ts}` shape the
Claude Code and qwen-code providers emit — so diff, render, crystallize and the
dashboard never learn the trace came from eve:

| eve stream event | agentvcs turn |
| --- | --- |
| `session.started` | user message (the inbound prompt) |
| `message.completed` | assistant turn: `[thinking]` + text + `[tool_use]` |
| `action.result` | `[tool_result]` (flagged `is_error` on failure) |
| `turn.failed` / `session.failed` | a visible failure marker — the step you roll back to |
| `*.usage` | tokens/cost/context for `agentvcs runtime` (mode: runtime) |
