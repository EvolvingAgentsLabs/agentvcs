# agentvcs on-disk format — v0

This document specifies the repository format. It is the standard we are
proposing for versioning evolving agent systems; any implementation that reads
and writes these objects is compatible. Format version: **0** (alpha, may change
before 1.0).

## 1. Repository layout

```
.agentvcs/
  HEAD                     # "ref: refs/heads/<branch>\n"  or a raw commit id (detached)
  refs/heads/<branch>      # a single 64-hex commit id per branch
  objects/<aa>/<rest>      # content-addressed objects (see §3)
agent.json                 # working-tree manifest declaring the non-code dimensions
.agentvcsignore            # optional, fnmatch patterns, one per line
```

## 2. The manifest — `agent.json`

The manifest declares the three non-code dimensions for the *current* working
tree. `agentvcs commit` reads it together with a snapshot of the files.

```json
{
  "goal": "string — the high-level objective",
  "parent_goal": "string|null — optional lineage of the goal itself",
  "models": [
    {
      "provider": "string",
      "model": "string",
      "version": "string|null",
      "params": { "temperature": 1.0, "...": "any json" }
    }
  ],
  "trace": "relative/path/to/trace.jsonl|null",
  "state": "fluid|crystallized",
  "metrics": { "any": "json — cost, tokens, eval scores, ..." }
}
```

`trace` is either a **path** to a file (`.jsonl` — one JSON message per line, or
`.json` — a JSON array / an object with a `messages` array), or a **provider**
object that auto-discovers the agent's native session log at commit time:

```json
"trace": { "provider": "claude-code", "auto": true }
```

A provider lets agentvcs *vacuum* the high-fidelity trace the agent already
produced instead of asking it to write one. Three providers ship today, all
normalizing to the same `trace` object — the on-disk format is provider-agnostic:

- **`claude-code`** reads the transcript Claude Code records under
  `~/.claude/projects/<cwd "/"→"-">/<session-uuid>.jsonl`, keeping the real
  `tool_use` / `tool_result` / `thinking` blocks. Optional keys: `session`,
  `project_dir`, `projects_dir`, `path` (bypass discovery).
- **`qwen-code`** reads gemini-cli/qwen-code checkpoints under
  `~/.qwen/tmp/<sha256(project)>/checkpoint*.json`. Optional keys: `model` (pin
  routing), `project_hash`, `qwen_dir`, `path`.
