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

The trace file is either `.jsonl` (one JSON message per line) or `.json` (a JSON
array, or an object with a `messages` array).

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
  "crystal": "<crystal-id>   (present only when state == crystallized)"
}
```

`parents` is a list to allow future merges (conciliación of live branches).
The first parent is the linear ancestor `log` follows.

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

## 5. Reserved for v1 (not yet implemented)

- **merge / conciliation**: combining two live branches by evaluating their
  recorded `metrics` and integrating the winning code + learnings. The `parents`
  list and `metrics` field already reserve space for this.
- **goal lineage queries** over `goal.parent`.
- **packed objects** for large histories.
