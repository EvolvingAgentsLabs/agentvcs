//! `bisect`: binary search over the patches of a run for the first one under
//! which a metric turns bad (`spec/cli/COMMANDS.md`; no goldens in v0.1).
//!
//! Candidates are the manifests the run went through: `M0` = the run_start
//! manifest, `Mi` = `to_manifest` of the i-th patch in ledger order. Like git
//! bisect it assumes monotonicity: `M0` good, `Mk` bad, and once bad, bad. The
//! probe re-executes the run from the first patch's `applied_at_step` (restoring
//! the checkpoint of the step before it) under one candidate and reports the
//! metric. Probing is the caller's business (the CLI runs `--exec`), so this
//! module is pure and testable.

use agentvcs_core::ledger::as_index;
use agentvcs_core::{Error, Result};
use serde_json::{json, Value};
use std::collections::HashMap;

/// `--bad <cond>`: when a metric value counts as bad, e.g. `<0.5`, `>=10`.
#[derive(Debug, Clone, PartialEq)]
pub struct BadCond {
    pub op: String,
    pub value: f64,
}

impl BadCond {
    pub fn parse(s: &str) -> Result<Self> {
        let s = s.trim();
        for op in ["<=", ">=", "==", "!=", "<", ">"] {
            if let Some(rest) = s.strip_prefix(op) {
                let value: f64 = rest.trim().parse().map_err(|_| {
                    Error::new("E_USAGE", format!("--bad: cannot read a number in {s:?}"))
                })?;
                return Ok(BadCond {
                    op: op.into(),
                    value,
                });
            }
        }
        Err(Error::new(
            "E_USAGE",
            "--bad must be <op><number>, op one of < <= > >= == !=",
        ))
    }

    pub fn is_bad(&self, x: f64) -> bool {
        match self.op.as_str() {
            "<" => x < self.value,
            "<=" => x <= self.value,
            ">" => x > self.value,
            ">=" => x >= self.value,
            "==" => x == self.value,
            _ => x != self.value,
        }
    }
}

/// What a probe needs to re-execute one candidate.
#[derive(Debug, Clone, PartialEq)]
pub struct Plan {
    pub run_id: String,
    pub from_step: u64,
    pub checkpoint_ref: Option<String>,
    /// `(patch_id or None for M0, manifest_id)`, in order.
    pub candidates: Vec<(Option<String>, String)>,
}

/// Extract the candidates of a run from its (verified) ledger entries.
pub fn plan(run_id: &str, ledger: &[Value]) -> Result<Plan> {
    let start = ledger
        .first()
        .filter(|e| e["kind"] == "run_start")
        .ok_or_else(|| Error::new("E_FIRST_NOT_RUN_START", "run has no run_start"))?;
    let mut candidates = vec![(
        None,
        start["body"]["manifest_id"]
            .as_str()
            .unwrap_or_default()
            .to_owned(),
    )];
    let mut from_step = None;
    let mut checkpoints: HashMap<u64, Option<String>> = HashMap::new();
    for e in ledger {
        let b = &e["body"];
        match e["kind"].as_str() {
            Some("step") => {
                if let Some(i) = as_index(&b["step_index"]) {
                    checkpoints.insert(i, b["checkpoint_ref"].as_str().map(str::to_owned));
                }
            }
            Some("patch") => {
                from_step.get_or_insert(as_index(&b["applied_at_step"]).unwrap_or(0));
                candidates.push((
                    b["patch_id"].as_str().map(str::to_owned),
                    b["to_manifest"].as_str().unwrap_or_default().to_owned(),
                ));
            }
            _ => {}
        }
    }
    let from_step = from_step.ok_or_else(|| Error::new("E_NOT_FOUND", "run has no patches"))?;
    let checkpoint_ref = from_step
        .checked_sub(1)
        .and_then(|p| checkpoints.get(&p).cloned().flatten());
    Ok(Plan {
        run_id: run_id.into(),
        from_step,
        checkpoint_ref,
        candidates,
    })
}

/// One probe of the search.
#[derive(Debug, Clone, PartialEq)]
pub struct Probe {
    pub candidate: usize,
    pub patch_id: Option<String>,
    pub manifest_id: String,
    pub metric: f64,
    pub bad: bool,
}

