//! Ledger entries (`spec/PROTOCOL.md §3`) and the writer-side run state.
//!
//! The writer enforces the same invariants `verify` checks, so a ledger written
//! through [`RunState::append`] verifies by construction (except the gate, which
//! is a policy the caller applies before appending a patch).

use crate::error::{Error, Result};
use crate::hash::{hash_value, is_hash};
use crate::json::{canonical, write_canonical};
use crate::schema::{author_ok, body_ok};
use crate::PROTOCOL;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

/// `entry_hash` = hash of the entry without its `entry_hash` key.
pub fn entry_hash(e: &Value) -> Result<String> {
    let Some(m) = e.as_object() else {
        return Err(Error::new("E_SCHEMA", "entry is not an object"));
    };
    let mut keys: Vec<&String> = m.keys().filter(|k| *k != "entry_hash").collect();
    keys.sort_by(|a, b| crate::json::cmp_utf16(a, b));
    let mut s = String::with_capacity(256);
    s.push('{');
    for (i, k) in keys.into_iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        write_canonical(&Value::String(k.clone()), &mut s)?;
        s.push(':');
        write_canonical(&m[k.as_str()], &mut s)?;
    }
    s.push('}');
    Ok(crate::hash::b3_bytes(s.as_bytes()))
}

/// `patch_id` = hash of the proposal (`PROTOCOL.md §3.3`).
pub fn patch_id(body: &Value) -> Result<String> {
    let mut m = Map::new();
    m.insert("protocol".into(), PROTOCOL.into());
    for k in [
        "from_manifest",
        "to_manifest",
        "rationale",
        "evidence",
        "author",
        "rollback_of",
    ] {
        m.insert(k.into(), body.get(k).cloned().unwrap_or(Value::Null));
    }
    Ok(hash_value(&Value::Object(m))?)
}

/// Whether a gate's thresholds hold on its metrics (`PROTOCOL.md §3.4`).
pub fn gate_passes(g: &Value) -> bool {
    let (Some(th), Some(metrics)) = (
        g.get("thresholds").and_then(Value::as_object),
        g.get("metrics").and_then(Value::as_object),
    ) else {
        return false;
    };
    if th.is_empty() {
        return false;
    }
    th.iter().all(|(name, t)| {
        let (Some(v), Some(op), Some(x)) = (
            metrics.get(name).and_then(Value::as_f64),
            t.get("op").and_then(Value::as_str),
            t.get("value").and_then(Value::as_f64),
        ) else {
            return false;
        };
        match op {
            ">=" => v >= x,
            ">" => v > x,
            "<=" => v <= x,
            "<" => v < x,
            "==" => v == x,
            _ => false,
        }
    })
}

/// A non-negative integral JSON number as `u64`.
pub fn as_index(v: &Value) -> Option<u64> {
    if let Some(u) = v.as_u64() {
        return Some(u);
    }
    v.as_f64()
        .filter(|f| *f >= 0.0 && f.fract() == 0.0 && *f <= 9_007_199_254_740_991.0)
        .map(|f| f as u64)
}

/// What a writer must know to append the next entry of a run.
#[derive(Debug, Clone, PartialEq)]
pub struct RunState {
    pub run_id: String,
    pub next_seq: u64,
    pub last_hash: Option<String>,
    /// Active manifest; `None` before `run_start` (or when only `run_end` is known).
    pub active: Option<String>,
    pub next_step: u64,
    pub ended: bool,
}

impl RunState {
    pub fn new(run_id: &str) -> Self {
        RunState {
            run_id: run_id.into(),
            next_seq: 0,
            last_hash: None,
            active: None,
            next_step: 0,
            ended: false,
        }
    }

    /// The state after `e`, computed from `e` alone: the last entry of a ledger
    /// determines everything a writer needs.
    pub fn after(e: &Value) -> Result<Self> {
        let mut s = RunState::new(e["run_id"].as_str().unwrap_or_default());
        s.observe(e)?;
        Ok(s)
    }

