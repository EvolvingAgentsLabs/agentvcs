//! Hand-written checks equivalent to `spec/schemas/*.json`.
//!
//! They return `false` on the first mismatch; callers map that to `E_SCHEMA`.
//! The `protocol` const is deliberately *not* checked here: the spec checks it
//! separately (`E_PROTOCOL_VERSION`) right after the schema.

use crate::hash::is_hash;
use serde_json::{Map, Value};

pub const KINDS: [&str; 7] = [
    "prompt", "model", "sampling", "tool", "adapter", "router", "config",
];

pub fn is_dimension_name(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty()
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b[1..].iter().all(|c| {
            c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, b'_' | b'.' | b'-' | b'/')
        })
}

fn only_keys(m: &Map<String, Value>, allowed: &[&str]) -> bool {
    m.keys().all(|k| allowed.contains(&k.as_str()))
}

fn has_keys(m: &Map<String, Value>, req: &[&str]) -> bool {
    req.iter().all(|k| m.contains_key(*k))
}

fn is_hash_value(v: &Value) -> bool {
    v.as_str().is_some_and(is_hash)
}

/// JSON Schema `integer`: a number with no fractional part.
pub fn is_integer(v: &Value) -> bool {
    match v {
        Value::Number(n) => {
            n.is_i64() || n.is_u64() || n.as_f64().is_some_and(|f| f.fract() == 0.0)
        }
        _ => false,
    }
}

fn is_nonneg_integer(v: &Value) -> bool {
    is_integer(v) && v.as_f64().is_some_and(|f| f >= 0.0)
}

fn opt<F: Fn(&Value) -> bool>(m: &Map<String, Value>, k: &str, f: F) -> bool {
    m.get(k).is_none_or(f)
}

fn str_or_null(v: &Value) -> bool {
    v.is_string() || v.is_null()
}

fn unique_strings(v: &Value) -> bool {
    match v.as_array() {
        Some(a) => {
            let mut seen = std::collections::HashSet::new();
            a.iter()
                .all(|x| x.as_str().is_some_and(|s| seen.insert(s.to_owned())))
        }
        None => false,
    }
}

/// Content constraints of one dimension kind (`PROTOCOL.md §2.1`).
pub fn content_ok(kind: &str, c: &Value) -> bool {
    let Some(m) = c.as_object() else {
        // only the kinds that declare `type: object` constrain non-objects
        return false;
    };
    match kind {
        "prompt" => {
            m.get("template").is_some_and(Value::is_string) && opt(m, "variables", unique_strings)
        }
        "model" => {
            m.get("provider").is_some_and(Value::is_string)
                && m.get("id").is_some_and(Value::is_string)
                && opt(m, "quantization", str_or_null)
                && opt(m, "revision", str_or_null)
        }
        "sampling" => {
            opt(m, "temperature", Value::is_number)
                && opt(m, "top_p", Value::is_number)
                && opt(m, "top_k", is_integer)
                && opt(m, "min_p", Value::is_number)
                && opt(m, "max_tokens", is_integer)
                && opt(m, "seed", |v| v.is_null() || is_integer(v))
                && opt(m, "stop", |v| {
                    v.as_array().is_some_and(|a| a.iter().all(Value::is_string))
                })
                && opt(m, "grammar", str_or_null)
        }
        "tool" => {
            m.get("name").is_some_and(Value::is_string)
                && m.get("signature").is_some_and(Value::is_object)
                && m.get("code_hash").is_some_and(is_hash_value)
        }
        "adapter" => {
            m.get("adapter_id").is_some_and(Value::is_string)
                && m.get("weights_hash").is_some_and(is_hash_value)
                && opt(m, "base_model", Value::is_string)
        }
        "router" | "config" => true,
        _ => false,
    }
}

/// `harness_manifest.schema.json`, minus the `protocol` const and the `kind` enum
/// (both reported with their own codes earlier in the validation order).
pub fn manifest_ok(v: &Value) -> bool {
    let Some(m) = v.as_object() else {
        return false;
    };
    if !has_keys(m, &["protocol", "type", "dimensions"])
        || !only_keys(
            m,
            &[
                "protocol",
                "type",
                "name",
                "parent_ids",
                "manifest_id",
                "dimensions",
            ],
        )
        || m["type"] != "harness_manifest"
        || !opt(m, "name", Value::is_string)
        || !opt(m, "parent_ids", |p| {
            p.as_array().is_some_and(|a| a.iter().all(is_hash_value))
        })
        || !opt(m, "manifest_id", is_hash_value)
    {
        return false;
    }
    let Some(dims) = m["dimensions"].as_object() else {
        return false;
    };
    dims.iter().all(|(name, d)| {
        let Some(d) = d.as_object() else {
            return false;
        };
        is_dimension_name(name)
            && has_keys(d, &["kind", "content"])
            && only_keys(d, &["kind", "content", "content_hash"])
            && opt(d, "content_hash", is_hash_value)
            && d["kind"]
                .as_str()
                .is_some_and(|k| content_ok(k, &d["content"]))
    })
}

/// `gate_result.schema.json`.
pub fn gate_result_ok(v: &Value) -> bool {
    let Some(m) = v.as_object() else {
        return false;
    };
    let req = [
        "suite",
        "suite_hash",
        "metrics",
        "thresholds",
        "passed",
        "evidence",
    ];
    has_keys(m, &req)
        && only_keys(m, &req)
        && m["suite"].is_string()
        && is_hash_value(&m["suite_hash"])
        && m["metrics"]
            .as_object()
            .is_some_and(|x| x.values().all(Value::is_number))
        && m["thresholds"].as_object().is_some_and(|x| {
            x.values().all(|t| {
                t.as_object().is_some_and(|t| {
                    has_keys(t, &["op", "value"])
                        && only_keys(t, &["op", "value"])
                        && t["op"]
                            .as_str()
                            .is_some_and(|o| [">=", ">", "<=", "<", "=="].contains(&o))
                        && t["value"].is_number()
                })
            })
        })
        && m["passed"].is_boolean()
        && m["evidence"]
            .as_array()
            .is_some_and(|a| a.iter().all(Value::is_string))
}

