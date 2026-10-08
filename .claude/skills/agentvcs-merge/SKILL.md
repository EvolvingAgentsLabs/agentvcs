---
name: agentvcs-merge
description: Merge two diverged agentvcs harness manifests (ours/theirs from a common base) — run `agentvcs merge resolve`, or resolve the conflicts yourself with the merge_prepare/merge_commit MCP tools, and review the result. Use when the user asks to merge manifests, branches of a harness, or a supervisor's hot-patches with the team's edits.
---

# Merging harness manifests with agentvcs

A merge is three-way and per dimension (spec/MERGE.md). agentvcs merges what is
mechanical; conflicts need judgment. Never write the store by hand: agentvcs
validates, commits and records every merge. Always pass `--json`; branch on
`error.code`.

You need three manifests (store ids `b3:…` or files): `--base`, `--ours`,
`--theirs`. Ask for the runs behind each side (`--ours-run`, `--theirs-run`) and
the metrics that matter (`--metric`, repeatable): they become the evidence, and a
suite (`--suite`) gates the merged manifest.

## Option A: let agentvcs run the resolver (default)

```bash
agentvcs merge resolve --base <m> --ours <m> --theirs <m> \
    [--ours-run r] [--theirs-run r] [--metric m]... [--suite s.yaml] \
    [--model <claude model>] [--budget-usd 1] [--max-turns 20] --json
```

It starts a separate, sandboxed headless Claude Code (Read + this merge's
`prepare`/`commit` only), audits its transcript, and commits. Show the user
`--dry-run` first if they want to see the command. Outcomes:
- exit 0: `merged`, `record`, `gate`, `resolver` (model, cost, turns, transcript blob).
- exit 1 with `gate.passed: false`: committed and recorded, but the gate rejected it.
- `E_RESOLVER_NO_COMMIT` (1), `E_RESOLVER_ESCAPED` (5), `E_RESOLVER_NOT_FOUND` (4):
  nothing committed; report it, do not retry blindly.

## Option B: resolve it yourself in this session

1. `merge_prepare` (MCP) or `agentvcs merge prepare … --json`: read every conflict,
   both diffs against base and the evidence (gates, blame deltas).
2. Write the resolution (spec/MERGE.md §3): one entry per conflict,
   `{"take": "ours"|"theirs"|"base"|"delete"}` or `{"kind", "content"}`, a
   rationale citing the evidence, `author: {"type": "agent", "id": "claude-code"}`.
3. Show it to the user before committing, then `merge_commit` (MCP) or
   `agentvcs merge commit … --resolution res.json [--suite s.yaml] --json`.

## Review the result

`agentvcs diff <ours> <merged> --json` (and against theirs) shows what the merge
changed for each side. To apply it to a running system, propose a patch from the
run's active manifest to `merged` with `--rationale "merge:<record>"`, gate it, then
apply it.
