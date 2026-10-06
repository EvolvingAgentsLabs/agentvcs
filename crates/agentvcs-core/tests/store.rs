//! The local store (ADR-0004): objects, manifests, ledgers, index.

use agentvcs_core::ledger::{run_start_body, RunState};
use agentvcs_core::manifest::normalize;
use agentvcs_core::store::Store;
use serde_json::{json, Value};

fn manifest(t: &str, name: &str) -> Value {
    json!({
        "protocol": "agentvcs/0.1", "type": "harness_manifest", "name": name,
        "dimensions": {"p": {"kind": "prompt", "content": {"template": t}}}
    })
}

fn step() -> Value {
    json!({"agent_id": "a", "inputs": [], "outputs": [], "started_at": "t", "ended_at": "t",
           "tokens": {"in": 1, "out": 1}, "latency_ms": 1, "checkpoint_ref": null})
}

#[test]
fn open_without_init_is_no_store() {
    let d = tempfile::tempdir().unwrap();
    assert_eq!(Store::open(d.path()).unwrap_err().code, "E_NO_STORE");
    Store::init(d.path()).unwrap();
    Store::init(d.path()).unwrap(); // idempotent
    Store::open(d.path()).unwrap();
}

#[test]
fn blobs_are_content_addressed() {
    let d = tempfile::tempdir().unwrap();
    let s = Store::init(d.path()).unwrap();
    let id = s.put_blob(b"hello").unwrap();
    assert_eq!(id, agentvcs_core::hash::b3_bytes(b"hello"));
    assert_eq!(s.get_object(&id).unwrap(), b"hello");
    let missing = format!("b3:{}", "0".repeat(64));
    assert_eq!(s.get_object(&missing).unwrap_err().code, "E_NOT_FOUND");
    let j = s.put_json(&json!({"b": 1, "a": 2.0})).unwrap();
    assert_eq!(s.get_object(&j).unwrap(), br#"{"a":2,"b":1}"#);
}

#[test]
fn manifests_first_annotation_wins() {
    let d = tempfile::tempdir().unwrap();
    let s = Store::init(d.path()).unwrap();
    let a = normalize(&manifest("x", "first")).unwrap();
    let b = normalize(&manifest("x", "second")).unwrap();
    assert_eq!(a.manifest_id, b.manifest_id);
    s.put_manifest(&a).unwrap();
    s.put_manifest(&b).unwrap();
    let got = s.get_manifest(&a.manifest_id).unwrap();
    assert_eq!(got.value["name"], "first");
    // contents are stored as objects under their content hash
    let ch = got.value["dimensions"]["p"]["content_hash"]
        .as_str()
        .unwrap();
    assert_eq!(s.get_object(ch).unwrap(), br#"{"template":"x"}"#);
}

#[test]
fn ledger_tail_gives_the_writer_state() {
    let d = tempfile::tempdir().unwrap();
    let s = Store::init(d.path()).unwrap();
    let m = normalize(&manifest("x", "m")).unwrap();
    s.put_manifest(&m).unwrap();
    let mut st = RunState::new("r1");
    s.append(
        &mut st,
        "run_start",
        run_start_body(&m.manifest_id, "t", None),
    )
    .unwrap();
    for _ in 0..5 {
        let mut b = step().as_object().unwrap().clone();
        st.fill_step(&mut b).unwrap();
        s.append(&mut st, "step", Value::Object(b)).unwrap();
    }
    let from_disk = s.run_state("r1").unwrap();
    assert_eq!(from_disk, st);
    assert_eq!(from_disk.next_step, 5);
    assert_eq!(s.read_ledger("r1").unwrap().len(), 6);
    // a stale writer state cannot fork the chain
    let mut stale = RunState::new("r1");
    assert!(s
        .append(
            &mut stale,
            "run_start",
            run_start_body(&m.manifest_id, "t", None)
        )
        .is_err());
    assert_eq!(s.run_state("nope").unwrap_err().code, "E_NOT_FOUND");
}

#[test]
fn run_ids_are_safe_file_names() {
    let d = tempfile::tempdir().unwrap();
    let s = Store::init(d.path()).unwrap();
    for bad in ["", "../x", "a/b", ".hidden", "a b"] {
        assert_eq!(s.run_state(bad).unwrap_err().code, "E_USAGE", "{bad:?}");
    }
}

#[test]
fn index_is_rebuildable() {
    let d = tempfile::tempdir().unwrap();
    let s = Store::init(d.path()).unwrap();
    let m = normalize(&manifest("x", "m")).unwrap();
    s.put_manifest(&m).unwrap();
    let mut st = RunState::new("r1");
    s.append(
        &mut st,
        "run_start",
        run_start_body(&m.manifest_id, "t", None),
    )
    .unwrap();
    let before = s.index_snapshot().unwrap();
    std::fs::remove_file(d.path().join(".agentvcs/index.sqlite")).unwrap();
    let s = Store::open(d.path()).unwrap();
    s.rebuild_index().unwrap();
    assert_eq!(s.index_snapshot().unwrap(), before);
}
