# Plan: validate the agentvcs × eve integration against a real eve runtime

**Status:** the offline reproduction (`demo.sh`, replaying a hand-written trace
fixture) runs end-to-end. The **real** integration — the bridge hook firing
against a live eve runtime — has **not** been tested yet. This is the plan to do
that and record a GIF from the real session.

## Prerequisites (one-time, you provide)

1. **Node 24+** — eve requires it. (A machine with Node 20 must
   `nvm install 24 && nvm use 24`.)
2. **A model API key** — one of:
   - `AI_GATEWAY_API_KEY` (Vercel AI Gateway), or
   - `VERCEL_OIDC_TOKEN` (via `vercel link`), or
   - `ANTHROPIC_API_KEY` (direct Anthropic).
   eve's default model is `anthropic/claude-sonnet-4.6`.

Tooling already present on the dev machine: `vhs`, `agg`, `ffmpeg` (for the GIF),
and `agentvcs` (run from a checkout with `PYTHONPATH=src python3.12 -m agentvcs.cli`).

Once Node 24 + a key are in place, every phase below is runnable without further
human input beyond approving commands.

## Phase 1 — Scaffold a real eve agent

```bash
npx eve@latest init eve-refund-agent
cd eve-refund-agent && npm install
```

**Checkpoint:** `agent/agent.ts` and `agent/instructions.md` exist (confirms the
filesystem-first layout the integration assumes).

## Phase 2 — Install the bridge hook + refund instructions

```bash
mkdir -p agent/hooks
cp <agentvcs-repo>/examples/eve/agent/hooks/agentvcs.ts agent/hooks/agentvcs.ts
cp <agentvcs-repo>/examples/eve/agent/instructions.md   agent/instructions.md
```

**The single most important checkpoint of the whole plan:** run one real turn and
verify the hook actually writes `.eve/agentvcs/trace.jsonl`, and that the real
event names/fields match what the provider expects.

```bash
npx eve dev      # interactive TUI; send: "Add a refund handler tool."
head .eve/agentvcs/trace.jsonl
```

If the real `event.data.*` fields differ from the assumed shape (`message`,
`toolCalls`, `usage`, `reasoning`), **adjust `src/agentvcs/traces/vercel_eve.py`**
to the real shape. This validates (or corrects) the core unknown: how eve's
Workflow SDK surfaces events through hooks. **This is the real objective of the
test.**

## Phase 3 — Version it with agentvcs

```bash
echo ".eve" > .agentvcsignore
agentvcs init --eve
agentvcs commit -m "turn 1: add refund tool"
agentvcs show --trace     # should render the REAL turn (thinking/tool_use/tool_result)
agentvcs runtime          # real budget/tokens reconstructed from the Workflow SDK
```

**Checkpoint:** `show --trace` renders the real conversation; `runtime` reports
real token usage.

## Phase 4 — Produce the bad turn (for the rollback + resume story)

A real agent won't hallucinate on cue, so for a reproducible GIF there are two
paths:

- **(A) Authentic:** let it run several turns and capture the first real build
  failure. Most honest, but unpredictable timing.
- **(B) Seeded (recommended for the GIF):** ask for a change likely to break the
  build (e.g. *"use Vercel's dedupe API"* — agents often invent a nonexistent
  import), or make a breaking edit yourself. **agentvcs versions the filesystem
  regardless of who edited it**, so the rollback demo is just as real.

```bash
# after the turn that breaks the build:
agentvcs commit -m "turn 2: idempotency"
agentvcs show --trace     # the failure is captured (turn.failed / bad import)
agentvcs rollback         # restore code + trace of the good turn, in one undo
npx eve dev               # resume the eve session from the restored state
```

**Checkpoint:** after `rollback`, the tool file is back to the good version and
eve can continue the session.

## Phase 5 — Record the GIF (with `vhs`)

Write `examples/eve/record.tape` (a vhs script) that runs the sequence
`commit → show --trace → rollback → resume` and exports
`examples/eve/eve-rollback.gif`, recorded over the **real** Phase 4 session.

## Risks / what might break

- **Event vocabulary differs** from the assumed shape → caught in Phase 2; a few
  minutes to fix in the provider.
- **eve writes the trace under a different `.eve/` path** → the provider already
  has an `rglob` fallback over `.eve/`, but confirm it resolves.
- **Node 24 / beta instability** → if eve won't start, document it and fall back
  to the offline `demo.sh` GIF.

## What's needed to start

Node 24 + one model API key. With those in place, run Phases 1–5 and produce the
real GIF. Until then, `bash examples/eve/demo.sh` is the working offline
stand-in.
