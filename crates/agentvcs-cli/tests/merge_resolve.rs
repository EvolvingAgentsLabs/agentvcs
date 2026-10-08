//! `merge resolve` (spec/MERGE.md §6) end to end through the real binary, with a
//! fake `claude` (tests/fake_claude/claude) that speaks stream-json and drives the
//! `agentvcs mcp --merge-session` server it is given. The real Claude Code is never
//! invoked here.

use agentvcs_core::store::Store;
use serde_json::{json, Value};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const BIN: &str = env!("CARGO_BIN_EXE_agentvcs");

fn fake_claude() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fake_claude/claude")
}

/// Run agentvcs in `dir` with extra environment variables.
fn avcs(dir: &Path, args: &[&str], env: &[(&str, &str)]) -> (i32, Value) {
    let mut c = Command::new(BIN);
    c.arg("-C").arg(dir).args(args).arg("--json");
    for (k, v) in env {
        c.env(k, v);
    }
    let mut child = c
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn agentvcs");
    drop(child.stdin.take());
    let o = child.wait_with_output().unwrap();
    let text = String::from_utf8(o.stdout).unwrap();
    let v: Value = serde_json::from_str(text.trim()).unwrap_or_else(|_| {
        panic!(
            "{args:?}: stdout is not one JSON object: {text:?}\nstderr: {}",
            String::from_utf8_lossy(&o.stderr)
        )
    });
    (o.status.code().unwrap(), v)
}

fn ok(dir: &Path, args: &[&str]) -> Value {
    let (code, v) = avcs(dir, args, &[]);
    assert_eq!(code, 0, "{args:?} -> {v}");
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

const BASE: &str = "Find every {clause} clause.\nQuote it verbatim.";
const OURS: &str = "Find every {clause} clause.\nQuote it verbatim, including any cap amount.";
const THEIRS: &str = "Find every {clause} clause.\nQuote it verbatim and cite its section.";

struct Fixture {
    _tmp: tempfile::TempDir,
    dir: PathBuf,
    base: String,
    ours: String,
}

/// A store with a run `r1` patched (gated) from base to ours; `theirs.json`
/// edits the same prompt (one conflict) and the sampling (mechanical).
fn diverged() -> Fixture {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().to_path_buf();
    ok(&dir, &["init"]);
    let w = |n: &str, v: &Value| std::fs::write(dir.join(n), v.to_string()).unwrap();
    w("base.json", &manifest(BASE, 0.2));
    w("ours.json", &manifest(OURS, 0.2));
    w("theirs.json", &manifest(THEIRS, 0.1));
    let base = ok(&dir, &["snapshot", "base.json"])["manifest_id"]
        .as_str()
        .unwrap()
        .to_owned();
    ok(
        &dir,
        &["run", "start", "--manifest", &base, "--run-id", "r1"],
    );
    let pid = ok(
        &dir,
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
    )["patch_id"]
        .as_str()
        .unwrap()
        .to_owned();
    std::fs::write(
        dir.join("suite.yaml"),
        "name: smoke\ncommand: \"echo '{\\\"metrics\\\": {\\\"f1\\\": 0.8}}'\"\nthresholds:\n  f1: {op: \">=\", value: 0.5}\n",
    )
    .unwrap();
    ok(&dir, &["gate", "run", &pid, "--suite", "suite.yaml"]);
    let ours = ok(&dir, &["patch", "apply", &pid])["active_manifest"]
        .as_str()
        .unwrap()
        .to_owned();
    Fixture {
        _tmp: tmp,
        dir,
        base,
        ours,
    }
}

/// Every file under the store, with its bytes: "nothing committed" means this
/// does not change.
fn store_files(dir: &Path) -> Vec<(PathBuf, Vec<u8>)> {
    fn walk(p: &Path, out: &mut Vec<(PathBuf, Vec<u8>)>) {
        for e in std::fs::read_dir(p).unwrap() {
            let p = e.unwrap().path();
            if p.is_dir() {
                walk(&p, out);
            } else if !p.to_string_lossy().contains("index") {
                out.push((p.clone(), std::fs::read(&p).unwrap()));
            }
        }
    }
    let mut v = Vec::new();
    walk(&dir.join(".agentvcs"), &mut v);
    v.sort();
    v
}

fn resolve_args<'a>(f: &'a Fixture, claude: &'a str, extra: &[&'a str]) -> Vec<&'a str> {
    let mut a = vec![
        "merge",
        "resolve",
        "--base",
        &f.base,
        "--ours",
        &f.ours,
        "--theirs",
        "theirs.json",
        "--ours-run",
        "r1",
        "--metric",
        "f1",
        "--claude",
        claude,
    ];
    a.extend_from_slice(extra);
    a
}

