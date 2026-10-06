//! End-to-end lifecycle through the real binary: init → snapshot → run start →
//! steps → patch propose → gate run → patch apply → more steps → rollback →
//! export audit → verify → blame, plus the commands no golden covers.

use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

const BIN: &str = env!("CARGO_BIN_EXE_agentvcs");

struct Out {
    code: i32,
    json: Value,
}

fn avcs(dir: &Path, args: &[&str]) -> Out {
    avcs_stdin(dir, args, None)
}

fn avcs_stdin(dir: &Path, args: &[&str], stdin: Option<&str>) -> Out {
    let mut cmd = Command::new(BIN);
    cmd.arg("-C").arg(dir).args(args).arg("--json");
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = cmd.spawn().expect("spawn agentvcs");
    {
        let mut si = child.stdin.take().unwrap();
        if let Some(s) = stdin {
            si.write_all(s.as_bytes()).unwrap();
        }
    }
    let o = child.wait_with_output().unwrap();
    let text = String::from_utf8(o.stdout).unwrap();
    let json: Value = serde_json::from_str(text.trim())
        .unwrap_or_else(|_| panic!("{args:?}: stdout is not one JSON object: {text:?}"));
    Out {
        code: o.status.code().unwrap(),
        json,
    }
}

fn ok(dir: &Path, args: &[&str]) -> Value {
    let o = avcs(dir, args);
    assert_eq!(o.code, 0, "{args:?} -> {}", o.json);
    assert_eq!(o.json["ok"], true);
    o.json
}

fn manifest(template: &str, model: &str) -> Value {
    json!({
        "protocol": "agentvcs/0.1", "type": "harness_manifest", "name": "toy",
        "dimensions": {
            "extract.prompt": {"kind": "prompt", "content": {"template": template, "variables": ["clause"]}},
            "extract.model": {"kind": "model", "content": {"provider": "llama.cpp", "id": model}},
            "extract.sampling": {"kind": "sampling", "content": {"temperature": 0.2}}
        }
    })
}

fn step(f1: f64, ckpt: &str) -> String {
    json!({
        "agent_id": "extractor", "inputs": [], "outputs": [],
        "started_at": "2026-10-06T12:00:00Z", "ended_at": "2026-10-06T12:00:01Z",
        "tokens": {"in": 10, "out": 5}, "latency_ms": 12.5,
        "metrics": {"f1": f1}, "checkpoint_ref": ckpt
    })
    .to_string()
}

fn write(dir: &Path, name: &str, v: &str) {
    std::fs::write(dir.join(name), v).unwrap();
}

fn record(dir: &Path, run: &str, f1: f64, ckpt: &str) -> Value {
    let o = avcs_stdin(dir, &["step", "record", run], Some(&step(f1, ckpt)));
    assert_eq!(o.code, 0, "{}", o.json);
    o.json
}

