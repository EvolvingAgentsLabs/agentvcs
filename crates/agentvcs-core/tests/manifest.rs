//! Manifest normalization and validation order (`spec/PROTOCOL.md §2`).

use agentvcs_core::json::parse;
use agentvcs_core::manifest::normalize;
use serde_json::{json, Value};

fn code(v: Value) -> &'static str {
    normalize(&v).expect_err("should be invalid").code
}

fn base() -> Value {
    json!({
        "protocol": "agentvcs/0.1",
        "type": "harness_manifest",
        "dimensions": {
            "p": {"kind": "prompt", "content": {"template": "hi {x}", "variables": ["x"]}},
            "s": {"kind": "sampling", "content": {"temperature": 1.0}}
        }
    })
}

#[test]
fn empty_manifest_has_published_id() {
    let m =
        parse(r#"{"protocol":"agentvcs/0.1","type":"harness_manifest","dimensions":{}}"#).unwrap();
    let n = normalize(&m).unwrap();
    assert_eq!(
        n.manifest_id,
        "b3:d16c08db075a56fdab36c30890155896d908ad0dbbe244ab319c26bd179c5c0d"
    );
}

#[test]
fn filled_form_round_trips_and_annotations_do_not_count() {
    let n = normalize(&base()).unwrap();
    let filled = n.value.clone();
    assert_eq!(normalize(&filled).unwrap().manifest_id, n.manifest_id);
    let mut annotated = base();
    annotated["name"] = json!("v2");
    annotated["parent_ids"] = json!([n.manifest_id.clone()]);
    assert_eq!(normalize(&annotated).unwrap().manifest_id, n.manifest_id);
}

#[test]
fn int_and_float_are_the_same_value() {
    let mut a = base();
    a["dimensions"]["s"]["content"]["temperature"] = json!(1);
    assert_eq!(
        normalize(&a).unwrap().manifest_id,
        normalize(&base()).unwrap().manifest_id
    );
}

#[test]
fn errors() {
    let mut m = base();
    m["protocol"] = json!("agentvcs/9");
    assert_eq!(code(m), "E_PROTOCOL_VERSION");

    let mut m = base();
    m["dimensions"]["s"]["kind"] = json!("weights");
    assert_eq!(code(m), "E_UNKNOWN_KIND");

    let mut m = base();
    m["dimensions"]["p"]["content"] = json!({"variables": []});
    assert_eq!(code(m), "E_SCHEMA");

    let mut m = base();
    m["dimensions"]["p"]["content_hash"] = json!(format!("b3:{}", "0".repeat(64)));
    assert_eq!(code(m), "E_CONTENT_HASH");

    let mut m = base();
    m["manifest_id"] = json!(format!("b3:{}", "0".repeat(64)));
    assert_eq!(code(m), "E_MANIFEST_ID");

    let mut m = base();
    m["dimensions"]["Bad Name"] = json!({"kind": "config", "content": {}});
    assert_eq!(code(m), "E_SCHEMA");

    let mut m = base();
    m["extra"] = json!(1);
    assert_eq!(code(m), "E_SCHEMA");

    let mut m = base();
    m["dimensions"]["t"] = json!({"kind": "tool", "content": {"name": "x", "signature": {}}});
    assert_eq!(code(m), "E_SCHEMA");

    let mut m = base();
    m["dimensions"]["p"]["content"]["variables"] = json!(["x", "x"]);
    assert_eq!(code(m), "E_SCHEMA");
}

#[test]
fn validation_order_kind_before_schema_before_hashes() {
    // a schema error in one dimension and an unknown kind in another: kind wins
    let mut m = base();
    m["dimensions"]["a"] = json!({"kind": "prompt", "content": {}});
    m["dimensions"]["z"] = json!({"kind": "nope", "content": {}});
    assert_eq!(code(m), "E_UNKNOWN_KIND");
    // a schema error and a wrong content hash: schema wins
    let mut m = base();
    m["dimensions"]["a"] = json!({"kind": "prompt", "content": {}});
    m["dimensions"]["p"]["content_hash"] = json!(format!("b3:{}", "0".repeat(64)));
    assert_eq!(code(m), "E_SCHEMA");
    // protocol before kind
    let mut m = base();
    m["protocol"] = json!("x");
    m["dimensions"]["z"] = json!({"kind": "nope", "content": {}});
    assert_eq!(code(m), "E_PROTOCOL_VERSION");
}