fn log_path(f: &Fixture) -> PathBuf {
    f.dir.join("fake-claude.json")
}

fn resolve(f: &Fixture, mode: &str, extra: &[&str]) -> (i32, Value) {
    let claude = fake_claude();
    let log = log_path(f);
    avcs(
        &f.dir,
        &resolve_args(f, claude.to_str().unwrap(), extra),
        &[
            ("FAKE_CLAUDE_MODE", mode),
            ("FAKE_CLAUDE_LOG", log.to_str().unwrap()),
        ],
    )
}

fn object(dir: &Path, id: &str) -> Vec<u8> {
    Store::open(dir).unwrap().get_object(id).unwrap()
}

/// The flags of spec/MERGE.md §6 step 4, in order, around the two paths and the prompt.
fn spec_flags(mcp_config: &str, prompt: &str) -> Vec<String> {
    let mut v: Vec<String> = [
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--restricted",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--tools",
        "Read",
        "--allowedTools",
        "Read,mcp__agentvcs__prepare,mcp__agentvcs__commit",
        "--mcp-config",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    v.push(mcp_config.into());
    v.push("--append-system-prompt".into());
    v.push(prompt.into());
    v
}

#[test]
fn resolve_commits_the_staged_resolution_and_records_the_resolver() {
    let f = diverged();
    let (code, out) = resolve(
        &f,
        "resolve",
        &[
            "--model",
            "claude-opus-5-5",
            "--budget-usd",
            "0.5",
            "--max-turns",
            "12",
            "--suite",
            "suite.yaml",
        ],
    );
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["ok"], true);
    assert_eq!(out["gate"]["passed"], true);
    let r = &out["resolver"];
    assert_eq!(r["agent"], "claude-code");
    assert_eq!(r["version"], "2.1.292 (Claude Code)");
    assert_eq!(r["model"], "claude-opus-5-5");
    assert_eq!(r["cost_usd"], 0.0421);
    assert_eq!(r["turns"], 5);

    // the record carries the resolver; the transcript is a blob in the store
    let record: Value =
        serde_json::from_slice(&object(&f.dir, out["record"].as_str().unwrap())).unwrap();
    assert_eq!(record["type"], "merge_record");
    assert_eq!(&record["resolver"], r);
    assert_eq!(
        record["resolution"]["author"],
        json!({"type": "agent", "id": "claude-code"})
    );
    assert_eq!(
        record["resolution"]["resolutions"],
        json!({"extract.prompt": {"take": "ours"}})
    );
    let transcript = String::from_utf8(object(&f.dir, r["transcript"].as_str().unwrap())).unwrap();
    assert!(transcript.contains("\"mcp__agentvcs__commit\""));
    assert!(transcript.lines().last().unwrap().contains("\"result\""));

    // the merged manifest: ours' prompt, theirs' sampling
    let merged = Store::open(&f.dir)
        .unwrap()
        .get_manifest(out["merged"].as_str().unwrap())
        .unwrap()
        .value;
    assert_eq!(
        merged["dimensions"]["extract.prompt"]["content"]["template"],
        OURS
    );
    assert_eq!(
        merged["dimensions"]["extract.sampling"]["content"]["temperature"],
        0.1
    );

    // what the agent was given: the workspace, the command line, the task
    let log: Value = serde_json::from_slice(&std::fs::read(log_path(&f)).unwrap()).unwrap();
    assert_eq!(
        log["files"],
        json!([
            "BRANCHES.md",
            "base.json",
            "ours.json",
            "prepare.json",
            "theirs.json"
        ])
    );
    let branches = log["branches"].as_str().unwrap();
    assert!(branches.contains("quote cap amounts"), "{branches}");
    let argv: Vec<String> = serde_json::from_value(log["argv"].clone()).unwrap();
    let mut want = spec_flags(&argv[17], &argv[19]);
    want.extend(
        [
            "--model",
            "claude-opus-5-5",
            "--max-budget-usd",
            "0.5",
            "--max-turns",
            "12",
        ]
        .map(String::from),
    );
    assert_eq!(argv, want);
    assert_eq!(argv[19], include_str!("../src/resolve_prompt.md"));
    assert!(!log["stdin"].as_str().unwrap().is_empty());
    let cwd = PathBuf::from(log["cwd"].as_str().unwrap());
    assert!(
        !cwd.starts_with(&f.dir),
        "workspace must not be the project"
    );
    assert!(
        !cwd.exists(),
        "workspace is removed after a committed merge"
    );

    // the same resolution through `merge commit` gives the same record minus `resolver`
    std::fs::write(f.dir.join("res.json"), record["resolution"].to_string()).unwrap();
    let c = ok(
        &f.dir,
        &[
            "merge",
            "commit",
            "--base",
            &f.base,
            "--ours",
            &f.ours,
            "--theirs",
            "theirs.json",
            "--resolution",
            "res.json",
            "--suite",
            "suite.yaml",
        ],
    );
    assert_eq!(c["merged"], out["merged"]);
    let plain: Value =
        serde_json::from_slice(&object(&f.dir, c["record"].as_str().unwrap())).unwrap();
    assert!(
        plain.get("resolver").is_none(),
        "merge commit has no resolver"
    );
    let mut without = record.clone();
    without.as_object_mut().unwrap().remove("resolver");
    // gate evidence blobs are equal too: same suite, same stdout
    assert_eq!(plain, without);
}

