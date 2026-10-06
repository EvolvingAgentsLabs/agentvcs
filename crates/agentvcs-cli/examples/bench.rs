//! Gate F1 item 4 benchmarks. Run in release mode:
//!
//!     cargo run --release -p agentvcs-cli --example bench -- <path to agentvcs binary>
//!
//! 1. `step record` through the library (store opened once, as an SDK holds it);
//! 2. `step record` through the CLI (one process per step), next to the cost of
//!    spawning `/usr/bin/true`, so process creation is visible on its own;
//! 3. `verify` of a 100k-step ledger: in-process (parse + verify) and through the CLI.
//!
//! Progress is printed as each phase finishes.

use agentvcs_cli::commands::record_step;
use agentvcs_core::json::parse;
use agentvcs_core::ledger::LedgerBuilder;
use agentvcs_core::manifest::normalize;
use agentvcs_core::store::Store;
use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn manifest() -> Value {
    json!({"protocol": "agentvcs/0.1", "type": "harness_manifest",
           "dimensions": {"p": {"kind": "prompt", "content": {"template": "Find every {clause}."}},
                          "m": {"kind": "model", "content": {"provider": "llama.cpp", "id": "gemma-4-12b"}}}})
}

fn body(i: usize) -> Value {
    json!({"agent_id": "extractor",
           "inputs": [agentvcs_core::hash::b3_bytes(format!("in{i}").as_bytes())],
           "outputs": [agentvcs_core::hash::b3_bytes(format!("out{i}").as_bytes())],
           "started_at": "2026-10-06T12:00:00.000Z", "ended_at": "2026-10-06T12:00:01.000Z",
           "tokens": {"in": 812, "out": 133}, "latency_ms": 1840,
           "metrics": {"f1": (i % 10) as f64 / 10.0}, "checkpoint_ref": null})
}

fn pct(v: &mut [Duration], p: f64) -> f64 {
    v.sort();
    let i = ((v.len() as f64 - 1.0) * p).round() as usize;
    v[i].as_secs_f64() * 1e3
}

fn report(name: &str, mut v: Vec<Duration>) {
    let n = v.len();
    let (p50, p99, max) = (pct(&mut v, 0.5), pct(&mut v, 0.99), pct(&mut v, 1.0));
    println!("{name}: n={n} p50={p50:.3} ms p99={p99:.3} ms max={max:.3} ms");
}

fn spawn_with_stdin(bin: &str, args: &[&str], stdin: &str) -> Duration {
    let t = Instant::now();
    let mut c = Command::new(bin)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn");
    c.stdin.take().unwrap().write_all(stdin.as_bytes()).unwrap();
    let s = c.wait().unwrap();
    let d = t.elapsed();
    assert!(s.success(), "{bin} {args:?} failed");
    d
}

fn main() {
    let bin = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "target/release/agentvcs".into());
    let n_lib: usize = std::env::var("BENCH_LIB_STEPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10_000);
    let n_cli: usize = std::env::var("BENCH_CLI_STEPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(500);
    let n_verify: usize = std::env::var("BENCH_VERIFY_STEPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(100_000);
    println!(
        "target: {} {}",
        std::env::consts::OS,
        std::env::consts::ARCH
    );

    // 1. library
    let d = tempfile::tempdir().unwrap();
    let store = Store::init(d.path()).unwrap();
    let m = normalize(&manifest()).unwrap();
    store.put_manifest(&m).unwrap();
    let (code, out) = agentvcs_cli::run(
        &[
            "run".into(),
            "start".into(),
            "--manifest".into(),
            m.manifest_id.clone(),
            "--run-id".into(),
            "lib".into(),
        ],
        None,
        d.path().to_path_buf(),
    );
    assert_eq!(code, 0, "{out}");
    let mut lib = Vec::with_capacity(n_lib);
    for i in 0..n_lib {
        let b = body(i);
        let t = Instant::now();
        record_step(&store, "lib", b).unwrap();
        lib.push(t.elapsed());
    }
    report("step record (library, store held open)", lib);

    // 2. CLI
    let (code, out) = agentvcs_cli::run(
        &[
            "run".into(),
            "start".into(),
            "--manifest".into(),
            m.manifest_id.clone(),
            "--run-id".into(),
            "cli".into(),
        ],
        None,
        d.path().to_path_buf(),
    );
    assert_eq!(code, 0, "{out}");
    let dir = d.path().to_str().unwrap();
    let mut spawn_only = Vec::with_capacity(n_cli);
    for _ in 0..n_cli {
        spawn_only.push(spawn_with_stdin("/usr/bin/true", &[], ""));
    }
    report("process spawn alone (/usr/bin/true)", spawn_only);
    let mut cli = Vec::with_capacity(n_cli);
    for i in 0..n_cli {
        let b = body(i).to_string();
        cli.push(spawn_with_stdin(
            &bin,
            &["-C", dir, "step", "record", "cli", "--json"],
            &b,
        ));
    }
    report("step record (CLI process per step)", cli);

    // 3. verify of a large ledger
    let mut lb = LedgerBuilder::new("big", vec![m.value.clone()]);
    lb.run_start(&m.manifest_id, None).unwrap();
    for i in 0..n_verify {
        lb.step(body(i)).unwrap();
    }
    lb.run_end("completed").unwrap();
    let text = serde_json::to_string(&lb.bundle()).unwrap();
    println!(
        "bundle: {} entries, {:.1} MB",
        n_verify + 2,
        text.len() as f64 / 1e6
    );
    let t = Instant::now();
    let b = parse(&text).unwrap();
    let r = agentvcs_query::verify(&b);
    let lib_verify = t.elapsed();
    assert!(r.valid);
    println!(
        "verify {n_verify} steps (library, parse + verify): {:.3} s",
        lib_verify.as_secs_f64()
    );
    let f = d.path().join("big.json");
    std::fs::write(&f, &text).unwrap();
    let t = Instant::now();
    let o = Command::new(&bin)
        .args(["verify", f.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    let cli_verify = t.elapsed();
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stdout)
    );
    println!(
        "verify {n_verify} steps (CLI, bundle file): {:.3} s",
        cli_verify.as_secs_f64()
    );
}
