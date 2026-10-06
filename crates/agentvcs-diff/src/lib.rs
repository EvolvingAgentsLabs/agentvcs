//! Semantic diff of two harness manifests (`spec/SEMANTIC_DIFF.md`).

use agentvcs_core::json::{canon_eq, cmp_utf16};
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_core::Result;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

/// The result of `diff(A, B)`.
#[derive(Debug, Clone, PartialEq)]
pub struct Diff {
    pub from: String,
    pub to: String,
    pub changes: Vec<Value>,
}

impl Diff {
    pub fn identical(&self) -> bool {
        self.changes.is_empty()
    }

    /// `{"from", "to", "identical", "changes"}`.
    pub fn to_value(&self) -> Value {
        json!({
            "from": self.from,
            "to": self.to,
            "identical": self.identical(),
            "changes": self.changes,
        })
    }
}

/// Normalize two manifest values and diff them.
pub fn diff_values(a: &Value, b: &Value) -> Result<Diff> {
    Ok(diff(&normalize(a)?, &normalize(b)?))
}

/// Diff two normalized manifests.
pub fn diff(a: &Manifest, b: &Manifest) -> Diff {
    let (da, db) = (a.dimensions(), b.dimensions());
    let mut names: Vec<&String> = da.keys().chain(db.keys()).collect();
    names.sort_by(|x, y| cmp_utf16(x, y));
    names.dedup();
    let mut changes = Vec::new();
    for name in names {
        let change = match (da.get(name.as_str()), db.get(name.as_str())) {
            (Some(x), None) => json!({
                "dimension": name, "kind": x["kind"], "op": "removed",
                "details": {"content_hash": x["content_hash"]},
            }),
            (None, Some(y)) => json!({
                "dimension": name, "kind": y["kind"], "op": "added",
                "details": {"content_hash": y["content_hash"]},
            }),
            (Some(x), Some(y)) => {
                if x["kind"] != y["kind"] {
                    // reported even when the content hash is equal: the kind is part
                    // of the manifest id, so `identical` must stay false (ADR-0006 §4)
                    json!({
                        "dimension": name, "kind": y["kind"], "op": "kind_changed",
                        "details": {
                            "from_kind": x["kind"], "to_kind": y["kind"],
                            "from_hash": x["content_hash"], "to_hash": y["content_hash"],
                        },
                    })
                } else if x["content_hash"] == y["content_hash"] {
                    continue;
                } else {
                    let kind = x["kind"].as_str().unwrap_or_default();
                    json!({
                        "dimension": name, "kind": kind, "op": "modified",
                        "details": details(kind, &x["content"], &y["content"]),
                    })
                }
            }
            (None, None) => unreachable!(),
        };
        changes.push(change);
    }
    Diff {
        from: a.manifest_id.clone(),
        to: b.manifest_id.clone(),
        changes,
    }
}

fn details(kind: &str, a: &Value, b: &Value) -> Value {
    match kind {
        "prompt" => {
            let ta = a["template"].as_str().unwrap_or_default();
            let tb = b["template"].as_str().unwrap_or_default();
            let template = if ta == tb {
                Value::Null
            } else {
                let la: Vec<&str> = ta.split('\n').collect();
                let lb: Vec<&str> = tb.split('\n').collect();
                let l = lcs_len(&la, &lb);
                json!({"lines_added": lb.len() - l, "lines_removed": la.len() - l})
            };
            let vars = |c: &Value| -> BTreeSet<String> {
                c.get("variables")
                    .and_then(Value::as_array)
                    .map(|a| {
                        a.iter()
                            .filter_map(|v| v.as_str().map(str::to_owned))
                            .collect()
                    })
                    .unwrap_or_default()
            };
            let (va, vb) = (vars(a), vars(b));
            fn sorted(mut s: Vec<&String>) -> Vec<&String> {
                s.sort_by(|x, y| cmp_utf16(x, y));
                s
            }
            let rest = |c: &Value| {
                let mut m = c.as_object().cloned().unwrap_or_default();
                m.remove("template");
                m.remove("variables");
                Value::Object(m)
            };
            json!({
                "template": template,
                "variables_added": sorted(vb.difference(&va).collect()),
                "variables_removed": sorted(va.difference(&vb).collect()),
                "fields": field_diff(&rest(a), &rest(b)),
            })
        }
        "tool" => json!({
            "code_changed": a.get("code_hash") != b.get("code_hash"),
            "signature_changed": !canon_eq(
                a.get("signature").unwrap_or(&Value::Null),
                b.get("signature").unwrap_or(&Value::Null),
            ),
            "fields": field_diff(a, b),
        }),
        "adapter" => json!({
            "weights_changed": a.get("weights_hash") != b.get("weights_hash"),
            "fields": field_diff(a, b),
        }),
        _ => json!({"fields": field_diff(a, b)}),
    }
}

/// RFC 6901 escaping of one reference token.
pub fn pointer_escape(k: &str) -> String {
    k.replace('~', "~0").replace('/', "~1")
}

/// Field diff: objects recurse by key, everything else is a leaf compared canonically.
pub fn field_diff(a: &Value, b: &Value) -> Vec<Value> {
    let mut out = Vec::new();
    walk(a, b, "", &mut out);
    out.sort_by(|x, y| {
        cmp_utf16(
            x["path"].as_str().unwrap_or_default(),
            y["path"].as_str().unwrap_or_default(),
        )
    });
    out
}

fn walk(a: &Value, b: &Value, path: &str, out: &mut Vec<Value>) {
    match (a, b) {
        (Value::Object(x), Value::Object(y)) => {
            let mut keys: Vec<&String> = x.keys().chain(y.keys()).collect();
            keys.sort_by(|p, q| cmp_utf16(p, q));
            keys.dedup();
            for k in keys {
                let p = format!("{path}/{}", pointer_escape(k));
                match (x.get(k.as_str()), y.get(k.as_str())) {
                    (Some(v), None) => out.push(change(&p, "removed", Some(v), None)),
                    (None, Some(v)) => out.push(change(&p, "added", None, Some(v))),
                    (Some(v), Some(w)) => walk(v, w, &p, out),
                    (None, None) => unreachable!(),
                }
            }
        }
        _ => {
            if !canon_eq(a, b) {
                out.push(change(path, "changed", Some(a), Some(b)));
            }
        }
    }
}

fn change(path: &str, op: &str, from: Option<&Value>, to: Option<&Value>) -> Value {
    let mut m = Map::new();
    m.insert("path".into(), Value::String(path.into()));
    m.insert("op".into(), Value::String(op.into()));
    if let Some(f) = from {
        m.insert("from".into(), f.clone());
    }
    if let Some(t) = to {
        m.insert("to".into(), t.clone());
    }
    Value::Object(m)
}

/// Length of a longest common subsequence.
pub fn lcs_len<T: PartialEq>(x: &[T], y: &[T]) -> usize {
    let mut prev = vec![0usize; y.len() + 1];
    let mut cur = vec![0usize; y.len() + 1];
    for xi in x {
        for (j, yj) in y.iter().enumerate() {
            cur[j + 1] = if xi == yj {
                prev[j] + 1
            } else {
                prev[j + 1].max(cur[j])
            };
        }
        std::mem::swap(&mut prev, &mut cur);
    }
    prev[y.len()]
}
