//! The merge group of the conformance suite, run in-process (no gate: the
//! goldens never pass `--suite`).

use agentvcs_core::json::parse_bytes;
use agentvcs_core::manifest::normalize;
use agentvcs_core::testutil::{cases, subset_match};
use agentvcs_merge::{commit, prepare, record_id};
use serde_json::{json, Value};
use std::path::Path;

fn load(dir: &Path, name: &str) -> Value {
    parse_bytes(&std::fs::read(dir.join(name)).unwrap()).unwrap()
}

fn flag<'a>(argv: &'a [Value], name: &str) -> Vec<&'a str> {
    argv.windows(2)
        .filter(|w| w[0] == name)
        .map(|w| w[1].as_str().unwrap())
        .collect()
}

#[test]
fn merge_goldens() {
    let cs = cases("merge");
    assert_eq!(cs.len(), 19);
    for (dir, case) in cs {
        let argv = case["argv"].as_array().unwrap();
        let m = |f: &str| normalize(&load(&dir, flag(argv, f)[0])).unwrap();
        let (b, o, t) = (m("--base"), m("--ours"), m("--theirs"));
        let exp = &case["expect"];
        let out: Result<Value, agentvcs_core::Error> = match argv[1].as_str().unwrap() {
            "prepare" => {
                let run = |f: &str| flag(argv, f).first().map(|p| load(&dir, p));
                let metrics: Vec<String> = flag(argv, "--metric")
                    .into_iter()
                    .map(str::to_owned)
                    .collect();
                prepare(
                    &b,
                    &o,
                    &t,
                    run("--ours-run").as_ref(),
                    run("--theirs-run").as_ref(),
                    &metrics,
                )
                .map(|p| p.to_value())
            }
            "commit" => {
                let res = load(&dir, flag(argv, "--resolution")[0]);
                commit(&b, &o, &t, &res).map(|c| {
                    json!({"ok": true, "merge_id": c.record["merge_id"],
                           "merged": c.merged.manifest_id,
                           "record": record_id(&c.record).unwrap(), "gate": null})
                })
            }
            other => panic!("unknown merge subcommand {other}"),
        };
        match out {
            Ok(v) => {
                assert_eq!(exp["exit"], 0, "{}: got {v}", dir.display());
                if let Some(e) = subset_match(&exp["json"], &v, "$") {
                    panic!("{}: {e}", dir.display());
                }
            }
            Err(e) => {
                assert_eq!(exp["exit"], 3, "{}: {e}", dir.display());
                assert_eq!(e.code, exp["json"]["error"]["code"], "{}", dir.display());
            }
        }
    }
}
