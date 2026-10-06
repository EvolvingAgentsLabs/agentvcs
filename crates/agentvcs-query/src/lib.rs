//! Ledger queries: `verify` (`spec/LEDGER.md`), `blame` (`spec/BLAME.md`) and
//! `bisect` (`spec/cli/COMMANDS.md`, no goldens in v0.1).

pub mod bisect;

use agentvcs_core::json::{canon_eq, cmp_utf16};
use agentvcs_core::ledger::{as_index, entry_hash, gate_passes, patch_id};
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_core::schema::{bundle_shape_ok, entry_ok};
use agentvcs_core::{Error, Result, PROTOCOL};
use serde_json::{json, Map, Value};
use std::collections::HashMap;

/// The result of `verify`.
#[derive(Debug, Clone, PartialEq)]
pub struct Report {
    pub valid: bool,
    pub entries: usize,
    pub open: bool,
    pub violations: Vec<Value>,
}

impl Report {
    pub fn to_value(&self) -> Value {
        json!({
            "ok": true,
            "valid": self.valid,
            "entries": self.entries,
            "open": self.open,
            "violations": self.violations,
        })
    }
}

fn strip_display(changes: &Value) -> Value {
    match changes {
        Value::Array(a) => Value::Array(
            a.iter()
                .map(|c| match c {
                    Value::Object(m) => {
                        let mut m = m.clone();
                        m.remove("display");
                        Value::Object(m)
                    }
                    x => x.clone(),
                })
                .collect(),
        ),
        x => x.clone(),
    }
}

/// Verify an audit bundle in the order `spec/LEDGER.md` prescribes.
pub fn verify(bundle: &Value) -> Report {
    let mut v: Vec<Value> = Vec::new();
    let entries = bundle
        .get("ledger")
        .and_then(Value::as_array)
        .map_or(0, Vec::len);
    let fail = |code: &str, entries| Report {
        valid: false,
        entries,
        open: true,
        violations: vec![json!({"code": code, "seq": null})],
    };
    // 1. bundle
    if !bundle_shape_ok(bundle) {
        return fail("E_SCHEMA", entries);
    }
    if bundle["protocol"] != PROTOCOL {
        return fail("E_PROTOCOL_VERSION", entries);
    }
    let run_id = bundle["run_id"].as_str().unwrap_or_default();
    let manifests = bundle["manifests"].as_object().expect("shape checked");
    let ledger = bundle["ledger"].as_array().expect("shape checked");

    // 2. manifests, in key order
    let mut keys: Vec<&String> = manifests.keys().collect();
    keys.sort_by(|a, b| cmp_utf16(a, b));
    let mut normalized: HashMap<&str, Manifest> = HashMap::new();
    for key in keys {
        match normalize(&manifests[key.as_str()]) {
            Err(e) => v.push(json!({"code": e.code, "manifest_id": key})),
            Ok(n) => {
                if &n.manifest_id != key {
                    v.push(json!({"code": "E_MANIFEST_KEY", "manifest_id": key}));
                }
                normalized.insert(key.as_str(), n);
            }
        }
    }

    // 3. entries
    let mut active: Option<String> = None;
    let mut next_step: u64 = 0;
    let mut ended = false;
    let mut patches: HashMap<String, &Value> = HashMap::new();
    let mut diff_cache: HashMap<(String, String), Value> = HashMap::new();
    for (i, e) in ledger.iter().enumerate() {
        let mut bad = |code: &str| v.push(json!({"code": code, "seq": i}));
        if !entry_ok(e) {
            bad("E_SCHEMA");
            continue;
        }
        if e["protocol"] != PROTOCOL {
            bad("E_PROTOCOL_VERSION");
            continue;
        }
        if e["run_id"] != run_id {
            bad("E_RUN_ID");
        }
        if as_index(&e["seq"]) != Some(i as u64) {
            bad("E_SEQ");
        }
        let exp_prev = if i == 0 {
            Value::Null
        } else {
            ledger[i - 1]
                .get("entry_hash")
                .cloned()
                .unwrap_or(Value::Null)
        };
        if e["prev_hash"] != exp_prev {
            bad("E_PREV_HASH");
        }
        if entry_hash(e).ok().as_deref() != e["entry_hash"].as_str() {
            bad("E_ENTRY_HASH");
        }
        let kind = e["kind"].as_str().unwrap_or_default();
        let b = &e["body"];
        if i == 0 && kind != "run_start" {
            bad("E_FIRST_NOT_RUN_START");
        }
        if i > 0 && kind == "run_start" {
            bad("E_DUPLICATE_RUN_START");
        }
        if ended {
            bad("E_AFTER_RUN_END");
        }
        let named = ["manifest_id", "from_manifest", "to_manifest"]
            .iter()
            .filter_map(|k| b.get(*k));
        if named
            .into_iter()
            .any(|x| x.as_str().is_none_or(|x| !manifests.contains_key(x)))
        {
            bad("E_UNKNOWN_MANIFEST");
        }
        match kind {
            "run_start" => {
                active = b["manifest_id"].as_str().map(str::to_owned);
                next_step = match &b["parent"] {
                    Value::Null => 0,
                    p => as_index(&p["from_step"]).unwrap_or(0),
                };
            }
            "step" => {
                let si = as_index(&b["step_index"]).unwrap_or(u64::MAX);
                if si != next_step {
                    bad("E_STEP_INDEX");
                }
                if b["manifest_id"].as_str() != active.as_deref() {
                    bad("E_STEP_MANIFEST");
                }
                next_step = si.wrapping_add(1);
            }
            "patch" => {
                if b["from_manifest"] == b["to_manifest"] {
                    bad("E_PATCH_NOOP");
                }
                if patch_id(b).ok().as_deref() != b["patch_id"].as_str() {
                    bad("E_PATCH_ID");
                }
                if b["from_manifest"].as_str() != active.as_deref() {
                    bad("E_PATCH_FROM");
                }
                if as_index(&b["applied_at_step"]) != Some(next_step) {
                    bad("E_PATCH_STEP");
                }
                let g = &b["gate_result"];
                if !b["rollback_of"].is_null() {
                    match patches.get(b["rollback_of"].as_str().unwrap_or_default()) {
                        None => bad("E_ROLLBACK_UNKNOWN"),
                        Some(orig) => {
                            if orig["from_manifest"] != b["to_manifest"]
                                || orig["to_manifest"] != b["from_manifest"]
                            {
                                bad("E_ROLLBACK_TARGET");
                            }
                        }
                    }
                } else if g.is_null() || g["passed"] != true {
                    bad("E_PATCH_UNGATED");
                }
                if !g.is_null() && g["passed"].as_bool() != Some(gate_passes(g)) {
                    bad("E_GATE_INCONSISTENT");
                }
                let (f, t) = (
                    b["from_manifest"].as_str().unwrap_or_default(),
                    b["to_manifest"].as_str().unwrap_or_default(),
                );
                if let (Some(mf), Some(mt)) = (normalized.get(f), normalized.get(t)) {
                    let expected = diff_cache
                        .entry((f.to_owned(), t.to_owned()))
                        .or_insert_with(|| Value::Array(agentvcs_diff::diff(mf, mt).changes));
                    if !canon_eq(&strip_display(&b["semantic_diff"]), expected) {
                        bad("E_PATCH_DIFF");
                    }
                }
                patches.insert(b["patch_id"].as_str().unwrap_or_default().to_owned(), b);
                active = b["to_manifest"].as_str().map(str::to_owned);
            }
            "run_end" => ended = true,
            _ => {}
        }
    }
    Report {
        valid: v.is_empty(),
        entries,
        open: !ended,
        violations: v,
    }
}

