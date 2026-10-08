You are resolving a three-way merge of an agent harness manifest for agentvcs.

A harness manifest describes how a system of agents runs: named dimensions such as a prompt, a model,
sampling parameters, a router or a tool configuration, each with a `kind` and a `content`. Two lines,
`ours` and `theirs`, diverged from a common `base`. agentvcs has already merged every dimension that
only one side changed; what is left are the conflicts, where both sides changed the same dimension
differently. The goal is the harness that does its job best, keeping what each side got right.

Your working directory contains:

- `prepare.json`: the output of `agentvcs merge prepare` for this merge. It holds the `merge_id`, the
  dimensions that merged mechanically (`auto`), and every conflict with its three versions (`base`,
  `ours`, `theirs`; an absent side is `null`), the semantic diff of each side against base
  (`diff_ours`, `diff_theirs`), and `evidence`: for each side, the patches its recorded run applied
  to that dimension, with the author's rationale, the gate result and the metric deltas agentvcs
  attributed to the patch (`blame`; `null` when the patch is attributed jointly with others). The
  evidence is what the runtime observed, not a verdict, and it may be empty.
- `base.json`, `ours.json`, `theirs.json`: the three manifests.
- `BRANCHES.md` (only when runs were given): each side's patch rationales, in the order they were
  applied: what each side was trying to change.

Besides reading files in this directory, you have two tools, bound to this merge:

- `prepare` (no arguments): returns the prepare output again.
- `commit` (argument `resolution`: the resolution object below): validates the resolution and stages
  it. When it returns `"ok": true` the merge is done; agentvcs commits it after this session ends. If
  it returns an error, read the error code and message, fix the resolution and call `commit` again.

The resolution:

```json
{
  "protocol": "agentvcs/0.1",
  "type": "merge_resolution",
  "merge_id": "<the merge_id from prepare.json>",
  "resolutions": {
    "<dimension>": {"take": "ours"},
    "<dimension>": {"kind": "<the dimension's kind>", "content": { "...": "new content" }}
  },
  "rationale": "<why, in a few sentences, citing the evidence you relied on>",
  "author": {"type": "agent", "id": "claude-code"}
}
```

Rules:

- Every conflict gets exactly one entry, keyed by its dimension. Do not add entries for dimensions
  that are not conflicts.
- An entry is either `{"take": "ours" | "theirs" | "base" | "delete"}` or new content you write,
  with its `kind`, for example a prompt that combines the parts of both sides that each side needed.
  `take` must name a side where the dimension exists; to drop a dimension use `delete`.
- New content must be valid for its kind and keep the fields the other versions of that dimension
  have (for a prompt, keep `variables` consistent with the placeholders in the template).

Decide each conflict on its merits: read both diffs against base, work out what each side was
trying to fix, and use the evidence to judge whether it worked (a gated patch with a positive metric
delta is stronger than an untested edit; a change whose stated intent the other side does not
contradict can often be kept alongside it). Prefer combining both sides when they changed different
things for compatible reasons; take one side when they truly disagree, and say why.

You can only read files in this directory and call `prepare` and `commit`. Finish with one short
paragraph saying what you chose for each conflict and why.
