//! Hash-chain properties (Gate F1 item 3): any single-byte tamper of any entry
//! is detected; appending valid entries keeps a valid ledger valid.

use agentvcs_core::json::{canonical, parse_bytes_with, Mode};
use agentvcs_core::ledger::LedgerBuilder;
use agentvcs_core::manifest::normalize;
use agentvcs_query::verify;
use proptest::prelude::*;
use serde_json::{json, Value};

fn manifest(t: &str) -> Value {
    normalize(&json!({
        "protocol": "agentvcs/0.1", "type": "harness_manifest",
        "dimensions": {"p": {"kind": "prompt", "content": {"template": t}}}
    }))
    .unwrap()
    .value
}

fn step_body(metric: f64) -> Value {
    json!({
        "agent_id": "a", "inputs": [], "outputs": [],
        "started_at": "t0", "ended_at": "t1",
        "tokens": {"in": 1, "out": 2}, "latency_ms": 3,
        "metrics": {"m": metric}, "checkpoint_ref": null
    })
}

/// A valid ledger: steps under A, a gated patch to B, more steps.
fn build(n_before: usize, n_after: usize) -> Value {
    let (a, b) = (manifest("one"), manifest("two"));
    let mut lb = LedgerBuilder::new("run-p", vec![a.clone(), b.clone()]);
    lb.run_start(a["manifest_id"].as_str().unwrap(), None)
        .unwrap();
    for i in 0..n_before {
        lb.step(step_body(i as f64 / 10.0)).unwrap();
    }
    let gate = json!({
        "suite": "s", "suite_hash": format!("b3:{}", "1".repeat(64)),
        "metrics": {"m": 1.0}, "thresholds": {"m": {"op": ">=", "value": 0.5}},
        "passed": true, "evidence": []
    });
    let d = agentvcs_diff::diff_values(&a, &b).unwrap();
    lb.patch_with_diff(
        b["manifest_id"].as_str().unwrap(),
        Value::Array(d.changes),
        "why",
        vec![0],
        json!({"type": "agent", "id": "x"}),
        None,
        Some(gate),
    )
    .unwrap();
    for i in 0..n_after {
        lb.step(step_body(i as f64)).unwrap();
    }
    lb.bundle()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(400))]

    #[test]
    fn single_byte_tamper_is_detected(
        before in 0usize..4, after in 0usize..4,
        pick in any::<prop::sample::Index>(), pos in any::<prop::sample::Index>(), byte in any::<u8>()
    ) {
        let b = build(before, after);
        prop_assert!(verify(&b).valid);
        let ledger = b["ledger"].as_array().unwrap();
        let i = pick.index(ledger.len());
        let mut line = canonical(&ledger[i]).unwrap().into_bytes();
        let p = pos.index(line.len());
        prop_assume!(line[p] != byte);
        line[p] = byte;
        // a tamper that breaks the JSON itself is detected by the parser
        match parse_bytes_with(&line, Mode::CanonicalForm) {
            Err(_) => {}
            Ok(e) => {
                let mut t = b.clone();
                t["ledger"][i] = e;
                let r = verify(&t);
                prop_assert!(!r.valid, "tamper at entry {} byte {} not detected", i, p);
            }
        }
    }

    #[test]
    fn appending_valid_entries_keeps_valid(before in 0usize..5, after in 0usize..20) {
        let b = build(before, after);
        prop_assert!(verify(&b).valid);
    }
}

#[test]
fn appending_step_by_step_stays_valid() {
    let a = manifest("one");
    let mut lb = LedgerBuilder::new("run-q", vec![a.clone()]);
    lb.run_start(a["manifest_id"].as_str().unwrap(), None)
        .unwrap();
    for i in 0..50 {
        lb.step(step_body(i as f64)).unwrap();
        assert!(verify(&lb.bundle()).valid);
    }
    lb.run_end("completed").unwrap();
    let r = verify(&lb.bundle());
    assert!(r.valid && !r.open);
}
