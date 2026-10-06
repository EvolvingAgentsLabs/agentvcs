//! Three-way merge of harness manifests (`spec/MERGE.md`, v0.2 draft).
//!
//! [`prepare`] does the mechanical part and hands every real conflict over with
//! the evidence a run's ledger holds; [`commit`] checks an agent's resolution in
//! the spec's order and builds the merged manifest and the merge record. Neither
//! touches a store or runs a gate: the CLI does both (ADR-0008).

use agentvcs_core::hash::{hash_value, is_hash};
use agentvcs_core::json::cmp_utf16;
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_core::schema::{author_ok, content_ok, KINDS};
use agentvcs_core::{Error, Result, PROTOCOL};
use agentvcs_query::{blame, verify, Blame};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

/// `merge_id` = `hash({"protocol", "base", "ours", "theirs"})`: it names the
/// question, not the answer.
pub fn merge_id(base: &str, ours: &str, theirs: &str) -> Result<String> {
    Ok(hash_value(
        &json!({"protocol": PROTOCOL, "base": base, "ours": ours, "theirs": theirs}),
    )?)
}

/// The result of `merge prepare`.
#[derive(Debug, Clone, PartialEq)]
pub struct Prepared {
    pub merge_id: String,
    pub base: String,
    pub ours: String,
    pub theirs: String,
    /// `{"dimension", "resolution": "same"|"ours"|"theirs"}`, sorted by dimension.
    pub auto: Vec<Value>,
    /// Conflict objects of `spec/MERGE.md §2`, sorted by dimension.
    pub conflicts: Vec<Value>,
}

impl Prepared {
    pub fn to_value(&self) -> Value {
        json!({
            "ok": true, "merge_id": self.merge_id,
            "base": self.base, "ours": self.ours, "theirs": self.theirs,
            "auto": self.auto, "conflicts": self.conflicts,
        })
    }

    fn conflict(&self, d: &str) -> Option<&Value> {
        self.conflicts.iter().find(|c| c["dimension"] == d)
    }
}

/// What identifies a dimension on one side: its kind and its content hash. A kind
/// change with equal content is a change (spec/MERGE.md §1, ADR-0008 §2).
fn key<'a>(m: &'a Manifest, d: &str) -> Option<(&'a Value, &'a Value)> {
    m.dimensions()
        .get(d)
        .map(|x| (&x["kind"], &x["content_hash"]))
}

fn side(m: &Manifest, d: &str) -> Value {
    match m.dimensions().get(d) {
        None => Value::Null,
        Some(x) => {
            json!({"kind": x["kind"], "content": x["content"], "content_hash": x["content_hash"]})
        }
    }
}

fn names<'a>(ms: &[&'a Manifest]) -> Vec<&'a String> {
    let mut v: Vec<&String> = ms.iter().flat_map(|m| m.dimensions().keys()).collect();
    v.sort_by(|a, b| cmp_utf16(a, b));
    v.dedup();
    v
}

/// Mechanical result of one dimension: `Ok(resolution)` or `Err(conflict type)`.
fn mechanical(
    b: &Manifest,
    o: &Manifest,
    t: &Manifest,
    d: &str,
) -> std::result::Result<&'static str, &'static str> {
    let (kb, ko, kt) = (key(b, d), key(o, d), key(t, d));
    if ko == kt {
        Ok("same")
    } else if ko == kb {
        Ok("theirs")
    } else if kt == kb {
        Ok("ours")
    } else {
        Err(match (kb, ko, kt) {
            (None, _, _) => "add/add",
            (_, _, None) => "modify/delete",
            (_, None, _) => "delete/modify",
            _ => "modify/modify",
        })
    }
}

/// The evidence one run's ledger holds (`spec/MERGE.md §2, Evidence`).
struct Evidence<'a> {
    patches: Vec<&'a Value>,
    blames: Vec<Blame>,
}

impl<'a> Evidence<'a> {
    /// Refuses a ledger that does not verify (`E_INVALID_LEDGER`), as `blame` does:
    /// evidence is what the runtime observed, and an unverifiable ledger is not that.
    fn of(bundle: &'a Value, metrics: &[String]) -> Result<Self> {
        let r = verify(bundle);
        if !r.valid {
            return Err(Error::new(
                "E_INVALID_LEDGER",
                format!(
                    "run {} does not verify (first violation: {})",
                    bundle["run_id"], r.violations[0]
                ),
            ));
        }
        let mut seen = BTreeSet::new();
        let blames = metrics
            .iter()
            .filter(|m| seen.insert(m.as_str()))
            .map(|m| blame(bundle, m))
            .collect::<Result<_>>()?;
        let patches = bundle["ledger"]
            .as_array()
            .expect("verified")
            .iter()
            .filter(|e| e["kind"] == "patch")
            .map(|e| &e["body"])
            .collect();
        Ok(Evidence { patches, blames })
    }