#[test]
fn the_last_valid_commit_is_the_one_staged() {
    let f = diverged();
    let (code, out) = resolve(&f, "invalid-then-ok", &[]);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["gate"], Value::Null);
    // no --model: the model is the one the session reports
    assert_eq!(out["resolver"]["model"], "fake-model");
}

#[test]
fn a_session_without_a_valid_commit_commits_nothing() {
    let f = diverged();
    let before = store_files(&f.dir);
    let (code, out) = resolve(&f, "nocommit", &[]);
    assert_eq!(
        (code, out["error"]["code"].as_str()),
        (1, Some("E_RESOLVER_NO_COMMIT")),
        "{out}"
    );
    assert_eq!(out["ok"], false);
    assert_eq!(store_files(&f.dir), before);
}

#[test]
fn an_escape_is_refused_and_nothing_is_committed() {
    for mode in [
        "bash",
        "read-outside-denied",
        "read-outside-executed",
        "read-dotdot",
        "other-mcp",
    ] {
        let f = diverged();
        let before = store_files(&f.dir);
        let (code, out) = resolve(&f, mode, &[]);
        assert_eq!(
            (code, out["error"]["code"].as_str()),
            (5, Some("E_RESOLVER_ESCAPED")),
            "{mode}: {out}"
        );
        assert_eq!(store_files(&f.dir), before, "{mode}: the store changed");
    }
}

#[test]
fn no_conflicts_commit_mechanically_without_the_agent() {
    let f = diverged();
    // theirs = base with another sampling: nothing conflicts
    std::fs::write(f.dir.join("theirs.json"), manifest(BASE, 0.1).to_string()).unwrap();
    let (code, out) = resolve(&f, "resolve", &[]);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["resolver"], Value::Null);
    assert!(!log_path(&f).exists(), "the agent must not be invoked");
    let record: Value =
        serde_json::from_slice(&object(&f.dir, out["record"].as_str().unwrap())).unwrap();
    assert_eq!(record["resolver"], Value::Null);
    assert!(record.as_object().unwrap().contains_key("resolver"));
    assert_eq!(record["resolution"]["resolutions"], json!({}));
    // ... even when there is no claude at all
    let (code, out) = avcs(&f.dir, &resolve_args(&f, "/nonexistent/claude", &[]), &[]);
    assert_eq!(code, 0, "{out}");
}

#[test]
fn a_missing_claude_is_not_found() {
    let f = diverged();
    let before = store_files(&f.dir);
    let (code, out) = avcs(&f.dir, &resolve_args(&f, "/nonexistent/claude", &[]), &[]);
    assert_eq!(
        (code, out["error"]["code"].as_str()),
        (4, Some("E_RESOLVER_NOT_FOUND"))
    );
    // nothing named claude on PATH
    let empty = tempfile::tempdir().unwrap();
    let args: Vec<&str> = resolve_args(&f, "", &[])
        .into_iter()
        .filter(|a| !a.is_empty() && *a != "--claude")
        .collect();
    let (code, out) = avcs(&f.dir, &args, &[("PATH", empty.path().to_str().unwrap())]);
    assert_eq!(
        (code, out["error"]["code"].as_str()),
        (4, Some("E_RESOLVER_NOT_FOUND")),
        "{out}"
    );
    assert_eq!(store_files(&f.dir), before);
}

