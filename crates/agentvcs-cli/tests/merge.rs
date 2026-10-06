//! Merge end to end through the real binary (spec/MERGE.md, v0.2 draft): two
//! lines diverge from a base, one of them through a gated patch in a run; the
//! prepared conflict carries that patch as evidence; a synthesised resolution is
//! committed and gated; the merged manifest goes back into the run as a patch
//! citing the merge record, and the ledger still verifies.

use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

const BIN: &str = env!("CARGO_BIN_EXE_agentvcs");

fn avcs_stdin(dir: &Path, args: &[&str], stdin: Option<&str>) -> (i32, Value) {
    let mut child = Command::new(BIN)
        .arg("-C")
        .arg(dir)
        .args(args)
        .arg("--json")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn agentvcs");
    {
        let mut si = child.stdin.take().unwrap();
        if let Some(s) = stdin {
            si.write_all(s.as_bytes()).unwrap();
        }
    }
    let o = child.wait_with_output().unwrap();
    let text = String::from_utf8(o.stdout).unwrap();
    let v: Value = serde_json::from_str(text.trim())
        .unwrap_or_else(|_| panic!("{args:?}: stdout is not one JSON object: {text:?}"));
    (o.status.code().unwrap(), v)
}

fn ok(dir: &Path, args: &[&str]) -> Value {
    let (code, v) = avcs_stdin(dir, args, None);
    assert_eq!(code, 0, "{args:?} -> {v}");
    assert_eq!(v["ok"], true);
    v
}

fn manifest(template: &str, temperature: f64) -> Value {
    json!({
        "protocol": "agentvcs/0.1", "type": "harness_manifest", "name": "toy",
        "dimensions": {
            "extract.prompt": {"kind": "prompt", "content": {"template": template, "variables": ["clause"]}},
            "extract.model": {"kind": "model", "content": {"provider": "llama.cpp", "id": "gemma-4-12b"}},
            "extract.sampling": {"kind": "sampling", "content": {"temperature": temperature}}
        }
    })
}

fn write(dir: &Path, name: &str, v: &str) {
    std::fs::write(dir.join(name), v).unwrap();
}

fn step(dir: &Path, run: &str, f1: f64) {
    let body = json!({
        "agent_id": "extractor", "inputs": [], "outputs": [],
        "started_at": "2026-10-06T12:00:00Z", "ended_at": "2026-10-06T12:00:01Z",
        "tokens": {"in": 10, "out": 5}, "latency_ms": 12.5, "metrics": {"f1": f1}
    })
    .to_string();
    let (code, v) = avcs_stdin(dir, &["step", "record", run], Some(&body));
    assert_eq!(code, 0, "{v}");
}

const BASE: &str = "Find every {clause} clause.\nQuote it verbatim.";
const OURS: &str = "Find every {clause} clause.\nQuote it verbatim, including any cap amount.";
const THEIRS: &str = "Find every {clause} clause.\nQuote it verbatim and cite its section.";
const SYNTH: &str =
    "Find every {clause} clause.\nQuote it verbatim, including any cap amount, and cite its section.";

