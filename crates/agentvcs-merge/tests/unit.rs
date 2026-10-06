//! What the goldens do not pin: kind changes with equal content, the check order
//! of `commit`, evidence from a ledger with joint attribution, and invalid ledgers.

use agentvcs_core::hash::hash_value;
use agentvcs_core::ledger::{patch_body, run_start_body, RunState};
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_merge::{commit, merge_id, prepare, record_id};
use serde_json::{json, Value};

fn m(dims: Value) -> Manifest {
    normalize(&json!({"protocol": "agentvcs/0.1", "type": "harness_manifest", "dimensions": dims}))
        .unwrap()
}

fn prompt(t: &str) -> Value {
    json!({"kind": "prompt", "content": {"template": t}})
}

fn resolution(id: &str, res: Value) -> Value {
    json!({"protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": id,
           "resolutions": res, "rationale": "r", "author": {"type": "agent", "id": "t"}})
}

#[test]
fn merge_id_names_the_question() {
    let a = merge_id("b3:a", "b3:b", "b3:c").unwrap();
    assert_eq!(a, merge_id("b3:a", "b3:b", "b3:c").unwrap());
    assert_ne!(a, merge_id("b3:a", "b3:c", "b3:b").unwrap());
    assert_eq!(
        a,
        hash_value(
            &json!({"protocol": "agentvcs/0.1", "base": "b3:a", "ours": "b3:b", "theirs": "b3:c"})
        )
        .unwrap()
    );
}

#[test]
fn kind_change_with_equal_content_is_a_change() {
    // same content, different kind: content_hash is equal, the dimension is not
    let base = m(json!({"r": {"kind": "config", "content": {"x": 1}}}));
    let ours = m(json!({"r": {"kind": "router", "content": {"x": 1}}}));
    let p = prepare(&base, &ours, &base, None, None, &[]).unwrap();
    assert_eq!(
        p.auto,
        vec![json!({"dimension": "r", "resolution": "ours"})]
    );
    let theirs = m(json!({"r": {"kind": "config", "content": {"x": 2}}}));
    let p = prepare(&base, &ours, &theirs, None, None, &[]).unwrap();
    assert!(p.auto.is_empty());
    assert_eq!(p.conflicts[0]["type"], "modify/modify");
    assert_eq!(p.conflicts[0]["diff_ours"]["op"], "kind_changed");
}

