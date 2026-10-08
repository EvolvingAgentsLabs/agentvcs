# Merge (v0.2 draft)

Status: **draft** — adds merge to protocol v0.1 without changing any v0.1 object.
Ledger entries, manifests, diff, verify and blame are unchanged; a v0.1 ledger stays valid.

## What it is for

Two lines of a harness diverge from a common manifest — a team edits a prompt in git while a
supervisor hot-patches the sampling of a running system, or two supervisors patch two runs. Merging
them is three-way, **dimension by dimension**. Most dimensions merge mechanically; the ones that
conflict need judgment about *what each side was trying to fix and whether it worked*. agentvcs does
the mechanical part, hands each real conflict to an agent (Claude Code, Codex, OpenCode, a human)
**with the evidence it has**, checks the agent's resolution, gates the merged manifest, and records
the decision. The runtime never decides a conflict by itself, and the agent never writes the store
directly.

```
merge prepare  →  agent resolves conflicts (its own intelligence + the evidence)  →  merge commit
 (mechanical,       resolution.json: per conflict take ours/theirs/base/delete       (validates,
  evidence)         or new content, plus a rationale                                  snapshots, gates,
                                                                                      records)
```

## 1. Mechanical rules

For each dimension name `d` in `base ∪ ours ∪ theirs`, with `b`, `o`, `t` its identity
`(kind, content_hash)` on each side (or *absent*). The kind is part of the identity: a change of kind
with identical content (`config {"x":1}` → `router {"x":1}`) is a change, although the hash is equal
(ADR-0008 §2):

| case | result | `resolution` |
|---|---|---|
| `o == t` (including both absent) | take `o` | `same` |
| `o == b`, `t != b` | take `t` (may add or delete) | `theirs` |
| `t == b`, `o != b` | take `o` (may add or delete) | `ours` |
| otherwise | **conflict** | — |

Conflict types, by which sides are absent: `modify/modify` (all present), `modify/delete`,
`delete/modify`, `add/add` (`b` absent, `o != t`).

`merge_id` = `hash({"protocol", "base", "ours", "theirs"})` over the three manifest ids. It names the
question, not the answer: the same three manifests always give the same `merge_id`.

## 2. `merge prepare`

```
agentvcs merge prepare --base <m> --ours <m> --theirs <m>
                       [--ours-run <run>] [--theirs-run <run>] [--metric <name>]... --json
```

Manifests are ids in the store or paths to manifest files. Output (normative fields):

```json
{
  "ok": true, "merge_id": "b3:…", "base": "b3:…", "ours": "b3:…", "theirs": "b3:…",
  "auto": [{"dimension": "extract.model", "resolution": "theirs"}],
  "conflicts": [{
    "dimension": "extract.prompt", "kind": "prompt", "type": "modify/modify",
    "base":   {"kind": "prompt", "content": {…}, "content_hash": "b3:…"},
    "ours":   {"kind": "prompt", "content": {…}, "content_hash": "b3:…"},
    "theirs": {"kind": "prompt", "content": {…}, "content_hash": "b3:…"},
    "diff_ours":   { SEMANTIC_DIFF change base → ours for this dimension },
    "diff_theirs": { SEMANTIC_DIFF change base → theirs for this dimension },
    "evidence": {"ours": [ … ], "theirs": [ … ]}
  }]
}
```

- `auto` and `conflicts` are sorted by dimension (code-unit order). A side that is absent is `null`.
- `diff_*` is the single change object `diff(base, side)` reports for `d` (or `null` if unchanged).

### Evidence

When `--ours-run` / `--theirs-run` name runs in the store (or paths to audit bundles, as `verify` and
`blame` accept), `evidence.<side>` lists every **patch in
that run's ledger whose `semantic_diff` touches `d`**, in ledger order:

```json
{"patch_id": "b3:…", "applied_at_step": 2051, "rationale": "…", "author": {…},
 "gate": {"passed": true, "metrics": {…}} | null,
 "blame": {"extract.recall": 0.442, …}}
```

`blame` holds, for each `--metric`, the `delta` of the blame attribution whose `patches` contain this
patch (`null` if the metric is absent or the patch is attributed jointly with others — the evidence
says so rather than splitting it). Evidence is what the runtime *observed*; it is not a verdict, and
spec/BLAME.md's caveat applies (a segment boundary is not causation). Without a run, `evidence.<side>`
is `[]`. A run whose ledger does not `verify` is refused (`E_INVALID_LEDGER`), as `blame` refuses it.

## 3. The resolution an agent writes

```json
{
  "protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": "b3:…",
  "resolutions": {
    "extract.prompt": {"take": "theirs"},
    "extract.sampling": {"content": {"temperature": 0.1, "grammar": "…"}, "kind": "sampling"}
  },
  "rationale": "ours fixed cap extraction (+0.44 recall, gated); theirs only reworded; kept ours' field
                list and theirs' citation line",
  "author": {"type": "agent", "id": "claude-code"}
}
```