/// One blame segment.
#[derive(Debug, Clone, PartialEq)]
pub struct Segment {
    pub manifest_id: String,
    pub from_step: u64,
    pub to_step: u64,
    pub n: usize,
    pub mean: Option<f64>,
    pub introduced_by: Vec<String>,
}

/// The result of `blame`.
#[derive(Debug, Clone, PartialEq)]
pub struct Blame {
    pub metric: String,
    pub segments: Vec<Segment>,
}

impl Blame {
    pub fn to_value(&self) -> Value {
        let segs: Vec<Value> = self
            .segments
            .iter()
            .map(|s| {
                json!({
                    "manifest_id": s.manifest_id, "from_step": s.from_step, "to_step": s.to_step,
                    "n": s.n, "mean": s.mean, "introduced_by": s.introduced_by,
                })
            })
            .collect();
        let attributions: Vec<Value> = (1..self.segments.len())
            .map(|i| {
                let (a, c) = (self.segments[i - 1].mean, self.segments[i].mean);
                json!({
                    "patches": self.segments[i].introduced_by,
                    "from_segment": i - 1, "to_segment": i,
                    "delta": a.zip(c).map(|(a, c)| c - a),
                })
            })
            .collect();
        json!({"ok": true, "metric": self.metric, "segments": segs, "attributions": attributions})
    }
}

/// Segment a verified ledger by manifest and attribute metric deltas to patches.
pub fn blame(bundle: &Value, metric: &str) -> Result<Blame> {
    let r = verify(bundle);
    if !r.valid {
        return Err(Error::new(
            "E_INVALID_LEDGER",
            format!(
                "ledger does not verify (first violation: {})",
                r.violations[0]
            ),
        ));
    }
    let mut segs: Vec<(Segment, Vec<f64>)> = Vec::new();
    let mut pending: Vec<String> = Vec::new();
    for e in bundle["ledger"].as_array().expect("verified") {
        let b = &e["body"];
        match e["kind"].as_str() {
            Some("patch") => pending.push(b["patch_id"].as_str().unwrap_or_default().into()),
            Some("step") => {
                let mid = b["manifest_id"].as_str().unwrap_or_default();
                let si = as_index(&b["step_index"]).unwrap_or_default();
                let extend = segs
                    .last()
                    .is_some_and(|(s, _)| s.manifest_id == mid && pending.is_empty());
                if !extend {
                    let introduced_by = if segs.is_empty() {
                        Vec::new()
                    } else {
                        std::mem::take(&mut pending)
                    };
                    pending.clear();
                    segs.push((
                        Segment {
                            manifest_id: mid.into(),
                            from_step: si,
                            to_step: si,
                            n: 0,
                            mean: None,
                            introduced_by,
                        },
                        Vec::new(),
                    ));
                }
                let (s, vals) = segs.last_mut().expect("pushed");
                s.to_step = si;
                if let Some(x) = b
                    .get("metrics")
                    .and_then(Value::as_object)
                    .and_then(|m: &Map<String, Value>| m.get(metric))
                    .and_then(Value::as_f64)
                {
                    vals.push(x);
                }
            }
            _ => {}
        }
    }
    let segments = segs
        .into_iter()
        .map(|(mut s, vals)| {
            s.n = vals.len();
            s.mean = (!vals.is_empty()).then(|| vals.iter().sum::<f64>() / vals.len() as f64);
            s
        })
        .collect();
    Ok(Blame {
        metric: metric.into(),
        segments,
    })
}
