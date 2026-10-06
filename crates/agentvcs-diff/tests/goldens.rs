//! The diff group of the conformance suite, run in-process.

use agentvcs_core::json::parse_bytes;
use agentvcs_core::testutil::{cases, subset_match};
use agentvcs_diff::diff_values;
use serde_json::Value;

#[test]
fn diff_goldens() {
    let cs = cases("diff");
    assert_eq!(cs.len(), 16);
    for (dir, case) in cs {
        let argv = case["argv"].as_array().unwrap();
        let load = |i: usize| {
            parse_bytes(&std::fs::read(dir.join(argv[i].as_str().unwrap())).unwrap()).unwrap()
        };
        let d = diff_values(&load(1), &load(2)).unwrap();
        let mut out = d.to_value();
        out.as_object_mut()
            .unwrap()
            .insert("ok".into(), Value::Bool(true));
        if let Some(e) = subset_match(&case["expect"]["json"], &out, "$") {
            panic!("{}: {e}", dir.display());
        }
    }
}
