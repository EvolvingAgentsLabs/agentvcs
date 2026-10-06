//! The verify and blame groups of the conformance suite, run in-process.

use agentvcs_core::json::parse_bytes;
use agentvcs_core::testutil::{cases, subset_match};
use agentvcs_query::{blame, verify};

fn bundle(dir: &std::path::Path) -> serde_json::Value {
    parse_bytes(&std::fs::read(dir.join("bundle.json")).unwrap()).unwrap()
}

#[test]
fn verify_goldens() {
    let cs = cases("verify");
    assert_eq!(cs.len(), 31);
    for (dir, case) in cs {
        let r = verify(&bundle(&dir));
        let out = r.to_value();
        let exp = &case["expect"];
        let exit = if r.valid { 0 } else { 1 };
        assert_eq!(exit, exp["exit"].as_i64().unwrap(), "{}", dir.display());
        if let Some(e) = subset_match(&exp["json"], &out, "$") {
            panic!("{}: {e}", dir.display());
        }
        if let Some(fv) = exp.get("first_violation") {
            let got = &out["violations"][0];
            if let Some(e) = subset_match(fv, got, "$.violations[0]") {
                panic!("{}: {e}; all: {}", dir.display(), out["violations"]);
            }
        }
    }
}

#[test]
fn blame_goldens() {
    let cs = cases("blame");
    assert_eq!(cs.len(), 8);
    for (dir, case) in cs {
        let argv = case["argv"].as_array().unwrap();
        let metric = argv[3].as_str().unwrap();
        let exp = &case["expect"];
        match blame(&bundle(&dir), metric) {
            Ok(b) => {
                assert_eq!(exp["exit"], 0, "{}", dir.display());
                let mut out = b.to_value();
                out["ok"] = true.into();
                if let Some(e) = subset_match(&exp["json"], &out, "$") {
                    panic!("{}: {e}", dir.display());
                }
            }
            Err(e) => {
                assert_eq!(exp["exit"], 3, "{}", dir.display());
                assert_eq!(e.code, exp["json"]["error"]["code"], "{}", dir.display());
            }
        }
    }
}