    /// Advance past an existing entry.
    pub fn observe(&mut self, e: &Value) -> Result<()> {
        let bad = || Error::new("E_SCHEMA", "malformed ledger entry in store");
        let b = &e["body"];
        self.next_seq = as_index(&e["seq"]).ok_or_else(bad)? + 1;
        self.last_hash = Some(e["entry_hash"].as_str().ok_or_else(bad)?.to_owned());
        match e["kind"].as_str() {
            Some("run_start") => {
                self.active = b["manifest_id"].as_str().map(str::to_owned);
                self.next_step = match &b["parent"] {
                    Value::Null => 0,
                    p => as_index(&p["from_step"]).ok_or_else(bad)?,
                };
            }
            Some("step") => {
                self.active = b["manifest_id"].as_str().map(str::to_owned);
                self.next_step = as_index(&b["step_index"]).ok_or_else(bad)? + 1;
            }
            Some("patch") => {
                self.active = b["to_manifest"].as_str().map(str::to_owned);
                self.next_step = as_index(&b["applied_at_step"]).ok_or_else(bad)?;
            }
            Some("run_end") => self.ended = true,
            _ => return Err(bad()),
        }
        Ok(())
    }

    /// Fill `step_index` and `manifest_id` of a step body when absent; refuse them
    /// when present and wrong.
    pub fn fill_step(&self, body: &mut Map<String, Value>) -> Result<()> {
        let active = self
            .active
            .as_deref()
            .ok_or_else(|| Error::new("E_FIRST_NOT_RUN_START", "run has no run_start"))?;
        match body.get("step_index") {
            None => {
                body.insert("step_index".into(), self.next_step.into());
            }
            Some(v) if as_index(v) == Some(self.next_step) => {}
            Some(v) => {
                return Err(Error::new(
                    "E_STEP_INDEX",
                    format!("step_index {v} but the next step is {}", self.next_step),
                ))
            }
        }
        match body.get("manifest_id") {
            None => {
                body.insert("manifest_id".into(), active.into());
            }
            Some(v) if v.as_str() == Some(active) => {}
            Some(v) => {
                return Err(Error::new(
                    "E_STEP_MANIFEST",
                    format!("step manifest {v} but the active manifest is {active}"),
                ))
            }
        }
        Ok(())
    }

    /// Build the next entry of kind `kind` with `body`, check the writer-side
    /// invariants, and advance. Returns the entry and its canonical line.
    pub fn append(&mut self, kind: &str, body: Value) -> Result<(Value, String)> {
        if self.ended {
            return Err(Error::new("E_AFTER_RUN_END", "run has ended"));
        }
        if (kind == "run_start") != (self.next_seq == 0) {
            return Err(Error::new(
                if kind == "run_start" {
                    "E_DUPLICATE_RUN_START"
                } else {
                    "E_FIRST_NOT_RUN_START"
                },
                "run_start must be the first entry and only the first",
            ));
        }
        if !body_ok(kind, &body) {
            return Err(Error::new(
                "E_SCHEMA",
                format!("{kind} body does not match ledger_entry.schema.json"),
            ));
        }
        if kind == "step" && body["manifest_id"].as_str() != self.active.as_deref() {
            return Err(Error::new(
                "E_STEP_MANIFEST",
                "step under a non-active manifest",
            ));
        }
        if kind == "step" && as_index(&body["step_index"]) != Some(self.next_step) {
            return Err(Error::new(
                "E_STEP_INDEX",
                "step_index is not the next step",
            ));
        }
        if kind == "patch" {
            if body["from_manifest"] == body["to_manifest"] {
                return Err(Error::new("E_PATCH_NOOP", "patch changes nothing"));
            }
            if body["from_manifest"].as_str() != self.active.as_deref() {
                return Err(Error::new(
                    "E_PATCH_FROM",
                    "patch from_manifest is not the active manifest",
                ));
            }
            if as_index(&body["applied_at_step"]) != Some(self.next_step) {
                return Err(Error::new(
                    "E_PATCH_STEP",
                    format!("applied_at_step must be the next step, {}", self.next_step),
                ));
            }
            if body["patch_id"].as_str() != Some(patch_id(&body)?.as_str()) {
                return Err(Error::new("E_PATCH_ID", "patch_id does not recompute"));
            }
        }
        let mut e = Map::new();
        e.insert("protocol".into(), PROTOCOL.into());
        e.insert("type".into(), "ledger_entry".into());
        e.insert("run_id".into(), self.run_id.clone().into());
        e.insert("seq".into(), self.next_seq.into());
        e.insert(
            "prev_hash".into(),
            self.last_hash.clone().map_or(Value::Null, Value::String),
        );
        e.insert("kind".into(), kind.into());
        e.insert("body".into(), body);
        let mut e = Value::Object(e);
        let h = entry_hash(&e)?;
        e["entry_hash"] = Value::String(h);
        let line = canonical(&e)?;
        self.observe(&e)?;
        Ok((e, line))
    }
}