- **`vercel-eve`** reads the event stream a [Vercel eve](https://eve.dev) agent's
  bridge hook appends to `<project>/.eve/agentvcs/trace.jsonl` (eve keeps its
  durable state in the Workflow SDK, so a hook on the `*` stream event is the
  capture seam — see `examples/eve/`). Optional keys: `model`, `eve_dir`,
  `session`, `path`. It maps `session.started`→user, `message.completed`→assistant
  (`thinking`+text+`tool_use`), `action.result`→`tool_result`, and
  `turn.failed`→a visible failure marker.
- **`anthropic-managed`** reads Anthropic Managed Agents' server-side **session event
  stream** (`GET /v1/sessions/<id>/events?beta=true`, beta header
  `managed-agents-2026-04-01`) — from an exported file or a live `auto_fetch` (stdlib
  only). Optional keys: `session`, `agent_id`, `auto_fetch`, `base_url`, `api_key`,
  `anthropic_dir`, `path`, `model`. It collapses `agent.thinking`/`agent.message`/
  `agent.tool_use` into one assistant turn, maps `agent.tool_result`→`tool_result`,
  and reconstructs the runtime frame from `span.model_request_end.model_usage`.

All providers accept `redact` (a list of regexes scrubbed before storage) and
`redact_defaults: false` (keep only user patterns); known secrets are scrubbed by
default. Adding a source is one module + one registry entry in
`src/agentvcs/traces/`.

A `models` entry may also carry `"auto": true`, in which case the `model` is
filled from the model that actually produced the trace (so the pin can't drift
from reality).

**Optional dimensions.** The manifest may also carry, both off by default:

- `"mode": "runtime"` — additionally capture the operational frame (budget, context
  pressure, model routing, tool/subagent usage) as a `runtime` object per commit,
  alongside an optional `"budget": { "ceiling_usd": …, "windows": {…}, "pricing": {…} }`.
- `"corporate": { … }` — the digital statute of an autonomous legal entity
  (`entity_type`, `jurisdiction`, `liability_limits.{max_inference_usd,
  requires_human_for}`, `legal_representatives[]`). Because it lives in `agent.json`
  it is versioned and (with a Soul) signed by the tree hash like any other file; the
  policy gate and the signed *Libro de Actas* are produced by `agentvcs audit`.

When a repo has a **Soul** (`agentvcs init --with-soul`), every commit is additionally
stamped with `soul` (Ed25519 public id) and `signature` over its canonical content.

## 3. Objects

Every object is canonical JSON — `sort_keys=True`, `separators=(",", ":")`,
UTF-8, no trailing newline — hashed with **SHA-256**. The hex digest is the
object id. Storage is `objects/<id[:2]>/<id[2:]>`, zlib-compressed. Identical
content ⇒ identical id ⇒ stored once (automatic dedup across commits).

Blobs (raw file bytes) are framed as `b"blob\0" + bytes` before hashing and
storage, so a file and a JSON object with the same bytes never collide.

### 3.1 `tree` — the code dimension
```json
{ "type": "tree", "entries": { "relative/path": "<blob-id>", "...": "..." } }
```

### 3.2 `goal`
```json
{ "type": "goal", "text": "string", "parent": "string|null" }
```

### 3.3 `modelpin`
```json
{ "type": "modelpin", "provider": "string", "model": "string",
  "version": "string|null", "params": { "...": "any json" } }
```

### 3.4 `trace`
```json
{ "type": "trace", "messages": [ { "...": "any json" } ] }
```

### 3.5 `commit`
```json
{
  "type": "commit",
  "parents": ["<commit-id>", "..."],
  "tree": "<tree-id>",
  "goal": "<goal-id>",
  "models": ["<modelpin-id>", "..."],
  "trace": "<trace-id>|null",
  "state": "fluid|crystallized",
  "metrics": { "...": "any json" },
  "message": "string",
  "author": "string",
  "timestamp": 1234567890,
  "crystal": "<crystal-id>   (present only when state == crystallized)",
  "runtime": "<runtime-id>   (optional; present in runtime mode)",
  "soul": "<ed25519-pubkey-hex>   (optional; present when signed)",
  "signature": "<ed25519-sig-hex>  (optional; covers the commit minus this field)"
}
```

`parents` is a list of one or more commit ids. The first parent is the linear
ancestor `log` follows; a **merge** commit (see §5) has two — the run-time line and
the design-time line it reconciled.

### 3.6 `crystal` — the frozen recipe
Produced by `freeze`. A self-contained, deterministic replay of a fluid commit.
```json
{
  "type": "crystal",
  "source_commit": "<commit-id>",
  "goal": "string",
  "models": [ { "...": "modelpin with temperature pinned to 0" } ],
  "steps": [ { "...": "the ordered trace messages to replay" } ]
}
```

## 4. State semantics

- **fluid** — the default. The commit represents a probabilistic, still-evolving
  state. Re-running it may produce different results.
- **crystallized** — produced by `freeze`. Every model pin has `temperature: 0`
  and `top_p: 1`; the trace is captured as an ordered, replayable `steps` recipe.
  Re-running it is intended to be reproducible. A crystallized commit cannot be
  re-crystallized.

## 5. Merge & reconciliation (implemented)

`agentvcs merge <branch>` reconciles two evolving lines — canonically the **run-time
line** (what an autonomous system changed about itself in the field, captured by
agentvcs) and the **design-time line** (a new release developed under version
control). It is *multidimensional*: each dimension is reconciled in the way that
fits it, rather than as one opaque text merge.

1. **merge-base** — the lowest common ancestor over the full `parents` DAG.
2. **code (tree)** — a three-way, line-level merge against the base. Clean hunks
   auto-merge; true overlaps get git-style `<<<<<<< / ======= / >>>>>>>` conflict
   markers written into the files. Add/delete vs modify is surfaced as a conflict.
3. **models** — the model pins of both sides are unioned.
4. **goal + trace** — the *semantic* dimensions are not merged textually. agentvcs
   assembles a reconciliation **bundle** and, if `--reconcile CMD` is given, pipes it
   as JSON to that command (an agent) on stdin:

   ```json
   { "base":   { "goal": "…", "trace": [ … ] },
     "ours":   { "goal": "…", "trace": [ … ] },
     "theirs": { "goal": "…", "trace": [ … ] } }
   ```

   The command returns `{ "goal": "string", "trace": [ … ], "notes": "string" }`,
   which becomes the merged goal and trace. Without `--reconcile`, a mechanical
   fallback unions the goals and concatenates the traces so the merge still completes.
5. **commit** — a two-parent merge commit (first parent = HEAD/`ours`, second =
   `theirs`). When conflicts remain, the merge reports them and exits non-zero unless
   `--force` (which commits with the markers in place).

This is the mechanism by which run-time evolution is **not lost** at the next
release: an agent, not a textual heuristic, decides how the field-learned goal and
reasoning combine with the freshly-developed code.

## 6. Reserved for a later version (not yet implemented)

- **goal lineage queries** over `goal.parent`.
- **packed objects** for large histories.
- **richer metric-weighted reconciliation** (auto-selecting the winning side per
  hunk from recorded `metrics`/`eval` scores).
