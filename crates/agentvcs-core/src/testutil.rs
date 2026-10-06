//! Helpers shared by tests across crates (golden-case loading and matching).

use crate::json::parse_bytes;
use serde_json::Value;
use std::path::{Path, PathBuf};

/// `conformance/cases` of this repository.
pub fn cases_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../conformance/cases")
}

/// Every case directory of a group, sorted.
pub fn cases(group: &str) -> Vec<(PathBuf, Value)> {
    let mut out: Vec<_> = std::fs::read_dir(cases_dir())
        .expect("conformance/cases")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.starts_with(&format!("{group}-")))
        })
        .map(|p| {
            let c = parse_bytes(&std::fs::read(p.join("case.json")).unwrap()).unwrap();
            (p, c)
        })
        .collect();
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

/// The conformance runner's subset match (run.py `match`).
pub fn subset_match(exp: &Value, act: &Value, path: &str) -> Option<String> {
    match exp {
        Value::Object(m) => {
            let Some(a) = act.as_object() else {
                return Some(format!("{path}: expected object"));
            };
            for (k, v) in m {
                match a.get(k) {
                    None => return Some(format!("{path}.{k}: missing")),
                    Some(x) => {
                        if let Some(e) = subset_match(v, x, &format!("{path}.{k}")) {
                            return Some(e);
                        }
                    }
                }
            }
            None
        }
        Value::Array(e) => match act.as_array() {
            Some(a) if a.len() == e.len() => e
                .iter()
                .zip(a)
                .enumerate()
                .find_map(|(i, (x, y))| subset_match(x, y, &format!("{path}[{i}]"))),
            _ => Some(format!("{path}: expected list of {}, got {act}", e.len())),
        },
        Value::Number(n) => match act.as_f64() {
            Some(a) if (n.as_f64().unwrap() - a).abs() <= 1e-9 => None,
            _ => Some(format!("{path}: expected {n}, got {act}")),
        },
        _ => (exp != act).then(|| format!("{path}: expected {exp}, got {act}")),
    }
}