    /// The `delta` of the one attribution whose `patches` are exactly `[pid]`;
    /// `null` when the patch is attributed jointly, or the metric is absent.
    fn delta(b: &Blame, pid: &str) -> Value {
        let hits: Vec<usize> = (1..b.segments.len())
            .filter(|&i| b.segments[i].introduced_by.iter().any(|p| p == pid))
            .collect();
        match hits.as_slice() {
            [i] if b.segments[*i].introduced_by.len() == 1 => {
                let (a, c) = (b.segments[i - 1].mean, b.segments[*i].mean);
                a.zip(c).map_or(Value::Null, |(a, c)| json!(c - a))
            }
            _ => Value::Null,
        }
    }

    fn for_dimension(&self, d: &str) -> Vec<Value> {
        self.patches
            .iter()
            .filter(|b| {
                b["semantic_diff"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|c| c["dimension"] == d))
            })
            .map(|b| {
                let pid = b["patch_id"].as_str().unwrap_or_default();
                let g = &b["gate_result"];
                let blame: Map<String, Value> = self
                    .blames
                    .iter()
                    .map(|bl| (bl.metric.clone(), Self::delta(bl, pid)))
                    .collect();
                json!({
                    "patch_id": pid, "applied_at_step": b["applied_at_step"],
                    "rationale": b["rationale"], "author": b["author"],
                    "gate": if g.is_null() { Value::Null } else { json!({"passed": g["passed"], "metrics": g["metrics"]}) },
                    "blame": blame,
                })
            })
            .collect()
    }
}

/// `merge prepare`: mechanical results, and every conflict with both sides, both
/// diffs from base, and the evidence of `ours_run` / `theirs_run` (audit bundles).
pub fn prepare(
    base: &Manifest,
    ours: &Manifest,
    theirs: &Manifest,
    ours_run: Option<&Value>,
    theirs_run: Option<&Value>,
    metrics: &[String],
) -> Result<Prepared> {
    let ev_o = ours_run.map(|b| Evidence::of(b, metrics)).transpose()?;
    let ev_t = theirs_run.map(|b| Evidence::of(b, metrics)).transpose()?;
    let (diff_o, diff_t) = (
        agentvcs_diff::diff(base, ours).changes,
        agentvcs_diff::diff(base, theirs).changes,
    );
    let change = |changes: &[Value], d: &str| {
        changes
            .iter()
            .find(|c| c["dimension"] == d)
            .cloned()
            .unwrap_or(Value::Null)
    };
    let (mut auto, mut conflicts) = (Vec::new(), Vec::new());
    for d in names(&[base, ours, theirs]) {
        match mechanical(base, ours, theirs, d) {
            Ok(r) => auto.push(json!({"dimension": d, "resolution": r})),
            Err(typ) => {
                let kind = ours
                    .dimensions()
                    .get(d)
                    .or_else(|| theirs.dimensions().get(d))
                    .map(|x| x["kind"].clone())
                    .expect("a conflict has at least one present side");
                let ev = |e: &Option<Evidence>| e.as_ref().map_or(vec![], |e| e.for_dimension(d));
                conflicts.push(json!({
                    "dimension": d, "kind": kind, "type": typ,
                    "base": side(base, d), "ours": side(ours, d), "theirs": side(theirs, d),
                    "diff_ours": change(&diff_o, d), "diff_theirs": change(&diff_t, d),
                    "evidence": {"ours": ev(&ev_o), "theirs": ev(&ev_t)},
                }));
            }
        }
    }
    Ok(Prepared {
        merge_id: merge_id(&base.manifest_id, &ours.manifest_id, &theirs.manifest_id)?,
        base: base.manifest_id.clone(),
        ours: ours.manifest_id.clone(),
        theirs: theirs.manifest_id.clone(),
        auto,
        conflicts,
    })
}

// ------------------------------------------------------------------ resolution

const TAKES: [&str; 4] = ["ours", "theirs", "base", "delete"];

fn only_keys(m: &Map<String, Value>, allowed: &[&str]) -> bool {
    m.keys().all(|k| allowed.contains(&k.as_str()))
}

/// The resolution's schema (`spec/MERGE.md §3`): the top-level fields, and each
/// resolution being exactly `{take}` or `{content, kind}`. The kind enum and the
/// content constraints are checked later, with their own codes.
pub fn resolution_ok(v: &Value) -> bool {
    let Some(m) = v.as_object() else {
        return false;
    };
    let req = [
        "protocol",
        "type",
        "merge_id",
        "resolutions",
        "rationale",
        "author",
    ];
    req.iter().all(|k| m.contains_key(*k))
        && only_keys(m, &req)
        && m["protocol"].is_string()
        && m["type"] == "merge_resolution"
        && m["merge_id"].as_str().is_some_and(is_hash)
        && m["rationale"].is_string()
        && author_ok(&m["author"])
        && m["resolutions"].as_object().is_some_and(|r| {
            r.values().all(|x| match x.as_object() {
                Some(x) if x.len() == 1 && x.contains_key("take") => {
                    x["take"].as_str().is_some_and(|t| TAKES.contains(&t))
                }
                Some(x) if x.len() == 2 && x.contains_key("content") => {
                    x.get("kind").is_some_and(Value::is_string)
                }
                _ => false,
            })
        })
}