/// The result of the search.
#[derive(Debug, Clone, PartialEq)]
pub struct Outcome {
    pub first_bad_patch: Option<String>,
    pub probes: Vec<Probe>,
    pub reason: Option<String>,
}

impl Outcome {
    pub fn to_value(&self) -> Value {
        let probes: Vec<Value> = self
            .probes
            .iter()
            .map(|p| {
                json!({"candidate": p.candidate, "patch_id": p.patch_id,
                       "manifest_id": p.manifest_id, "metric": p.metric, "bad": p.bad})
            })
            .collect();
        let mut v = json!({"ok": true, "first_bad_patch": self.first_bad_patch, "probes": probes});
        if let Some(r) = &self.reason {
            v["reason"] = r.clone().into();
        }
        v
    }
}

/// Binary search. `probe(manifest_id)` returns the metric of one re-execution;
/// results are cached by manifest (a rollback revisits one).
pub fn search<F>(plan: &Plan, cond: &BadCond, mut probe: F) -> Result<Outcome>
where
    F: FnMut(&str) -> Result<f64>,
{
    let mut probes = Vec::new();
    let mut cache: HashMap<String, f64> = HashMap::new();
    let mut is_bad = |i: usize, probes: &mut Vec<Probe>| -> Result<bool> {
        let (pid, mid) = &plan.candidates[i];
        let metric = match cache.get(mid) {
            Some(m) => *m,
            None => {
                let m = probe(mid)?;
                cache.insert(mid.clone(), m);
                m
            }
        };
        let bad = cond.is_bad(metric);
        probes.push(Probe {
            candidate: i,
            patch_id: pid.clone(),
            manifest_id: mid.clone(),
            metric,
            bad,
        });
        Ok(bad)
    };
    let k = plan.candidates.len() - 1;
    let done = |reason: &str, probes| Outcome {
        first_bad_patch: None,
        probes,
        reason: Some(reason.into()),
    };
    if is_bad(0, &mut probes)? {
        return Ok(done("the run_start manifest is already bad", probes));
    }
    if !is_bad(k, &mut probes)? {
        return Ok(done("the last manifest is not bad", probes));
    }
    let (mut lo, mut hi) = (0, k);
    while hi - lo > 1 {
        let mid = (lo + hi) / 2;
        if is_bad(mid, &mut probes)? {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    Ok(Outcome {
        first_bad_patch: plan.candidates[hi].0.clone(),
        probes,
        reason: None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan_of(n: usize) -> Plan {
        Plan {
            run_id: "r".into(),
            from_step: 3,
            checkpoint_ref: None,
            candidates: (0..=n)
                .map(|i| ((i > 0).then(|| format!("P{i}")), format!("M{i}")))
                .collect(),
        }
    }

    #[test]
    fn finds_first_bad_with_log_probes() {
        let cond = BadCond::parse("<0.5").unwrap();
        for n in 1..40 {
            for first_bad in 1..=n {
                let p = plan_of(n);
                let out = search(&p, &cond, |m| {
                    let i: usize = m[1..].parse().unwrap();
                    Ok(if i >= first_bad { 0.1 } else { 0.9 })
                })
                .unwrap();
                assert_eq!(out.first_bad_patch, Some(format!("P{first_bad}")));
                let bound = 2 + (n as f64).log2().ceil() as usize;
                assert!(
                    out.probes.len() <= bound,
                    "{n} {first_bad} {}",
                    out.probes.len()
                );
            }
        }
    }

    #[test]
    fn endpoints() {
        let cond = BadCond::parse(">= 10").unwrap();
        let p = plan_of(3);
        let all_bad = search(&p, &cond, |_| Ok(11.0)).unwrap();
        assert_eq!(all_bad.first_bad_patch, None);
        assert!(all_bad.reason.unwrap().contains("already bad"));
        let none_bad = search(&p, &cond, |_| Ok(1.0)).unwrap();
        assert_eq!(none_bad.first_bad_patch, None);
    }

    #[test]
    fn cond_parse() {
        assert!(BadCond::parse("~3").is_err());
        assert!(BadCond::parse("<x").is_err());
        assert!(BadCond::parse("!=2").unwrap().is_bad(3.0));
    }
}