#[test]
fn full_lifecycle() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();

    // no store yet
    let o = avcs(dir, &["run", "start", "--manifest", "b3:x"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (4, Some("E_NO_STORE"))
    );

    assert_eq!(ok(dir, &["init"])["store"], ".agentvcs");
    ok(dir, &["init"]); // idempotent

    write(
        dir,
        "a.json",
        &manifest("Find every {clause}.", "gemma-4-12b").to_string(),
    );
    write(
        dir,
        "b.json",
        &manifest("Find every {clause}.\nAlso the cap amount.", "gemma-4-12b").to_string(),
    );
    write(
        dir,
        "c.yaml",
        "protocol: agentvcs/0.1\ntype: harness_manifest\ndimensions:\n  extract.prompt:\n    kind: prompt\n    content:\n      template: \"bad\"\n",
    );
    let a = ok(dir, &["snapshot", "a.json"])["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let b = ok(dir, &["snapshot", "b.json"])["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let c = ok(dir, &["snapshot", "c.yaml"])["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_ne!(a, b);

    // diff by store ids
    let df = ok(dir, &["diff", &a, &b]);
    assert_eq!(df["identical"], false);
    assert_eq!(df["changes"][0]["details"]["template"]["lines_added"], 1);

    // run start
    let r = ok(dir, &["run", "start", "--manifest", &a, "--run-id", "r1"]);
    assert_eq!(r["run_id"], "r1");
    let o = avcs(dir, &["run", "start", "--manifest", &a, "--run-id", "r1"]);
    assert_eq!(o.json["error"]["code"], "E_RUN_EXISTS");

    // three steps under A
    for i in 0..3 {
        let s = record(dir, "r1", 0.4, &format!("ckpt-{i}"));
        assert_eq!(s["seq"], i + 1);
        assert_eq!(s["step_index"], i);
    }
    // a step that names the wrong manifest is refused
    let bad = step(0.4, "x").replace(
        "\"agent_id\"",
        &format!("\"manifest_id\":\"{b}\",\"agent_id\""),
    );
    let o = avcs_stdin(dir, &["step", "record", "r1"], Some(&bad));
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (3, Some("E_STEP_MANIFEST"))
    );
    let o = avcs_stdin(dir, &["step", "record", "r1"], Some("{not json"));
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (3, Some("E_SCHEMA"))
    );

    // propose A -> B
    let p = ok(
        dir,
        &[
            "patch",
            "propose",
            "r1",
            "--from",
            &a,
            "--to",
            "b.json",
            "--rationale",
            "never asks for the cap",
            "--evidence",
            "0,1,2",
            "--author",
            "agent:supervisor-v0",
        ],
    );
    let pid = p["patch_id"].as_str().unwrap().to_owned();
    assert_eq!(p["semantic_diff"][0]["dimension"], "extract.prompt");

    // ungated apply is refused by policy
    let o = avcs(dir, &["patch", "apply", &pid, "--at-step", "3"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (5, Some("E_PATCH_UNGATED"))
    );

    // a failing gate is a negative answer (exit 1) and still refuses apply
    write(dir, "fail.yaml", "name: smoke\ncommand: |-\n  echo '{\"f1\": 0.1}'\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n");
    let o = avcs(dir, &["gate", "run", &pid, "--suite", "fail.yaml"]);
    assert_eq!(o.code, 1, "{}", o.json);
    assert_eq!(o.json["gate_result"]["passed"], false);
    let o = avcs(dir, &["patch", "apply", &pid, "--at-step", "3"]);
    assert_eq!(o.code, 5);

    // the suite's command sees the patch in its environment
    write(
        dir,
        "pass.yaml",
        "name: cuad-smoke\ncommand: |-\n  test \"$AGENTVCS_TO_MANIFEST\" = \"$AGENTVCS_MANIFEST\" && test -f \"$AGENTVCS_MANIFEST_FILE\" && echo '{\"metrics\": {\"f1\": 0.8}}'\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n",
    );
    let g = ok(dir, &["gate", "run", &pid, "--suite", "pass.yaml"]);
    assert_eq!(g["gate_result"]["passed"], true);
    assert_eq!(g["gate_result"]["suite"], "cuad-smoke");

    // a broken suite command is an error, not a failed gate
    write(
        dir,
        "broken.yaml",
        "command: exit 7\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n",
    );
    let o = avcs(dir, &["gate", "run", &pid, "--suite", "broken.yaml"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (3, Some("E_GATE_COMMAND"))
    );

    // wrong step is refused, right step applies
    let o = avcs(dir, &["patch", "apply", &pid, "--at-step", "7"]);
    assert_eq!(o.json["error"]["code"], "E_PATCH_STEP");
    let ap = ok(dir, &["patch", "apply", &pid, "--at-step", "3"]);
    assert_eq!(ap["active_manifest"], b.as_str());

    // two steps under B
    for _ in 0..2 {
        record(dir, "r1", 0.9, "ckpt-b");
    }
    // freeze: B has a passed gate, A has none
    let f = ok(dir, &["freeze", &b]);
    assert_eq!(f["frozen"], true);
    let o = avcs(dir, &["freeze", &a]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (5, Some("E_NOT_GATED"))
    );

    // rollback needs no gate
    let rb = ok(dir, &["patch", "rollback", &pid]);
    assert_eq!(rb["active_manifest"], a.as_str());
    assert_eq!(rb["rollback_of"], pid.as_str());
    let o = avcs(dir, &["patch", "rollback", &pid]);
    assert_eq!(o.json["error"]["code"], "E_PATCH_FROM", "{}", o.json);
    record(dir, "r1", 0.5, "ckpt-a2");

    // log
    let lg = ok(dir, &["log", "r1"]);
    let kinds: Vec<&str> = lg["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["kind"].as_str().unwrap())
        .collect();
    assert_eq!(
        kinds,
        [
            "run_start",
            "step",
            "step",
            "step",
            "patch",
            "step",
            "step",
            "patch",
            "step"
        ]
    );

    // run end
    let e = ok(dir, &["run", "end", "r1"]);
    assert_eq!(e["entries"], 10);
    let o = avcs_stdin(dir, &["step", "record", "r1"], Some(&step(0.1, "x")));
    assert_eq!(o.json["error"]["code"], "E_AFTER_RUN_END");

    // export audit, refuse to overwrite without --yes
    let x = ok(dir, &["export", "audit", "r1", "-o", "bundle.json"]);
    assert_eq!(x["entries"], 10);
    let o = avcs(dir, &["export", "audit", "r1", "-o", "bundle.json"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (2, Some("E_EXISTS"))
    );
    ok(
        dir,
        &["export", "audit", "r1", "-o", "bundle.json", "--yes"],
    );
    let inline = ok(dir, &["export", "audit", "r1"]);
    assert_eq!(inline["bundle"]["type"], "audit_bundle");

    // verify the bundle file and the run in the store
    let v = ok(dir, &["verify", "bundle.json"]);
    assert_eq!(
        (
            v["valid"].as_bool(),
            v["open"].as_bool(),
            v["entries"].as_u64()
        ),
        (Some(true), Some(false), Some(10))
    );
    assert_eq!(ok(dir, &["verify", "r1"])["valid"], true);

    // blame: A(0.4) | B(0.9) | A(0.5)
    let bl = ok(dir, &["blame", "bundle.json", "--metric", "f1"]);
    let segs = bl["segments"].as_array().unwrap();
    assert_eq!(segs.len(), 3);
    assert_eq!(segs[1]["introduced_by"], json!([pid]));
    assert!((bl["attributions"][0]["delta"].as_f64().unwrap() - 0.5).abs() < 1e-9);
    assert_eq!(bl["attributions"][1]["patches"][0], rb["patch_id"]);

    // a tampered bundle no longer verifies, and blame refuses it
    let text = std::fs::read_to_string(dir.join("bundle.json")).unwrap();
    write(
        dir,
        "tampered.json",
        &text.replacen("never asks for the cap", "never asks for the cap!", 1),
    );
    let o = avcs(dir, &["verify", "tampered.json"]);
    assert_eq!((o.code, o.json["valid"].as_bool()), (1, Some(false)));
    let o = avcs(dir, &["blame", "tampered.json", "--metric", "f1"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (3, Some("E_INVALID_LEDGER"))
    );

    // resume from step 2: the child starts at step_index 2 with step 1's checkpoint
    let rs = ok(
        dir,
        &[
            "resume",
            "r1",
            "--from-step",
            "2",
            "--manifest",
            &c,
            "--run-id",
            "r1-child",
        ],
    );
    assert_eq!(rs["parent"]["from_step"], 2);
    assert_eq!(rs["checkpoint_ref"], "ckpt-1");
    let s = record(dir, "r1-child", 0.7, "c");
    assert_eq!(s["step_index"], 2);
    assert_eq!(ok(dir, &["verify", "r1-child"])["valid"], true);

    // the exported bundle agrees with the reference semantics when available
    check_with_reference(dir.join("bundle.json").as_path());
}

/// Run `conformance/tools/ref.py` verify on a bundle if Python with `blake3` is
/// available; skip (loudly) otherwise.
fn check_with_reference(bundle: &Path) {
    let tools = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../conformance/tools");
    let py = std::env::var("AGENTVCS_TEST_PYTHON").unwrap_or_else(|_| "python3".into());
    let script = format!(
        "import json,sys; sys.path.insert(0, {:?}); import ref; r = ref.verify(json.load(open({:?}))); print(json.dumps(r)); sys.exit(0 if r['valid'] else 1)",
        tools.to_str().unwrap(),
        bundle.to_str().unwrap()
    );
    let required = std::env::var_os("AGENTVCS_REQUIRE_REFERENCE").is_some();
    match Command::new(&py).arg("-c").arg(&script).output() {
        Ok(o) if String::from_utf8_lossy(&o.stderr).contains("No module named 'blake3'") => {
            assert!(!required, "reference check required but blake3 is missing");
            eprintln!("SKIP reference check: python blake3 module not installed");
        }
        Ok(o) => assert!(
            o.status.success(),
            "reference verify disagrees: {}{}",
            String::from_utf8_lossy(&o.stdout),
            String::from_utf8_lossy(&o.stderr)
        ),
        Err(_) => {
            assert!(!required, "reference check required but {py} is missing");
            eprintln!("SKIP reference check: {py} not found")
        }
    }
}

#[test]
fn bisect_finds_the_bad_patch() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    ok(dir, &["init"]);
    let mut ids = Vec::new();
    for i in 0..5 {
        write(
            dir,
            &format!("m{i}.json"),
            &manifest(&format!("v{i}"), "m").to_string(),
        );
        ids.push(
            ok(dir, &["snapshot", &format!("m{i}.json")])["manifest_id"]
                .as_str()
                .unwrap()
                .to_owned(),
        );
    }
    ok(
        dir,
        &["run", "start", "--manifest", &ids[0], "--run-id", "b"],
    );
    record(dir, "b", 0.9, "k0");
    write(
        dir,
        "pass.yaml",
        "command: |-\n  echo '{\"f1\": 1}'\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n",
    );
    let mut pids = Vec::new();
    for i in 1..5 {
        let p = ok(
            dir,
            &[
                "patch",
                "propose",
                "b",
                "--from",
                &ids[i - 1],
                "--to",
                &ids[i],
                "--rationale",
                &format!("p{i}"),
            ],
        );
        let pid = p["patch_id"].as_str().unwrap().to_owned();
        ok(dir, &["gate", "run", &pid, "--suite", "pass.yaml"]);
        ok(dir, &["patch", "apply", &pid]);
        record(dir, "b", 0.5, "k");
        pids.push(pid);
    }
    // manifests 3 and 4 are bad: the probe reads the template version from the manifest file
    write(
        dir,
        "probe.sh",
        &format!(
            "test \"$AGENTVCS_FROM_STEP\" = 1 || exit 9\ncase \"$AGENTVCS_MANIFEST\" in {}|{}) echo '{{\"f1\": 0.2}}';; *) echo 0.9;; esac\n",
            ids[3], ids[4]
        ),
    );
    let o = ok(
        dir,
        &[
            "bisect",
            "b",
            "--metric",
            "f1",
            "--bad",
            "<0.5",
            "--exec",
            "sh probe.sh",
        ],
    );
    assert_eq!(o["first_bad_patch"], pids[2].as_str(), "{o}");
    assert!(o["probes"].as_array().unwrap().len() <= 4);
}

#[test]
fn usage_and_store_errors() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    let o = avcs(dir, &["frobnicate"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (2, Some("E_USAGE"))
    );
    let o = avcs(dir, &["blame", "x.json"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (2, Some("E_USAGE"))
    );
    let o = avcs(dir, &["verify", "a", "b"]);
    assert_eq!(o.code, 2);
    let o = avcs(dir, &["hash", "f", "--nope"]);
    assert_eq!(o.code, 2);
    ok(dir, &["init"]);
    let o = avcs(dir, &["verify", "no-such-run"]);
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (4, Some("E_NOT_FOUND"))
    );
    let o = avcs(
        dir,
        &[
            "run",
            "start",
            "--manifest",
            &format!("b3:{}", "0".repeat(64)),
        ],
    );
    assert_eq!(
        (o.code, o.json["error"]["code"].as_str()),
        (4, Some("E_NOT_FOUND"))
    );
    // no prompt ever: stdin closed, output is still one JSON object
    let o = avcs_stdin(dir, &["step", "record", "nope"], Some(""));
    assert_eq!(o.json["ok"], false);
}