fn hash_list(v: &Value) -> bool {
    v.as_array().is_some_and(|a| a.iter().all(is_hash_value))
}

/// The body of an entry of the given kind.
pub fn body_ok(kind: &str, b: &Value) -> bool {
    let Some(m) = b.as_object() else {
        return false;
    };
    match kind {
        "run_start" => {
            let req = ["manifest_id", "started_at", "parent"];
            has_keys(m, &req)
                && only_keys(m, &req)
                && is_hash_value(&m["manifest_id"])
                && m["started_at"].is_string()
                && match &m["parent"] {
                    Value::Null => true,
                    Value::Object(p) => {
                        let req = ["run_id", "from_step", "checkpoint_ref"];
                        has_keys(p, &req)
                            && only_keys(p, &req)
                            && p["run_id"].is_string()
                            && is_nonneg_integer(&p["from_step"])
                            && str_or_null(&p["checkpoint_ref"])
                    }
                    _ => false,
                }
        }
        "step" => {
            let req = [
                "step_index",
                "manifest_id",
                "agent_id",
                "inputs",
                "outputs",
                "started_at",
                "ended_at",
                "tokens",
                "latency_ms",
                "checkpoint_ref",
            ];
            let mut all = req.to_vec();
            all.push("metrics");
            has_keys(m, &req)
                && only_keys(m, &all)
                && is_nonneg_integer(&m["step_index"])
                && is_hash_value(&m["manifest_id"])
                && m["agent_id"].is_string()
                && hash_list(&m["inputs"])
                && hash_list(&m["outputs"])
                && m["started_at"].is_string()
                && m["ended_at"].is_string()
                && m["tokens"].as_object().is_some_and(|t| {
                    has_keys(t, &["in", "out"])
                        && only_keys(t, &["in", "out"])
                        && is_nonneg_integer(&t["in"])
                        && is_nonneg_integer(&t["out"])
                })
                && m["latency_ms"].as_f64().is_some_and(|f| f >= 0.0)
                && opt(m, "metrics", |x| {
                    x.as_object()
                        .is_some_and(|x| x.values().all(Value::is_number))
                })
                && str_or_null(&m["checkpoint_ref"])
        }
        "patch" => {
            let req = [
                "patch_id",
                "from_manifest",
                "to_manifest",
                "semantic_diff",
                "rationale",
                "evidence",
                "author",
                "applied_at_step",
                "rollback_of",
                "gate_result",
            ];
            has_keys(m, &req)
                && only_keys(m, &req)
                && is_hash_value(&m["patch_id"])
                && is_hash_value(&m["from_manifest"])
                && is_hash_value(&m["to_manifest"])
                && m["semantic_diff"]
                    .as_array()
                    .is_some_and(|a| a.iter().all(Value::is_object))
                && m["rationale"].is_string()
                && m["evidence"]
                    .as_array()
                    .is_some_and(|a| a.iter().all(is_nonneg_integer))
                && author_ok(&m["author"])
                && is_nonneg_integer(&m["applied_at_step"])
                && (m["rollback_of"].is_null() || is_hash_value(&m["rollback_of"]))
                && (m["gate_result"].is_null() || gate_result_ok(&m["gate_result"]))
        }
        "run_end" => {
            let req = ["ended_at", "status"];
            has_keys(m, &req)
                && only_keys(m, &req)
                && m["ended_at"].is_string()
                && m["status"]
                    .as_str()
                    .is_some_and(|s| ["completed", "aborted", "failed"].contains(&s))
        }
        _ => false,
    }
}

pub fn author_ok(v: &Value) -> bool {
    v.as_object().is_some_and(|a| {
        has_keys(a, &["type", "id"])
            && only_keys(a, &["type", "id"])
            && a["type"]
                .as_str()
                .is_some_and(|t| t == "human" || t == "agent")
            && a["id"].is_string()
    })
}

/// `ledger_entry.schema.json` minus the `protocol` const.
pub fn entry_ok(v: &Value) -> bool {
    let Some(m) = v.as_object() else {
        return false;
    };
    let req = [
        "protocol",
        "type",
        "run_id",
        "seq",
        "prev_hash",
        "kind",
        "body",
        "entry_hash",
    ];
    has_keys(m, &req)
        && only_keys(m, &req)
        && m["protocol"].is_string()
        && m["type"] == "ledger_entry"
        && m["run_id"].as_str().is_some_and(|s| !s.is_empty())
        && is_nonneg_integer(&m["seq"])
        && (m["prev_hash"].is_null() || is_hash_value(&m["prev_hash"]))
        && is_hash_value(&m["entry_hash"])
        && m["kind"].as_str().is_some_and(|k| body_ok(k, &m["body"]))
}

/// Top level of `audit_bundle.schema.json`; manifests are checked one by one
/// in verification step 2, entries in step 3 (ADR-0006 §2).
pub fn bundle_shape_ok(v: &Value) -> bool {
    let Some(m) = v.as_object() else {
        return false;
    };
    let req = ["protocol", "type", "run_id", "manifests", "ledger"];
    has_keys(m, &req)
        && only_keys(m, &req)
        && m["type"] == "audit_bundle"
        && m["run_id"].is_string()
        && m["manifests"].is_object()
        && m["ledger"].is_array()
}