#[test]
fn dry_run_writes_the_workspace_and_prints_the_exact_command() {
    let f = diverged();
    let before = store_files(&f.dir);
    let (code, out) = resolve(&f, "resolve", &["--dry-run", "--max-turns", "7"]);
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["dry_run"], true);
    assert!(!log_path(&f).exists(), "--dry-run must not run the agent");
    assert_eq!(store_files(&f.dir), before);
    let argv: Vec<String> = serde_json::from_value(out["command"].clone()).unwrap();
    assert_eq!(argv[0], fake_claude().to_str().unwrap());
    let mcp = out["mcp_config"].as_str().unwrap();
    let prompt = include_str!("../src/resolve_prompt.md");
    let mut want = vec![argv[0].clone()];
    want.extend(spec_flags(mcp, prompt));
    want.extend(["--max-turns", "7"].map(String::from));
    assert_eq!(argv, want);

    // the workspace holds exactly the spec's files; the MCP config is outside it
    let ws = PathBuf::from(out["workspace"].as_str().unwrap());
    assert_eq!(out["cwd"], out["workspace"]);
    let mut files: Vec<String> = std::fs::read_dir(&ws)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    files.sort();
    assert_eq!(
        files,
        [
            "BRANCHES.md",
            "base.json",
            "ours.json",
            "prepare.json",
            "theirs.json"
        ]
    );
    assert!(!Path::new(mcp).starts_with(&ws));
    let prep: Value =
        serde_json::from_slice(&std::fs::read(ws.join("prepare.json")).unwrap()).unwrap();
    assert_eq!(prep["merge_id"], out["merge_id"]);
    let cfg: Value = serde_json::from_slice(&std::fs::read(mcp).unwrap()).unwrap();
    let srv = &cfg["mcpServers"]["agentvcs"];
    let args: Vec<String> = serde_json::from_value(srv["args"].clone()).unwrap();
    assert_eq!(args[..2], ["mcp", "--merge-session"]);
    assert_eq!(args[2], out["session"].as_str().unwrap());
    assert_eq!(cfg["mcpServers"].as_object().unwrap().len(), 1);

    // without runs there is no BRANCHES.md
    let (code, out) = avcs(
        &f.dir,
        &[
            "merge",
            "resolve",
            "--base",
            &f.base,
            "--ours",
            &f.ours,
            "--theirs",
            "theirs.json",
            "--dry-run",
        ],
        &[],
    );
    assert_eq!(code, 0, "{out}");
    let ws = PathBuf::from(out["workspace"].as_str().unwrap());
    assert!(!ws.join("BRANCHES.md").exists());
    assert!(ws.join("prepare.json").is_file());
}

/// The session server alone: only `prepare` and `commit`; `commit` stages and
/// never writes the store.
#[test]
fn merge_session_server_exposes_only_prepare_and_commit() {
    let f = diverged();
    let (code, out) = resolve(&f, "resolve", &["--dry-run"]);
    assert_eq!(code, 0, "{out}");
    let session = PathBuf::from(out["session"].as_str().unwrap());
    let before = store_files(&f.dir);
    let mut child = Command::new(BIN)
        .args(["mcp", "--merge-session", session.to_str().unwrap()])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    let mut rd = std::io::BufReader::new(child.stdout.take().unwrap());
    let mut id = 0;
    let mut call = |method: &str, params: Value| -> Value {
        use std::io::BufRead;
        id += 1;
        writeln!(
            stdin,
            "{}",
            json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params})
        )
        .unwrap();
        stdin.flush().unwrap();
        let mut line = String::new();
        rd.read_line(&mut line).unwrap();
        serde_json::from_str(&line).unwrap()
    };
    call("initialize", json!({"protocolVersion": "2025-06-18"}));
    let tools = call("tools/list", json!({}));
    let names: Vec<&str> = tools["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    assert_eq!(names, ["prepare", "commit"]);
    let prep = call("tools/call", json!({"name": "prepare", "arguments": {}}));
    let p = &prep["result"]["structuredContent"];
    let on_disk: Value = serde_json::from_slice(
        &std::fs::read(PathBuf::from(out["workspace"].as_str().unwrap()).join("prepare.json"))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(p, &on_disk);
    let unknown = call(
        "tools/call",
        json!({"name": "merge_commit", "arguments": {}}),
    );
    assert!(unknown.get("error").is_some(), "{unknown}");
    let bad = call(
        "tools/call",
        json!({"name": "commit", "arguments": {"resolution": {"merge_id": p["merge_id"]}}}),
    );
    assert_eq!(bad["result"]["isError"], true);
    assert!(!session.join("staged.json").exists());
    let res = json!({
        "protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": p["merge_id"],
        "resolutions": {"extract.prompt": {"take": "theirs"}},
        "rationale": "r", "author": {"type": "human", "id": "someone"}
    });
    let good = call(
        "tools/call",
        json!({"name": "commit", "arguments": {"resolution": res}}),
    );
    assert_eq!(good["result"]["isError"], false, "{good}");
    assert_eq!(good["result"]["structuredContent"]["staged"], true);
    let staged: Value =
        serde_json::from_slice(&std::fs::read(session.join("staged.json")).unwrap()).unwrap();
    assert_eq!(
        staged["author"],
        json!({"type": "agent", "id": "claude-code"})
    );
    assert_eq!(staged["resolutions"], res["resolutions"]);
    drop(stdin);
    child.wait().unwrap();
    assert_eq!(
        store_files(&f.dir),
        before,
        "commit must not write the store"
    );
}
