# @agentvcs/eve

Zero-friction [agentvcs](https://github.com/EvolvingAgentsLabs/agentvcs) trace
bridge for [Vercel eve](https://eve.dev). eve answers *how to run and schedule* an
agent; agentvcs answers *how to version, audit and undo* it. This package is the
one-line glue.

## Install (zero config)

From the root of your eve project:

```bash
npx @agentvcs/eve init
```

That drops a self-contained hook at `agent/hooks/agentvcs.ts` and, if you don't have
one yet, an eve-wired `agent.json`. Every turn is then captured to
`.eve/agentvcs/trace.jsonl`. It's idempotent and never overwrites without `--force`.

Then version it:

```bash
agentvcs init --eve            # if the repo isn't initialized yet
agentvcs commit -m "first refunds flow"
agentvcs ui                    # time-travel debug the session
```

## Or wire it yourself

If you'd rather manage the hook file, just re-export:

```ts
// agent/hooks/agentvcs.ts
export { default } from "@agentvcs/eve";
```

and set in `agent.json`:

```json
"trace": { "provider": "vercel-eve", "auto": true }
```

## Why a hook

eve keeps its durable session state inside the Workflow SDK — there's no stable
on-disk transcript a VCS can read. eve *does* expose hooks: this one subscribes to
the `*` stream event and persists every `session.started` / `message.completed` /
`action.result` / `turn.failed` event verbatim. We own both sides of that seam, so
it survives eve being in beta — when eve's internal state format changes, the event
vocabulary the agentvcs `vercel-eve` provider reads does not.

## What you get

- **Time-travel debugging** — `agentvcs rollback` to the exact turn an agent went
  wrong (the failure markers are captured, so you can find it).
- **Cost & context visibility** — `agentvcs runtime` reconstructs tokens, `$` cost
  and context pressure from the captured `usage` the runtime otherwise hides.
- **Versioned evolution** — every commit captures code + goal + models + trace; diff
  per dimension to see *what* changed.
- **Optional audit/identity** — opt into `--with-soul` (signed provenance) or
  `--corporate` (a legal statute + Libro de Actas) when the agent handles real value.

## Env

| Variable | Effect |
|----------|--------|
| `AGENTVCS_TRACE` | Redirect the output file (default `.eve/agentvcs/trace.jsonl`) |
| `AGENTVCS_TRACE_OFF=1` | Disable capture without removing the hook (e.g. in prod) |

## CLI

```
npx @agentvcs/eve init [dir] [--force] [--json]
```

`--json` emits a single `{ ok, ... }` object (for scripts/agents). `--force`
overwrites an existing hook file.