#[test]
fn conflict_types_and_sorting() {
    let base = m(json!({"b": prompt("b0"), "c": prompt("c0")}));
    let ours = m(json!({"a": prompt("a1"), "b": prompt("b1")}));
    let theirs = m(json!({"a": prompt("a2"), "c": prompt("c2")}));
    let p = prepare(&base, &ours, &theirs, None, None, &[]).unwrap();
    let types: Vec<(&str, &str)> = p
        .conflicts
        .iter()
        .map(|c| {
            (
                c["dimension"].as_str().unwrap(),
                c["type"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        types,
        [
            ("a", "add/add"),
            ("b", "modify/delete"),
            ("c", "delete/modify")
        ]
    );
    assert_eq!(p.conflicts[0]["base"], Value::Null);
    assert_eq!(p.conflicts[1]["theirs"], Value::Null);
    assert_eq!(p.conflicts[1]["diff_theirs"]["op"], "removed");
    assert_eq!(
        p.conflicts[2]["evidence"],
        json!({"ours": [], "theirs": []})
    );
}

fn three() -> (Manifest, Manifest, Manifest, String) {
    let base = m(json!({"a": prompt("a0"), "b": prompt("b0")}));
    let ours = m(json!({"a": prompt("a1"), "b": prompt("b1")}));
    let theirs = m(json!({"a": prompt("a2")}));
    let id = merge_id(&base.manifest_id, &ours.manifest_id, &theirs.manifest_id).unwrap();
    (base, ours, theirs, id)
}

#[test]
fn commit_check_order_follows_the_spec() {
    let (b, o, t, id) = three();
    let code = |r: Value| commit(&b, &o, &t, &r).err().map(|e| e.code);
    // a bad `take` value is a schema error, before staleness
    assert_eq!(
        code(resolution(
            &format!("b3:{}", "0".repeat(64)),
            json!({"a": {"take": "mine"}, "b": {"take": "ours"}})
        )),
        Some("E_SCHEMA")
    );
    // a resolution with both take and content is a schema error
    assert_eq!(
        code(resolution(
            &id,
            json!({"a": {"take": "ours", "content": {}, "kind": "prompt"}, "b": {"take": "ours"}})
        )),
        Some("E_SCHEMA")
    );
    // unknown keys and a missing author are schema errors
    let mut r = resolution(&id, json!({"a": {"take": "ours"}, "b": {"take": "ours"}}));
    r["extra"] = json!(1);
    assert_eq!(code(r), Some("E_SCHEMA"));
    let mut r = resolution(&id, json!({"a": {"take": "ours"}, "b": {"take": "ours"}}));
    r.as_object_mut().unwrap().remove("author");
    assert_eq!(code(r), Some("E_SCHEMA"));
    let mut r = resolution(&id, json!({"a": {"take": "ours"}, "b": {"take": "ours"}}));
    r["protocol"] = json!("agentvcs/0.0");
    assert_eq!(code(r), Some("E_PROTOCOL_VERSION"));
    // E_MERGE_TAKE (on "b", sorted after "a") is checked before content validity on "a"
    assert_eq!(
        code(resolution(
            &id,
            json!({"a": {"kind": "prompt", "content": {}}, "b": {"take": "theirs"}})
        )),
        Some("E_MERGE_TAKE")
    );
    assert_eq!(
        code(resolution(
            &id,
            json!({"a": {"kind": "nope", "content": {}}, "b": {"take": "ours"}})
        )),
        Some("E_UNKNOWN_KIND")
    );
    // content is validated as its kind, not only for required keys
    assert_eq!(
        code(resolution(
            &id,
            json!({"a": {"kind": "sampling", "content": {"temperature": "hot"}}, "b": {"take": "ours"}})
        )),
        Some("E_SCHEMA")
    );
}

#[test]
fn commit_builds_the_merged_manifest() {
    let (b, o, t, id) = three();
    let r = resolution(
        &id,
        json!({"a": {"take": "base"}, "b": {"kind": "config", "content": {"value": 3}}}),
    );
    let c = commit(&b, &o, &t, &r).unwrap();
    assert_eq!(
        c.merged.value["parent_ids"],
        json!([o.manifest_id, t.manifest_id])
    );
    assert_eq!(c.merged.dimensions()["a"], b.dimensions()["a"]);
    assert_eq!(c.merged.dimensions()["b"]["kind"], "config");
    assert_eq!(c.record["type"], "merge_record");
    assert_eq!(c.record["resolution"], r);
    assert_eq!(c.record["gate"], Value::Null);
    assert_eq!(
        record_id(&c.record).unwrap(),
        hash_value(&c.record).unwrap()
    );
    // delete removes the dimension; take base on add/add is refused
    let r = resolution(
        &id,
        json!({"a": {"take": "delete"}, "b": {"take": "delete"}}),
    );
    let c = commit(&b, &o, &t, &r).unwrap();
    assert!(c.merged.dimensions().is_empty());
    let base = m(json!({}));
    let ours = m(json!({"x": prompt("1")}));
    let theirs = m(json!({"x": prompt("2")}));
    let id = merge_id(&base.manifest_id, &ours.manifest_id, &theirs.manifest_id).unwrap();
    let r = resolution(&id, json!({"x": {"take": "base"}}));
    assert_eq!(
        commit(&base, &ours, &theirs, &r).unwrap_err().code,
        "E_MERGE_TAKE"
    );
}

// ------------------------------------------------------------------ evidence

fn gate(f1: f64) -> Value {
    json!({"suite": "s", "suite_hash": hash_value(&json!("s")).unwrap(), "metrics": {"f1": f1},
           "thresholds": {"f1": {"op": ">=", "value": 0.0}}, "passed": true, "evidence": []})
}

struct Run {
    st: RunState,
    ledger: Vec<Value>,
    manifests: serde_json::Map<String, Value>,
}

impl Run {
    fn new(m0: &Manifest) -> Run {
        let mut r = Run {
            st: RunState::new("r"),
            ledger: vec![],
            manifests: Default::default(),
        };
        r.manifests.insert(m0.manifest_id.clone(), m0.value.clone());
        r.push("run_start", run_start_body(&m0.manifest_id, "t", None));
        r
    }
    fn push(&mut self, kind: &str, body: Value) {
        let (e, _) = self.st.append(kind, body).unwrap();
        self.ledger.push(e);
    }
    fn step(&mut self, f1: f64) {
        let b = json!({"step_index": self.st.next_step, "manifest_id": self.st.active,
            "agent_id": "a", "inputs": [], "outputs": [], "started_at": "t", "ended_at": "t",
            "tokens": {"in": 1, "out": 1}, "latency_ms": 1, "metrics": {"f1": f1},
            "checkpoint_ref": null});
        self.push("step", b);
    }
    fn patch(&mut self, to: &Manifest, why: &str) -> String {
        let from = self.st.active.clone().unwrap();
        self.manifests
            .insert(to.manifest_id.clone(), to.value.clone());
        let fm = normalize(&self.manifests[&from]).unwrap();
        let d = Value::Array(agentvcs_diff::diff(&fm, to).changes);
        let b = patch_body(
            &from,
            &to.manifest_id,
            d,
            why,
            vec![],
            json!({"type": "agent", "id": "sup"}),
            self.st.next_step,
            None,
            Some(gate(0.9)),
        )
        .unwrap();
        let pid = b["patch_id"].as_str().unwrap().to_owned();
        self.push("patch", b);
        pid
    }
    fn bundle(&self) -> Value {
        json!({"protocol": "agentvcs/0.1", "type": "audit_bundle", "run_id": "r",
               "manifests": self.manifests, "ledger": self.ledger})
    }
}

#[test]
fn evidence_blame_is_null_when_attribution_is_joint() {
    let base =
        m(json!({"p": prompt("0"), "s": {"kind": "sampling", "content": {"temperature": 0.2}}}));
    let o1 =
        m(json!({"p": prompt("1"), "s": {"kind": "sampling", "content": {"temperature": 0.2}}}));
    let o2 =
        m(json!({"p": prompt("1"), "s": {"kind": "sampling", "content": {"temperature": 0.1}}}));
    let o3 =
        m(json!({"p": prompt("3"), "s": {"kind": "sampling", "content": {"temperature": 0.1}}}));
    let mut run = Run::new(&base);
    run.step(0.2);
    let p1 = run.patch(&o1, "prompt");
    let p2 = run.patch(&o2, "sampling"); // same boundary as p1: joint
    run.step(0.5);
    let p3 = run.patch(&o3, "prompt again");
    run.step(0.6);
    let theirs =
        m(json!({"p": prompt("x"), "s": {"kind": "sampling", "content": {"temperature": 0.3}}}));
    let metrics = vec!["f1".to_owned(), "absent".to_owned()];
    let p = prepare(&base, &o3, &theirs, Some(&run.bundle()), None, &metrics).unwrap();
    let ev = |d: &str| {
        p.conflicts.iter().find(|c| c["dimension"] == d).unwrap()["evidence"]["ours"].clone()
    };
    let ep = ev("p");
    assert_eq!(ep.as_array().unwrap().len(), 2);
    assert_eq!(ep[0]["patch_id"], p1.as_str());
    assert_eq!(ep[0]["blame"], json!({"f1": null, "absent": null}));
    assert_eq!(ep[1]["patch_id"], p3.as_str());
    assert!((ep[1]["blame"]["f1"].as_f64().unwrap() - 0.1).abs() < 1e-9);
    assert_eq!(ep[1]["blame"]["absent"], Value::Null);
    assert_eq!(
        ep[1]["gate"],
        json!({"passed": true, "metrics": {"f1": 0.9}})
    );
    assert_eq!(ep[1]["applied_at_step"], 2);
    let es = ev("s");
    assert_eq!(es.as_array().unwrap().len(), 1);
    assert_eq!(es[0]["patch_id"], p2.as_str());
    assert_eq!(es[0]["blame"]["f1"], Value::Null);
}

#[test]
fn evidence_from_a_ledger_that_does_not_verify_is_refused() {
    let base = m(json!({"p": prompt("0")}));
    let ours = m(json!({"p": prompt("1")}));
    let theirs = m(json!({"p": prompt("2")}));
    let mut run = Run::new(&base);
    run.step(0.2);
    run.patch(&ours, "x");
    let mut b = run.bundle();
    b["ledger"][2]["body"]["rationale"] = json!("rewritten after the fact");
    let e = prepare(&base, &ours, &theirs, Some(&b), None, &[]).unwrap_err();
    assert_eq!(e.code, "E_INVALID_LEDGER");
}
