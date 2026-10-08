//! A scripted MCP session against `agentvcs mcp` over real stdio: the tool
//! output must be the CLI's JSON for the same command.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};

const BIN: &str = env!("CARGO_BIN_EXE_agentvcs");

#[test]
fn scripted_stdio_session() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    std::fs::write(
        dir.join("m.json"),
        r#"{"protocol":"agentvcs/0.1","type":"harness_manifest","dimensions":{"p":{"kind":"prompt","content":{"template":"x"}}}}"#,
    )
    .unwrap();
    let mut child = Command::new(BIN)
        .args(["-C", dir.to_str().unwrap(), "mcp"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    let mut out = BufReader::new(child.stdout.take().unwrap());
    let mut id = 0;
    let mut call = |method: &str, params: Value| -> Value {
        id += 1;
        let msg = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        writeln!(stdin, "{msg}").unwrap();
        stdin.flush().unwrap();
        let mut line = String::new();
        out.read_line(&mut line).unwrap();
        let v: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(v["id"], id);
        v
    };
    let init = call(
        "initialize",
        json!({"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}),
    );
    assert_eq!(init["result"]["serverInfo"]["name"], "agentvcs");
    let tools = call("tools/list", json!({}));
    let names: Vec<&str> = tools["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    assert_eq!(names.len(), 21, "{names:?}");
    for n in [
        "init",
        "snapshot",
        "run_start",
        "step_record",
        "patch_apply",
        "verify",
        "blame",
        "export_audit",
        "merge_prepare",
        "merge_commit",
    ] {
        assert!(names.contains(&n), "{n}");
    }
    let tool = |name: &str, args: Value| -> Value { json!({"name": name, "arguments": args}) };
    let r = call("tools/call", tool("init", json!({})));
    assert_eq!(r["result"]["structuredContent"]["ok"], true);
    let snap = call(
        "tools/call",
        tool("snapshot", json!({"manifest": "m.json"})),
    );
    let mid = snap["result"]["structuredContent"]["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();
    // same JSON as the CLI
    let cli = Command::new(BIN)
        .args(["-C", dir.to_str().unwrap(), "snapshot", "m.json", "--json"])
        .output()
        .unwrap();
    let cli_text = String::from_utf8(cli.stdout).unwrap();
    assert_eq!(
        snap["result"]["content"][0]["text"].as_str().unwrap(),
        cli_text.trim()
    );

    let r = call(
        "tools/call",
        tool("run_start", json!({"manifest": mid, "run_id": "m1"})),
    );
    assert_eq!(r["result"]["structuredContent"]["run_id"], "m1");
    let body = json!({"agent_id": "a", "inputs": [], "outputs": [], "started_at": "t", "ended_at": "t",
                      "tokens": {"in": 1, "out": 1}, "latency_ms": 1, "metrics": {"f1": 0.5}});
    let r = call(
        "tools/call",
        tool("step_record", json!({"run": "m1", "body": body})),
    );
    assert_eq!(r["result"]["structuredContent"]["step_index"], 0);
    let r = call("tools/call", tool("verify", json!({"target": "m1"})));
    assert_eq!(r["result"]["structuredContent"]["valid"], true);
    assert_eq!(r["result"]["isError"], false);
    let r = call(
        "tools/call",
        tool("blame", json!({"target": "m1", "metric": "f1"})),
    );
    assert_eq!(r["result"]["structuredContent"]["segments"][0]["mean"], 0.5);
    // merge: the same JSON as the CLI, a repeatable flag as an array
    let mf = |t: &str| {
        format!(
            r#"{{"protocol":"agentvcs/0.1","type":"harness_manifest","dimensions":{{"p":{{"kind":"prompt","content":{{"template":"{t}"}}}}}}}}"#
        )
    };
    std::fs::write(dir.join("o.json"), mf("o")).unwrap();
    std::fs::write(dir.join("t.json"), mf("t")).unwrap();
    let cli_json = |args: &[&str]| -> String {
        let o = Command::new(BIN)
            .args(["-C", dir.to_str().unwrap()])
            .args(args)
            .arg("--json")
            .output()
            .unwrap();
        String::from_utf8(o.stdout).unwrap().trim().to_owned()
    };
    let r = call(
        "tools/call",
        tool(
            "merge_prepare",
            json!({"base": mid, "ours": "o.json", "theirs": "t.json", "ours_run": "m1",
                   "metric": ["f1", "loss"]}),
        ),
    );
    let prep = &r["result"]["structuredContent"];
    assert_eq!(prep["conflicts"][0]["type"], "modify/modify");
    assert_eq!(
        r["result"]["content"][0]["text"].as_str().unwrap(),
        cli_json(&[
            "merge",
            "prepare",
            "--base",
            &mid,
            "--ours",
            "o.json",
            "--theirs",
            "t.json",
            "--ours-run",
            "m1",
            "--metric",
            "f1",
            "--metric",
            "loss",
        ])
    );
    let res = json!({"protocol": "agentvcs/0.1", "type": "merge_resolution",
        "merge_id": prep["merge_id"], "resolutions": {"p": {"take": "theirs"}},
        "rationale": "r", "author": {"type": "agent", "id": "t"}});
    std::fs::write(dir.join("res.json"), res.to_string()).unwrap();
    let r = call(
        "tools/call",
        tool(
            "merge_commit",
            json!({"base": mid, "ours": "o.json", "theirs": "t.json", "resolution": "res.json"}),
        ),
    );
    assert_eq!(r["result"]["structuredContent"]["gate"], Value::Null);
    assert_eq!(
        r["result"]["content"][0]["text"].as_str().unwrap(),
        cli_json(&[
            "merge",
            "commit",
            "--base",
            &mid,
            "--ours",
            "o.json",
            "--theirs",
            "t.json",
            "--resolution",
            "res.json",
        ])
    );
    // policy refusal surfaces as a tool error with the CLI's code
    let r = call("tools/call", tool("freeze", json!({"manifest_id": mid})));
    assert_eq!(r["result"]["isError"], true);
    assert_eq!(
        r["result"]["structuredContent"]["error"]["code"],
        "E_NOT_GATED"
    );
    assert_eq!(r["result"]["_meta"]["exitCode"], 5);
    // bad arguments are E_USAGE
    let r = call("tools/call", tool("verify", json!({"nope": 1})));
    assert_eq!(r["result"]["structuredContent"]["error"]["code"], "E_USAGE");
    drop(stdin);
    assert!(child.wait().unwrap().success());
}