/// A checked merge: the merged manifest and the merge record (`gate: null`; the
/// caller fills it when it runs a suite, before storing the record).
#[derive(Debug, Clone, PartialEq)]
pub struct Committed {
    pub merged: Manifest,
    pub record: Value,
}

/// `record` = `hash(merge record)`.
pub fn record_id(record: &Value) -> Result<String> {
    Ok(hash_value(record)?)
}

fn err(code: &'static str, msg: String) -> Error {
    Error::new(code, msg)
}

/// `merge commit` without the store and the gate: the checks of
/// `spec/MERGE.md §4`, in order, then the merged manifest
/// (`parent_ids: [ours, theirs]`) and the merge record.
pub fn commit(
    base: &Manifest,
    ours: &Manifest,
    theirs: &Manifest,
    resolution: &Value,
) -> Result<Committed> {
    if !resolution_ok(resolution) {
        return Err(err(
            "E_SCHEMA",
            "resolution must be {protocol, type: merge_resolution, merge_id, resolutions: {dim: {take} | {content, kind}}, rationale, author}".into(),
        ));
    }
    if resolution["protocol"] != PROTOCOL {
        return Err(err(
            "E_PROTOCOL_VERSION",
            format!("resolution protocol must be {PROTOCOL}"),
        ));
    }
    let prep = prepare(base, ours, theirs, None, None, &[])?;
    if resolution["merge_id"] != prep.merge_id.as_str() {
        return Err(err(
            "E_MERGE_STALE",
            format!(
                "resolution is for merge {}, these manifests are merge {}",
                resolution["merge_id"], prep.merge_id
            ),
        ));
    }
    let res = resolution["resolutions"].as_object().expect("schema");
    if let Some(c) = prep
        .conflicts
        .iter()
        .find(|c| !res.contains_key(c["dimension"].as_str().unwrap_or_default()))
    {
        return Err(err(
            "E_MERGE_UNRESOLVED",
            format!("conflict on {} has no resolution", c["dimension"]),
        ));
    }
    let mut dims: Vec<&String> = res.keys().collect();
    dims.sort_by(|a, b| cmp_utf16(a, b));
    if let Some(d) = dims.iter().find(|d| prep.conflict(d).is_none()) {
        return Err(err(
            "E_MERGE_EXTRA",
            format!("{d:?} is not a conflict (it merged mechanically or does not exist)"),
        ));
    }
    let source = |which: &str| match which {
        "ours" => Some(ours),
        "theirs" => Some(theirs),
        "base" => Some(base),
        _ => None,
    };
    for d in &dims {
        if let Some(t) = res[d.as_str()].get("take").and_then(Value::as_str) {
            if t != "delete" && !source(t).is_some_and(|m| m.dimensions().contains_key(d.as_str()))
            {
                return Err(err(
                    "E_MERGE_TAKE",
                    format!(
                        "{d:?}: take {t} names a side where the dimension is absent (use delete)"
                    ),
                ));
            }
        }
    }
    for d in &dims {
        let x = &res[d.as_str()];
        if let Some(k) = x.get("kind").and_then(Value::as_str) {
            if !KINDS.contains(&k) {
                return Err(err("E_UNKNOWN_KIND", format!("{d:?}: unknown kind {k:?}")));
            }
            if !content_ok(k, &x["content"]) {
                return Err(err(
                    "E_SCHEMA",
                    format!("{d:?}: content is not a valid {k} (spec/PROTOCOL.md §2.1)"),
                ));
            }
        }
    }

    // build
    let mut out = Map::new();
    let mut put = |d: &str, kind: &Value, content: &Value| {
        out.insert(d.to_owned(), json!({"kind": kind, "content": content}));
    };
    for a in &prep.auto {
        let d = a["dimension"].as_str().unwrap_or_default();
        let src = if a["resolution"] == "theirs" {
            theirs
        } else {
            ours
        };
        if let Some(x) = src.dimensions().get(d) {
            put(d, &x["kind"], &x["content"]);
        }
    }
    for d in &dims {
        let x = &res[d.as_str()];
        match x.get("take").and_then(Value::as_str) {
            Some("delete") => {}
            Some(t) => {
                let y = &source(t).expect("checked").dimensions()[d.as_str()];
                put(d, &y["kind"], &y["content"]);
            }
            None => put(d, &x["kind"], &x["content"]),
        }
    }
    let mut keys: Vec<String> = out.keys().cloned().collect();
    keys.sort_by(|a, b| cmp_utf16(a, b));
    let dimensions: Map<String, Value> = keys
        .into_iter()
        .map(|k| {
            let v = out.remove(&k).expect("key");
            (k, v)
        })
        .collect();
    let merged = normalize(&json!({
        "protocol": PROTOCOL, "type": "harness_manifest",
        "parent_ids": [ours.manifest_id, theirs.manifest_id],
        "dimensions": dimensions,
    }))?;
    let record = json!({
        "protocol": PROTOCOL, "type": "merge_record", "merge_id": prep.merge_id,
        "base": prep.base, "ours": prep.ours, "theirs": prep.theirs,
        "merged": merged.manifest_id, "auto": prep.auto, "resolution": resolution,
        "gate": null,
    });
    Ok(Committed { merged, record })
}