`take` ∈ `ours`, `theirs`, `base`, `delete`. A `content` resolution is new content for that dimension
(the agent's synthesis) and carries its `kind`.

## 4. `merge commit`

```
agentvcs merge commit --base <m> --ours <m> --theirs <m> --resolution <file>
                      [--suite <suite.yaml>] --json
```

Checks, in order (exit 3 unless noted):

| check | code |
|---|---|
| resolution matches its schema | `E_SCHEMA` |
| `merge_id` equals the prepared one | `E_MERGE_STALE` |
| every conflict has exactly one resolution | `E_MERGE_UNRESOLVED` |
| no resolution for a dimension that is not a conflict | `E_MERGE_EXTRA` |
| `take` is one of `ours`, `theirs`, `base`, `delete` | `E_SCHEMA` |
| `take` names a side that exists for that dimension (`take: ours` on a dimension ours deleted is an error; use `delete`) | `E_MERGE_TAKE` |
| `content` resolutions validate as their kind (spec/PROTOCOL.md §2.1) | `E_SCHEMA` / `E_UNKNOWN_KIND` |

Then: build the merged manifest (auto results + resolutions; `parent_ids: [ours, theirs]`),
snapshot it, store a **merge record** and, with `--suite`, run the suite's command on the merged
manifest exactly as `gate run` does (`AGENTVCS_MANIFEST_FILE` = the merged manifest,
`AGENTVCS_FROM_MANIFEST` = `ours`). A failed gate is exit 1 (`"gate": {"passed": false}`); the merge
record is still stored — a rejected merge is history too.

```json
{"ok": true, "merge_id": "b3:…", "merged": "b3:…", "record": "b3:…",
 "gate": {"passed": true, "metrics": {…}} | null}
```

### Merge record (stored object)

```json
{"protocol": "agentvcs/0.1", "type": "merge_record", "merge_id": "b3:…",
 "base": "b3:…", "ours": "b3:…", "theirs": "b3:…", "merged": "b3:…",
 "auto": [ … ], "resolution": { the resolution file }, "gate": { … } | null}
```

`record` = `hash(merge record)`.

## 5. Applying a merge to a running system

Nothing new: it is a patch from the run's active manifest (normally `ours`) to `merged`, proposed,
gated and applied as any other (spec/PROTOCOL.md §3.3). Its `rationale` should cite the merge record
(`merge:<record>`), so `blame` attributes what the merge changed to the patch that brought it in.

## 6. Resolving with Claude Code — `merge resolve`

agentvcs has no model of its own. When a merge needs judgment, it delegates to **Claude Code** — the
only LLM agentvcs uses — and keeps every guarantee on its side: the agent proposes, the runtime
verifies, commits and records. (The local models agentvcs versions are the system it controls, never
part of agentvcs.)

```
agentvcs merge resolve --base <m> --ours <m> --theirs <m>
                       [--ours-run r] [--theirs-run r] [--metric m]... [--suite s]
                       [--model <claude model>] [--budget-usd <x>] [--max-turns <n>] [--claude <path>]
                       [--dry-run] --json
```

1. **Prepare** exactly as §2. If there are no conflicts, commit mechanically (§4) without invoking any
   agent (`resolver: null`).
2. **Workspace.** A fresh temporary directory holding only `prepare.json`, `base.json`, `ours.json`,
   `theirs.json` and, when runs are given, `BRANCHES.md` (each side's patch rationales, in ledger order).
3. **Tools.** The agent gets exactly two MCP tools from `agentvcs mcp --merge-session <dir>`, bound to this
   merge: `prepare` (no arguments; the prepare output) and `commit` (argument: the resolution object of
   §3). `commit` validates (§4 checks) and **stages** the resolution; nothing is committed to the store
   while the agent runs.
4. **Invocation** (the isolation recipe validated by experiment M0, where an allow-list alone let a
   `Bash` call through): `claude -p --output-format stream-json --verbose --restricted
   --strict-mcp-config --disable-slash-commands --no-session-persistence --permission-mode dontAsk
   --permission-prompts none --tools Read --allowedTools Read,mcp__agentvcs__prepare,mcp__agentvcs__commit
   --mcp-config <file> --append-system-prompt <built-in resolver prompt> [--model] [--max-budget-usd]
   [--max-turns]`, working directory = the workspace, task on stdin. No Bash, no Write, no network tools;
   Read is confined to the workspace by `--restricted`.
5. **Audit before commit.** After the session ends the runtime reads the transcript and refuses the
   staged resolution if the agent called any tool outside the three allowed ones, or a `Read` outside
   the workspace — even if the call was denied (`E_RESOLVER_ESCAPED`, exit 5). Otherwise it commits the
   staged resolution as §4 (with `--suite`, gated).
6. **Record.** The merge record gains a `resolver` object (absent for `merge commit`, so v0.2 record
   hashes are unchanged):
   `{"agent": "claude-code", "version": "<claude --version>", "model": "…", "cost_usd": x, "turns": n,
   "transcript": "b3:…"}` — the transcript is stored as a blob. The resolution's `author` is
   `{"type": "agent", "id": "claude-code"}`.

Errors: `E_RESOLVER_NOT_FOUND` (no `claude` on PATH or at `--claude`; exit 4), `E_RESOLVER_NO_COMMIT`
(the session ended without a valid staged resolution; exit 1, nothing committed),
`E_RESOLVER_ESCAPED` (exit 5). `--dry-run` writes the workspace and prints the exact command without
running it.

## 7. What v0.2 leaves out

- Merging ledgers or runs; octopus merges (more than two sides).
- Field-level auto-merge inside a dimension (two sides edit different fields of the same `sampling`):
  it is a conflict in v0.2 and the agent sees both field diffs. Whether auto-merging it is safe is an
  empirical question for M0, not a spec decision.
