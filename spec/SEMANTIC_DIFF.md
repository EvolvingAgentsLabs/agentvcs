# Semantic diff (v0.1)

`diff(A, B)` compares two manifests dimension by dimension. Its output is
normative only in the fields listed here; implementations may add a `display`
field (e.g. a unified text diff) that conformance ignores.

```json
{
  "from": "b3:…", "to": "b3:…",
  "identical": false,
  "changes": [
    {"dimension": "extract.prompt", "kind": "prompt", "op": "modified", "details": { … }}
  ]
}
```

- `changes` is sorted by `dimension` (UTF-16 code-unit order, as in JCS).
- A dimension whose `content_hash` is equal on both sides produces no change.
- `identical` is `true` iff `changes` is empty (equivalently, `from == to`).

## Operations

| `op` | when | `details` |
|---|---|---|
| `added` | dimension only in B | `{"content_hash": B.hash}` |
| `removed` | dimension only in A | `{"content_hash": A.hash}` |
| `kind_changed` | same name, different kind | `{"from_kind", "to_kind", "from_hash", "to_hash"}` |
| `modified` | same name and kind, different hash | per kind, below |

## `modified` details per kind

### Field diff (used by every kind)

A **field diff** walks two JSON values in parallel:

- two objects recurse by key; a key only on one side yields `added`/`removed`;
- anything else (scalars, arrays, or an object vs a non-object) is a leaf, compared
  by canonical form (so `1` equals `1.0`; arrays compare as whole values);
- each difference is `{"path": <JSON Pointer, RFC 6901>, "op": "added"|"removed"|"changed", "from"?, "to"?}`
  (`from` absent on `added`, `to` absent on `removed`);
- the list is sorted by `path` (code-unit order).

### `prompt`

```json
{"template": {"lines_added": 2, "lines_removed": 1},
 "variables_added": ["cap_amount"], "variables_removed": [],
 "fields": [ field diff of content minus "template" and "variables" ]}
```

- `template` is `null` when the template is unchanged.
- Lines are the result of splitting the template on `"\n"` exactly (a trailing
  newline yields a final empty line). With `L` = length of a longest common
  subsequence of the two line lists, `lines_removed = len(A) − L` and
  `lines_added = len(B) − L`. These counts do not depend on which diff algorithm
  produced the LCS.
- Variable lists are compared as sets; outputs are sorted.

### `sampling`, `model`, `router`, `config`

```json
{"fields": [ field diff of content ]}
```

### `tool`

```json
{"code_changed": true, "signature_changed": false, "fields": [ field diff of content ]}
```

`code_changed` ⇔ `code_hash` differs; `signature_changed` ⇔ `signature` differs
canonically.

### `adapter`

```json
{"weights_changed": true, "fields": [ field diff of content ]}
```

Weights are identified by hash only; there is no diff of weights.