/// Body of a `run_start`.
pub fn run_start_body(manifest_id: &str, started_at: &str, parent: Option<Value>) -> Value {
    json!({"manifest_id": manifest_id, "started_at": started_at, "parent": parent.unwrap_or(Value::Null)})
}

/// Body of a patch, with its `patch_id` computed.
#[allow(clippy::too_many_arguments)]
pub fn patch_body(
    from: &str,
    to: &str,
    semantic_diff: Value,
    rationale: &str,
    evidence: Vec<u64>,
    author: Value,
    applied_at_step: u64,
    rollback_of: Option<&str>,
    gate_result: Option<Value>,
) -> Result<Value> {
    if !author_ok(&author) {
        return Err(Error::new(
            "E_SCHEMA",
            "author must be {\"type\": \"human\"|\"agent\", \"id\": …}",
        ));
    }
    if rollback_of.is_some_and(|r| !is_hash(r)) {
        return Err(Error::new("E_SCHEMA", "rollback_of must be a patch id"));
    }
    let mut b = json!({
        "patch_id": null,
        "from_manifest": from,
        "to_manifest": to,
        "semantic_diff": semantic_diff,
        "rationale": rationale,
        "evidence": evidence,
        "author": author,
        "applied_at_step": applied_at_step,
        "rollback_of": rollback_of,
        "gate_result": gate_result,
    });
    b["patch_id"] = patch_id(&b)?.into();
    Ok(b)
}

/// Builds a ledger plus its audit bundle in memory (tests, benchmarks, SDKs).
pub struct LedgerBuilder {
    pub state: RunState,
    pub entries: Vec<Value>,
    pub manifests: Map<String, Value>,
    patches: HashMap<String, Value>,
}

impl LedgerBuilder {
    /// `manifests` are normalized manifest values (with `manifest_id`).
    pub fn new(run_id: &str, manifests: Vec<Value>) -> Self {
        LedgerBuilder {
            state: RunState::new(run_id),
            entries: Vec::new(),
            manifests: manifests
                .into_iter()
                .map(|m| (m["manifest_id"].as_str().unwrap_or_default().to_owned(), m))
                .collect(),
            patches: HashMap::new(),
        }
    }

    fn push(&mut self, kind: &str, body: Value) -> Result<&Value> {
        let (e, _) = self.state.append(kind, body)?;
        self.entries.push(e);
        Ok(self.entries.last().expect("pushed"))
    }

    pub fn run_start(&mut self, manifest_id: &str, parent: Option<Value>) -> Result<&Value> {
        self.push(
            "run_start",
            run_start_body(manifest_id, "2026-10-06T00:00:00Z", parent),
        )
    }

    pub fn step(&mut self, body: Value) -> Result<&Value> {
        let Value::Object(mut b) = body else {
            return Err(Error::new("E_SCHEMA", "step body is not an object"));
        };
        self.state.fill_step(&mut b)?;
        self.push("step", Value::Object(b))
    }

    /// Append a patch to `to`. `semantic_diff` is computed by the caller
    /// (`agentvcs-diff`), which sits above this crate.
    #[allow(clippy::too_many_arguments)]
    pub fn patch_with_diff(
        &mut self,
        to: &str,
        semantic_diff: Value,
        rationale: &str,
        evidence: Vec<u64>,
        author: Value,
        rollback_of: Option<&str>,
        gate_result: Option<Value>,
    ) -> Result<&Value> {
        let from = self.state.active.clone().unwrap_or_default();
        let b = patch_body(
            &from,
            to,
            semantic_diff,
            rationale,
            evidence,
            author,
            self.state.next_step,
            rollback_of,
            gate_result,
        )?;
        self.patches
            .insert(b["patch_id"].as_str().unwrap_or_default().into(), b.clone());
        self.push("patch", b)
    }

    pub fn run_end(&mut self, status: &str) -> Result<&Value> {
        self.push(
            "run_end",
            json!({"ended_at": "2026-10-06T00:00:01Z", "status": status}),
        )
    }

    /// The audit bundle (`PROTOCOL.md §4`).
    pub fn bundle(&self) -> Value {
        json!({
            "protocol": PROTOCOL,
            "type": "audit_bundle",
            "run_id": self.state.run_id,
            "manifests": self.manifests,
            "ledger": self.entries,
        })
    }
}