#[test]
fn diverge_prepare_commit_apply_verify() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    ok(dir, &["init"]);
    write(dir, "base.json", &manifest(BASE, 0.2).to_string());
    write(dir, "ours.json", &manifest(OURS, 0.2).to_string());
    // theirs changes the prompt too (conflict) and the sampling (mechanical)
    write(dir, "theirs.json", &manifest(THEIRS, 0.1).to_string());
    let base = ok(dir, &["snapshot", "base.json"])["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();

    // ours: a run under base, patched (gated) to ours, which lifts f1
    ok(
        dir,
        &["run", "start", "--manifest", &base, "--run-id", "r1"],
    );
    step(dir, "r1", 0.30);
    step(dir, "r1", 0.32);
    let p = ok(
        dir,
        &[
            "patch",
            "propose",
            "r1",
            "--from",
            &base,
            "--to",
            "ours.json",
            "--rationale",
            "quote cap amounts",
            "--author",
            "agent:supervisor",
        ],
    );
    let pid = p["patch_id"].as_str().unwrap().to_owned();
    write(
        dir,
        "suite.yaml",
        "name: smoke\ncommand: \"echo '{\\\"metrics\\\": {\\\"f1\\\": 0.8}}'\"\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n",
    );
    ok(dir, &["gate", "run", &pid, "--suite", "suite.yaml"]);
    let applied = ok(dir, &["patch", "apply", &pid]);
    let ours = applied["active_manifest"].as_str().unwrap().to_owned();
    step(dir, "r1", 0.70);
    step(dir, "r1", 0.74);

    // prepare: the prompt conflicts, the sampling merges, the patch is evidence
    let prep = ok(
        dir,
        &[
            "merge",
            "prepare",
            "--base",
            &base,
            "--ours",
            &ours,
            "--theirs",
            "theirs.json",
            "--ours-run",
            "r1",
            "--metric",
            "f1",
            "--metric",
            "latency",
        ],
    );
    assert_eq!(prep["ours"], ours.as_str());
    let auto: Vec<(&str, &str)> = prep["auto"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| {
            (
                a["dimension"].as_str().unwrap(),
                a["resolution"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        auto,
        [("extract.model", "same"), ("extract.sampling", "theirs")]
    );
    let c = &prep["conflicts"][0];
    assert_eq!(prep["conflicts"].as_array().unwrap().len(), 1);
    assert_eq!(
        (c["dimension"].as_str(), c["type"].as_str()),
        (Some("extract.prompt"), Some("modify/modify"))
    );
    let ev = c["evidence"]["ours"].as_array().unwrap();
    assert_eq!(ev.len(), 1);
    assert_eq!(ev[0]["patch_id"], pid.as_str());
    assert_eq!(ev[0]["applied_at_step"], 2);
    assert_eq!(
        ev[0]["gate"],
        json!({"passed": true, "metrics": {"f1": 0.8}})
    );
    assert!((ev[0]["blame"]["f1"].as_f64().unwrap() - 0.41).abs() < 1e-9);
    assert_eq!(ev[0]["blame"]["latency"], Value::Null);
    assert_eq!(c["evidence"]["theirs"], json!([]));
    // the same evidence from an exported bundle
    ok(dir, &["export", "audit", "r1", "-o", "r1.json"]);
    let prep2 = ok(
        dir,
        &[
            "merge",
            "prepare",
            "--base",
            "base.json",
            "--ours",
            &ours,
            "--theirs",
            "theirs.json",
            "--ours-run",
            "r1.json",
            "--metric",
            "f1",
            "--metric",
            "latency",
        ],
    );
    assert_eq!(prep2, prep);
    check_with_reference(dir, &ours, &prep);

    // the agent's resolution: a synthesis of both prompts
    let merge_id = prep["merge_id"].as_str().unwrap();
    let res = json!({
        "protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": merge_id,
        "resolutions": {"extract.prompt": {"kind": "prompt",
            "content": {"template": SYNTH, "variables": ["clause"]}}},
        "rationale": "ours fixed cap extraction (gated, +0.41 f1); kept theirs' citation line",
        "author": {"type": "agent", "id": "claude-code"}
    });
    write(dir, "res.json", &res.to_string());

    // a failing gate is exit 1, and the record is still stored
    write(
        dir,
        "strict.yaml",
        "command: \"echo '{\\\"f1\\\": 0.6}'\"\nthresholds:\n  f1: {op: \">=\", value: 0.9}\n",
    );
    let args = [
        "merge",
        "commit",
        "--base",
        &base,
        "--ours",
        &ours,
        "--theirs",
        "theirs.json",
        "--resolution",
        "res.json",
    ];
    let (code, rejected) = avcs_stdin(
        dir,
        &[&args[..], &["--suite", "strict.yaml"]].concat(),
        None,
    );
    assert_eq!(code, 1, "{rejected}");
    assert_eq!(rejected["ok"], true);
    assert_eq!(rejected["gate"]["passed"], false);
    let rec_path = |id: &str| {
        let hex = &id[3..];
        dir.join(".agentvcs/objects")
            .join(&hex[..2])
            .join(&hex[2..])
    };
    assert!(rec_path(rejected["record"].as_str().unwrap()).is_file());

    // the passing gate sees the merged manifest in the store
    write(
        dir,
        "merge-suite.yaml",
        "name: merge-smoke\ncommand: >-\n  grep -q 'cite its section' \"$AGENTVCS_MANIFEST_FILE\" &&\n  test \"$AGENTVCS_FROM_MANIFEST\" != \"$AGENTVCS_TO_MANIFEST\" &&\n  test -d \"$AGENTVCS_STORE\" &&\n  echo '{\"metrics\": {\"f1\": 0.81}}'\nthresholds:\n  f1: {op: \">=\", value: 0.75}\n",
    );
    let committed = ok(dir, &[&args[..], &["--suite", "merge-suite.yaml"]].concat());
    assert_eq!(committed["merge_id"], merge_id);
    assert_eq!(committed["gate"]["passed"], true);
    assert_eq!(committed["gate"]["metrics"], json!({"f1": 0.81}));
    assert_ne!(committed["record"], rejected["record"]);
    let merged = committed["merged"].as_str().unwrap().to_owned();
    let record_id = committed["record"].as_str().unwrap().to_owned();
    let record: Value =
        serde_json::from_slice(&std::fs::read(rec_path(&record_id)).unwrap()).unwrap();
    assert_eq!(record["type"], "merge_record");
    assert_eq!(record["merged"], merged.as_str());
    assert_eq!(record["resolution"], res);
    assert_eq!(record["gate"]["passed"], true);
    let (code, d2) = avcs_stdin(dir, &["diff", &ours, &merged], None);
    assert_eq!(code, 0);
    let changed: Vec<&str> = d2["changes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["dimension"].as_str().unwrap())
        .collect();
    assert_eq!(changed, ["extract.prompt", "extract.sampling"]);
    let stored: Value = serde_json::from_slice(
        &std::fs::read(
            dir.join(".agentvcs/manifests")
                .join(format!("{}.json", &merged[3..])),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(stored["parent_ids"], json!([ours, prep["theirs"]]));

    // the same resolution against stale manifests is refused
    let (code, v) = avcs_stdin(
        dir,
        &[
            "merge",
            "commit",
            "--base",
            &base,
            "--ours",
            "ours.json",
            "--theirs",
            &ours,
            "--resolution",
            "res.json",
        ],
        None,
    );
    assert_eq!(
        (code, v["error"]["code"].as_str()),
        (3, Some("E_MERGE_STALE"))
    );

    // apply the merge to the running system: an ordinary gated patch
    let rationale = format!("merge:{record_id}");
    let p = ok(
        dir,
        &[
            "patch",
            "propose",
            "r1",
            "--from",
            &ours,
            "--to",
            &merged,
            "--rationale",
            &rationale,
            "--author",
            "agent:claude-code",
        ],
    );
    let mpid = p["patch_id"].as_str().unwrap().to_owned();
    ok(dir, &["gate", "run", &mpid, "--suite", "merge-suite.yaml"]);
    let a = ok(dir, &["patch", "apply", &mpid]);
    assert_eq!(a["active_manifest"], merged.as_str());
    step(dir, "r1", 0.80);
    ok(dir, &["run", "end", "r1"]);
    let v = ok(dir, &["verify", "r1"]);
    assert_eq!(v["valid"], true, "{v}");
    let b = ok(dir, &["blame", "r1", "--metric", "f1"]);
    let last = b["attributions"]
        .as_array()
        .unwrap()
        .last()
        .unwrap()
        .clone();
    assert_eq!(last["patches"], json!([mpid]));
}

#[test]
fn merge_usage_errors() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    ok(dir, &["init"]);
    let (code, v) = avcs_stdin(dir, &["merge", "prepare", "--base", "x"], None);
    assert_eq!((code, v["error"]["code"].as_str()), (2, Some("E_USAGE")));
    write(dir, "m.json", &manifest(BASE, 0.2).to_string());
    let (code, v) = avcs_stdin(
        dir,
        &[
            "merge",
            "prepare",
            "--base",
            "m.json",
            "--ours",
            "m.json",
            "--theirs",
            "m.json",
            "--ours-run",
            "nope",
        ],
        None,
    );
    assert_eq!(
        (code, v["error"]["code"].as_str()),
        (4, Some("E_NOT_FOUND"))
    );
    let (code, v) = avcs_stdin(
        dir,
        &[
            "merge",
            "commit",
            "--base",
            "m.json",
            "--ours",
            "m.json",
            "--theirs",
            "m.json",
            "--resolution",
            "m.json",
        ],
        None,
    );
    assert_eq!((code, v["error"]["code"].as_str()), (3, Some("E_SCHEMA")));
}

/// `conformance/tools/ref.py`'s `merge_prepare` on the same inputs must give the
/// same JSON (skipped loudly without Python `blake3`, required in CI).
fn check_with_reference(dir: &Path, ours: &str, prep: &Value) {
    let tools = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../conformance/tools");
    let py = std::env::var("AGENTVCS_TEST_PYTHON").unwrap_or_else(|_| "python3".into());
    let ours_file = dir
        .join(".agentvcs/manifests")
        .join(format!("{}.json", &ours[3..]));
    let script = format!(
        "import json,sys; sys.path.insert(0, {:?}); import ref\n\
         L=lambda p: json.load(open(p))\n\
         print(json.dumps(ref.merge_prepare(L({:?}), L({:?}), L({:?}), L({:?}), None, ['f1', 'latency'])))",
        tools.to_str().unwrap(),
        dir.join("base.json").to_str().unwrap(),
        ours_file.to_str().unwrap(),
        dir.join("theirs.json").to_str().unwrap(),
        dir.join("r1.json").to_str().unwrap(),
    );
    let required = std::env::var_os("AGENTVCS_REQUIRE_REFERENCE").is_some();
    match Command::new(&py).arg("-c").arg(&script).output() {
        Ok(o) if String::from_utf8_lossy(&o.stderr).contains("No module named 'blake3'") => {
            assert!(!required, "reference check required but blake3 is missing");
            eprintln!("SKIP reference check: python blake3 module not installed");
        }
        Ok(o) => {
            assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
            let r: Value = serde_json::from_slice(&o.stdout).unwrap();
            if let Some(e) = agentvcs_core::testutil::subset_match(&r, prep, "$") {
                panic!("ref.py merge_prepare disagrees: {e}");
            }
        }
        Err(_) => {
            assert!(!required, "reference check required but {py} is missing");
            eprintln!("SKIP reference check: {py} not found");
        }
    }
}
