//! Command implementations. Each returns `(exit code, JSON)`; errors carry a code.

use crate::Invocation;
use agentvcs_core::hash::{b3_bytes, hash_value, is_hash};
use agentvcs_core::json::{canonical, parse_bytes, MAX_SAFE_INTEGER};
use agentvcs_core::ledger::{
    as_index, gate_passes, patch_body, patch_id, run_start_body, RunState,
};
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_core::schema::{author_ok, gate_result_ok};
use agentvcs_core::store::{check_run_id, Store};
use agentvcs_core::{Error, Result, PROTOCOL};
use agentvcs_query::bisect::{self, BadCond};
use serde_json::{json, Map, Number, Value};
use std::path::{Path, PathBuf};
use std::process::Command;

pub struct Ctx {
    pub cwd: PathBuf,
    pub stdin: Option<String>,
}

impl Ctx {
    fn path(&self, p: &str) -> PathBuf {
        let p = Path::new(p);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            self.cwd.join(p)
        }
    }

    fn store(&self) -> Result<Store> {
        Store::open(&self.cwd)
    }
}

type Out = Result<(i32, Value)>;

fn okv(v: Value) -> Out {
    Ok((0, v))
}

pub fn dispatch(inv: &Invocation, ctx: &Ctx) -> Out {
    match inv.cmd.tool {
        "init" => init(ctx),
        "hash" => hash(inv, ctx),
        "snapshot" => snapshot(inv, ctx),
        "run_start" => run_start(inv, ctx),
        "run_end" => run_end(inv, ctx),
        "step_record" => step_record(inv, ctx),
        "diff" => diff(inv, ctx),
        "patch_propose" => patch_propose(inv, ctx),
        "gate_run" => gate_run(inv, ctx),
        "patch_apply" => patch_apply(inv, ctx),
        "patch_rollback" => patch_rollback(inv, ctx),
        "resume" => resume(inv, ctx),
        "log" => log(inv, ctx),
        "blame" => blame(inv, ctx),
        "bisect" => bisect_cmd(inv, ctx),
        "freeze" => freeze(inv, ctx),
        "export_audit" => export_audit(inv, ctx),
        "verify" => verify(inv, ctx),
        "merge_prepare" => merge_prepare(inv, ctx),
        "merge_commit" => merge_commit(inv, ctx),
        other => Err(Error::new("E_USAGE", format!("unknown command {other}"))),
    }
}

// ---------------------------------------------------------------- input loading

fn read_file(ctx: &Ctx, p: &str) -> Result<Vec<u8>> {
    std::fs::read(ctx.path(p))
        .map_err(|e| Error::new("E_NOT_FOUND", format!("cannot read {p}: {e}")))
}

fn yaml_to_json(y: serde_yaml::Value) -> Result<Value> {
    use serde_yaml::Value as Y;
    Ok(match y {
        Y::Null => Value::Null,
        Y::Bool(b) => Value::Bool(b),
        Y::Number(n) => {
            if let Some(i) = n.as_i64() {
                if i.abs() > MAX_SAFE_INTEGER {
                    return Err(Error::new("E_CANONICAL", "integer beyond 2^53-1"));
                }
                Value::Number(i.into())
            } else if n.is_u64() {
                return Err(Error::new("E_CANONICAL", "integer beyond 2^53-1"));
            } else {
                let f = n.as_f64().unwrap_or(f64::NAN);
                Value::Number(
                    Number::from_f64(f)
                        .ok_or_else(|| Error::new("E_CANONICAL", "non-finite number"))?,
                )
            }
        }
        Y::String(s) => Value::String(s),
        Y::Sequence(a) => Value::Array(a.into_iter().map(yaml_to_json).collect::<Result<_>>()?),
        Y::Mapping(m) => {
            let mut out = Map::new();
            for (k, v) in m {
                let Y::String(k) = k else {
                    return Err(Error::new("E_SCHEMA", "YAML mapping keys must be strings"));
                };
                out.insert(k, yaml_to_json(v)?);
            }
            Value::Object(out)
        }
        Y::Tagged(_) => return Err(Error::new("E_SCHEMA", "YAML tags are not supported")),
    })
}

/// A JSON or YAML document (by extension), strictly parsed.
fn load_doc(ctx: &Ctx, p: &str) -> Result<Value> {
    let bytes = read_file(ctx, p)?;
    let lower = p.to_ascii_lowercase();
    if lower.ends_with(".yaml") || lower.ends_with(".yml") {
        let y: serde_yaml::Value = serde_yaml::from_slice(&bytes)
            .map_err(|e| Error::new("E_SCHEMA", format!("{p}: invalid YAML: {e}")))?;
        yaml_to_json(y)
    } else {
        Ok(parse_bytes(&bytes)?)
    }
}

/// A manifest named by a store id or a file path.
fn load_manifest(ctx: &Ctx, store: Option<&Store>, what: &str) -> Result<Manifest> {
    if ctx.path(what).is_file() {
        return normalize(&load_doc(ctx, what)?);
    }
    if is_hash(what) {
        if let Some(s) = store {
            return s.get_manifest(what);
        }
        return ctx.store()?.get_manifest(what);
    }
    Err(Error::new(
        "E_NOT_FOUND",
        format!("{what:?} is neither a manifest file nor a manifest id"),
    ))
}

/// A manifest named by id or file, stored if it came from a file.
fn manifest_into_store(ctx: &Ctx, store: &Store, what: &str) -> Result<Manifest> {
    let m = load_manifest(ctx, Some(store), what)?;
    store.put_manifest(&m)?;
    Ok(m)
}

/// An audit bundle: a file path, or a run id in the store.
fn load_bundle(ctx: &Ctx, target: &str) -> Result<Value> {
    if ctx.path(target).is_file() {
        return Ok(parse_bytes(&read_file(ctx, target)?)?);
    }
    let store = ctx.store()?;
    check_run_id(target).map_err(|_| {
        Error::new(
            "E_NOT_FOUND",
            format!("{target:?} is neither a file nor a run"),
        )
    })?;
    if !store.run_exists(target)? {
        return Err(Error::new(
            "E_NOT_FOUND",
            format!("{target:?} is neither a bundle file nor a run in the store"),
        ));
    }
    store.bundle(target)
}

fn parse_author(s: Option<&str>) -> Result<Value> {
    let s = s.unwrap_or("human:cli");
    let (t, id) = s
        .split_once(':')
        .ok_or_else(|| Error::new("E_USAGE", "--author must be type:id"))?;
    let a = json!({"type": t, "id": id});
    if !author_ok(&a) {
        return Err(Error::new(
            "E_USAGE",
            "--author type must be human or agent",
        ));
    }
    Ok(a)
}

fn parse_evidence(s: Option<&str>) -> Result<Vec<u64>> {
    match s.map(str::trim) {
        None | Some("") => Ok(vec![]),
        Some(s) => s
            .split(',')
            .map(|x| {
                x.trim().parse::<u64>().map_err(|_| {
                    Error::new("E_USAGE", format!("--evidence: {x:?} is not a step index"))
                })
            })
            .collect(),
    }
}

fn gen_run_id(prefix: &str) -> String {
    let now = agentvcs_core::time::now();
    let salt =
        b3_bytes(format!("{now}{}{:?}", std::process::id(), std::time::Instant::now()).as_bytes());
    let compact: String = now
        .chars()
        .filter(|c| c.is_ascii_digit())
        .take(14)
        .collect();
    format!("{prefix}-{compact}-{}", &salt[3..11])
}

// ---------------------------------------------------------------- commands

fn init(ctx: &Ctx) -> Out {
    Store::init(&ctx.cwd)?;
    okv(json!({"ok": true, "store": agentvcs_core::store::STORE_DIR}))
}

fn hash(inv: &Invocation, ctx: &Ctx) -> Out {
    let bytes = read_file(ctx, &inv.pos[0])?;
    if !inv.has("canonical") {
        return okv(json!({"ok": true, "hash": b3_bytes(&bytes)}));
    }
    let c = canonical(&parse_bytes(&bytes)?)?;
    okv(json!({"ok": true, "hash": b3_bytes(c.as_bytes()), "canonical": c}))
}

fn snapshot(inv: &Invocation, ctx: &Ctx) -> Out {
    let m = normalize(&load_doc(ctx, &inv.pos[0])?)?;
    ctx.store()?.put_manifest(&m)?;
    okv(json!({"ok": true, "manifest_id": m.manifest_id, "dimensions": m.dimension_hashes()}))
}

fn start_run(
    store: &Store,
    run_id: &str,
    manifest_id: &str,
    parent: Option<Value>,
) -> Result<Value> {
    check_run_id(run_id)?;
    if store.run_exists(run_id)? {
        return Err(Error::new(
            "E_RUN_EXISTS",
            format!("run {run_id} already exists"),
        ));
    }
    let mut st = RunState::new(run_id);
    store.append(
        &mut st,
        "run_start",
        run_start_body(manifest_id, &agentvcs_core::time::now(), parent),
    )
}

fn run_start(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let m = manifest_into_store(ctx, &store, inv.flag("manifest").unwrap_or_default())?;
    let run_id = inv
        .flag("run-id")
        .map_or_else(|| gen_run_id("run"), str::to_owned);
    let e = start_run(&store, &run_id, &m.manifest_id, None)?;
    okv(
        json!({"ok": true, "run_id": run_id, "manifest_id": m.manifest_id, "entry_hash": e["entry_hash"]}),
    )
}

fn run_end(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let run = &inv.pos[0];
    let mut st = store.run_state(run)?;
    let status = inv.flag("status").unwrap_or("completed");
    let e = store.append(
        &mut st,
        "run_end",
        json!({"ended_at": agentvcs_core::time::now(), "status": status}),
    )?;
    okv(json!({"ok": true, "run_id": run, "entries": st.next_seq, "entry_hash": e["entry_hash"]}))
}

/// The library path of `step record` (also used by the SDK and the benchmark).
pub fn record_step(store: &Store, run: &str, body: Value) -> Result<Value> {
    let Value::Object(mut b) = body else {
        return Err(Error::new("E_SCHEMA", "a step body is a JSON object"));
    };
    let mut st = store.run_state(run)?;
    if st.ended {
        return Err(Error::new(
            "E_AFTER_RUN_END",
            format!("run {run} has ended"),
        ));
    }
    st.fill_step(&mut b)?;
    b.entry("checkpoint_ref").or_insert(Value::Null);
    let e = store.append(&mut st, "step", Value::Object(b))?;
    Ok(
        json!({"ok": true, "seq": e["seq"], "entry_hash": e["entry_hash"],
              "step_index": e["body"]["step_index"]}),
    )
}

fn step_record(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let text = ctx.stdin.as_deref().unwrap_or("");
    let body = parse_bytes(text.as_bytes())?;
    okv(record_step(&store, &inv.pos[0], body)?)
}

fn diff(inv: &Invocation, ctx: &Ctx) -> Out {
    let a = load_manifest(ctx, None, &inv.pos[0])?;
    let b = load_manifest(ctx, None, &inv.pos[1])?;
    let mut v = agentvcs_diff::diff(&a, &b).to_value();
    v["ok"] = true.into();
    okv(v)
}

fn patch_propose(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let run = &inv.pos[0];
    if !store.run_exists(run)? {
        return Err(Error::new("E_NOT_FOUND", format!("run {run} not found")));
    }
    let from = store.get_manifest(inv.flag("from").unwrap_or_default())?;
    let to = manifest_into_store(ctx, &store, inv.flag("to").unwrap_or_default())?;
    if from.manifest_id == to.manifest_id {
        return Err(Error::new(
            "E_PATCH_NOOP",
            "--from and --to are the same manifest",
        ));
    }
    let semantic_diff = Value::Array(agentvcs_diff::diff(&from, &to).changes);
    let mut rec = json!({
        "patch_id": null,
        "run_id": run,
        "from_manifest": from.manifest_id,
        "to_manifest": to.manifest_id,
        "semantic_diff": semantic_diff,
        "rationale": inv.flag("rationale").unwrap_or_default(),
        "evidence": parse_evidence(inv.flag("evidence"))?,
        "author": parse_author(inv.flag("author"))?,
        "rollback_of": null,
        "gate_result": null,
    });
    let pid = patch_id(&rec)?;
    rec["patch_id"] = pid.clone().into();
    if let Ok(existing) = store.get_patch(&pid) {
        // same proposal again: keep its gate result
        rec["gate_result"] = existing["gate_result"].clone();
    }
    store.put_patch(&rec)?;
    okv(json!({"ok": true, "patch_id": pid, "semantic_diff": rec["semantic_diff"]}))
}

/// Read a JSON stdout into a map of numeric metrics: either `{"metrics": {…}}`
/// or a flat object (non-numeric values ignored).
fn metrics_of(out: &Value) -> Option<Map<String, Value>> {
    let obj = match out.get("metrics") {
        Some(Value::Object(m)) => m,
        _ => out.as_object()?,
    };
    Some(
        obj.iter()
            .filter(|(_, v)| v.is_number())
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    )
}

fn shell(cmd: &str, cwd: &Path, env: &[(&str, String)]) -> Result<Vec<u8>> {
    let mut c = Command::new("sh");
    c.arg("-c").arg(cmd).current_dir(cwd);
    for (k, v) in env {
        c.env(k, v);
    }
    let o = c
        .stdin(std::process::Stdio::null())
        .output()
        .map_err(|e| Error::new("E_GATE_COMMAND", format!("cannot run {cmd:?}: {e}")))?;
    if !o.status.success() {
        return Err(Error::new(
            "E_GATE_COMMAND",
            format!(
                "{cmd:?} exited with {}: {}",
                o.status,
                String::from_utf8_lossy(&o.stderr)
                    .chars()
                    .take(300)
                    .collect::<String>()
            ),
        ));
    }
    Ok(o.stdout)
}

/// The file a stored manifest lives in (what a suite command reads).
fn manifest_file(store: &Store, id: &str) -> String {
    store
        .root()
        .join("manifests")
        .join(format!("{}.json", agentvcs_core::hash::hex_of(id)))
        .to_string_lossy()
        .into_owned()
}

/// Run a suite's command with `env` and turn its stdout into a gate result
/// (`gate_result.schema.json`). Shared by `gate run` and `merge commit --suite`.
fn run_suite(ctx: &Ctx, store: &Store, suite_path: &str, env: &[(&str, String)]) -> Result<Value> {
    let suite = load_doc(ctx, suite_path)?;
    let command = suite["command"]
        .as_str()
        .ok_or_else(|| Error::new("E_SCHEMA", "suite needs a `command` string"))?;
    let thresholds = suite
        .get("thresholds")
        .cloned()
        .ok_or_else(|| Error::new("E_SCHEMA", "suite needs `thresholds`"))?;
    let name = suite["name"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| {
            Path::new(suite_path)
                .file_stem()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default()
        });
    let stdout = shell(command, &ctx.cwd, env)?;
    let out = parse_bytes(&stdout).map_err(|e| {
        Error::new(
            "E_GATE_COMMAND",
            format!("suite command did not print JSON metrics: {e}"),
        )
    })?;
    let metrics = metrics_of(&out).ok_or_else(|| {
        Error::new(
            "E_GATE_COMMAND",
            "suite command did not print a JSON object",
        )
    })?;
    let evidence = store.put_blob(&stdout)?;
    let mut g = json!({
        "suite": name,
        "suite_hash": hash_value(&suite)?,
        "metrics": metrics,
        "thresholds": thresholds,
        "passed": false,
        "evidence": [evidence],
    });
    g["passed"] = gate_passes(&g).into();
    if !gate_result_ok(&g) {
        return Err(Error::new(
            "E_SCHEMA",
            "suite thresholds must be {metric: {op, value}}",
        ));
    }
    Ok(g)
}

fn gate_run(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let pid = &inv.pos[0];
    let mut rec = store.get_patch(pid)?;
    let to = rec["to_manifest"].as_str().unwrap_or_default().to_owned();
    let env = [
        ("AGENTVCS_PATCH", pid.clone()),
        (
            "AGENTVCS_RUN",
            rec["run_id"].as_str().unwrap_or_default().to_owned(),
        ),
        (
            "AGENTVCS_FROM_MANIFEST",
            rec["from_manifest"].as_str().unwrap_or_default().to_owned(),
        ),
        ("AGENTVCS_TO_MANIFEST", to.clone()),
        ("AGENTVCS_MANIFEST", to.clone()),
        ("AGENTVCS_MANIFEST_FILE", manifest_file(&store, &to)),
        (
            "AGENTVCS_STORE",
            store.root().to_string_lossy().into_owned(),
        ),
    ];
    let g = run_suite(ctx, &store, inv.flag("suite").unwrap_or_default(), &env)?;
    rec["gate_result"] = g.clone();
    store.put_patch(&rec)?;
    let code = if g["passed"] == true { 0 } else { 1 };
    Ok((code, json!({"ok": true, "patch_id": pid, "gate_result": g})))
}

fn check_at_step(inv: &Invocation, st: &RunState) -> Result<()> {
    if let Some(s) = inv.flag("at-step") {
        let n: u64 = s
            .parse()
            .map_err(|_| Error::new("E_USAGE", "--at-step must be a step index"))?;
        if n != st.next_step {
            return Err(Error::new(
                "E_PATCH_STEP",
                format!("--at-step {n} but the run's next step is {}", st.next_step),
            ));
        }
    }
    Ok(())
}

/// The library path of `patch apply`.
pub fn apply_patch(store: &Store, pid: &str, at_step: Option<u64>) -> Result<Value> {
    let rec = store.get_patch(pid)?;
    let g = &rec["gate_result"];
    if rec["rollback_of"].is_null() && !(g.is_object() && g["passed"] == true) {
        return Err(Error::new(
            "E_PATCH_UNGATED",
            format!("patch {pid} has no passed gate (run `agentvcs gate run`)"),
        ));
    }
    let run = rec["run_id"].as_str().unwrap_or_default();
    let mut st = store.run_state(run)?;
    if let Some(n) = at_step {
        if n != st.next_step {
            return Err(Error::new(
                "E_PATCH_STEP",
                format!("--at-step {n} but the run's next step is {}", st.next_step),
            ));
        }
    }
    let evidence: Vec<u64> = rec["evidence"]
        .as_array()
        .map(|a| a.iter().filter_map(as_index).collect())
        .unwrap_or_default();
    let body = patch_body(
        rec["from_manifest"].as_str().unwrap_or_default(),
        rec["to_manifest"].as_str().unwrap_or_default(),
        rec["semantic_diff"].clone(),
        rec["rationale"].as_str().unwrap_or_default(),
        evidence,
        rec["author"].clone(),
        st.next_step,
        rec["rollback_of"].as_str(),
        (!g.is_null()).then(|| g.clone()),
    )?;
    if body["patch_id"] != rec["patch_id"] {
        return Err(Error::new(
            "E_PATCH_ID",
            "stored patch record does not recompute",
        ));
    }
    let e = store.append(&mut st, "patch", body)?;
    Ok(
        json!({"ok": true, "patch_id": pid, "run_id": run, "seq": e["seq"],
              "entry_hash": e["entry_hash"], "active_manifest": st.active}),
    )
}

fn patch_apply(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let at = match inv.flag("at-step") {
        None => None,
        Some(s) => Some(
            s.parse::<u64>()
                .map_err(|_| Error::new("E_USAGE", "--at-step must be a step index"))?,
        ),
    };
    okv(apply_patch(&store, &inv.pos[0], at)?)
}

fn patch_rollback(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let pid = &inv.pos[0];
    let orig = store.get_patch(pid)?;
    let run = orig["run_id"].as_str().unwrap_or_default().to_owned();
    let applied = store
        .read_ledger(&run)?
        .iter()
        .any(|e| e["kind"] == "patch" && e["body"]["patch_id"] == orig["patch_id"]);
    if !applied {
        return Err(Error::new(
            "E_ROLLBACK_UNKNOWN",
            format!("patch {pid} was never applied to run {run}"),
        ));
    }
    let st = store.run_state(&run)?;
    check_at_step(inv, &st)?;
    if st.active.as_deref() != orig["to_manifest"].as_str() {
        return Err(Error::new(
            "E_PATCH_FROM",
            format!("run {run} is not running the manifest patch {pid} installed"),
        ));
    }
    let from = store.get_manifest(orig["to_manifest"].as_str().unwrap_or_default())?;
    let to = store.get_manifest(orig["from_manifest"].as_str().unwrap_or_default())?;
    let mut rec = json!({
        "patch_id": null,
        "run_id": run,
        "from_manifest": from.manifest_id,
        "to_manifest": to.manifest_id,
        "semantic_diff": agentvcs_diff::diff(&from, &to).changes,
        "rationale": inv.flag("rationale").map_or_else(|| format!("rollback of {pid}"), str::to_owned),
        "evidence": parse_evidence(inv.flag("evidence"))?,
        "author": parse_author(inv.flag("author"))?,
        "rollback_of": pid,
        "gate_result": null,
    });
    rec["patch_id"] = patch_id(&rec)?.into();
    store.put_patch(&rec)?;
    let mut out = apply_patch(&store, rec["patch_id"].as_str().unwrap_or_default(), None)?;
    out["rollback_of"] = pid.clone().into();
    okv(out)
}

fn resume(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let parent = &inv.pos[0];
    let from_step: u64 = inv
        .flag("from-step")
        .unwrap_or_default()
        .parse()
        .map_err(|_| Error::new("E_USAGE", "--from-step must be a step index"))?;
    let ledger = store.read_ledger(parent)?;
    let first = match ledger.first() {
        Some(e) if e["kind"] == "run_start" => match &e["body"]["parent"] {
            Value::Null => 0,
            p => as_index(&p["from_step"]).unwrap_or(0),
        },
        _ => {
            return Err(Error::new(
                "E_FIRST_NOT_RUN_START",
                "parent run has no run_start",
            ))
        }
    };
    let mut next = first;
    let mut checkpoint_ref = Value::Null;
    for e in &ledger {
        if e["kind"] == "step" {
            let si = as_index(&e["body"]["step_index"]).unwrap_or(0);
            next = si + 1;
            if si + 1 == from_step {
                checkpoint_ref = e["body"]["checkpoint_ref"].clone();
            }
        }
    }
    if from_step < first || from_step > next {
        return Err(Error::new(
            "E_STEP_INDEX",
            format!("--from-step must be within {first}..={next} for run {parent}"),
        ));
    }
    let m = manifest_into_store(ctx, &store, inv.flag("manifest").unwrap_or_default())?;
    let run_id = inv.flag("run-id").map_or_else(
        || gen_run_id(&format!("{parent}-r{from_step}")),
        str::to_owned,
    );
    let p = json!({"run_id": parent, "from_step": from_step, "checkpoint_ref": checkpoint_ref});
    start_run(&store, &run_id, &m.manifest_id, Some(p.clone()))?;
    okv(
        json!({"ok": true, "run_id": run_id, "parent": p, "checkpoint_ref": checkpoint_ref,
               "manifest_id": m.manifest_id}),
    )
}

fn log(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let entries = store.read_ledger(&inv.pos[0])?;
    okv(json!({"ok": true, "run_id": inv.pos[0], "entries": entries}))
}

fn blame(inv: &Invocation, ctx: &Ctx) -> Out {
    let b = load_bundle(ctx, &inv.pos[0])?;
    okv(agentvcs_query::blame(&b, inv.flag("metric").unwrap_or_default())?.to_value())
}

fn verify(inv: &Invocation, ctx: &Ctx) -> Out {
    let b = load_bundle(ctx, &inv.pos[0])?;
    let r = agentvcs_query::verify(&b);
    Ok((if r.valid { 0 } else { 1 }, r.to_value()))
}

fn bisect_cmd(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let run = &inv.pos[0];
    let metric = inv.flag("metric").unwrap_or_default();
    let cond = BadCond::parse(inv.flag("bad").unwrap_or_default())?;
    let cmd = inv.flag("exec").unwrap_or_default();
    let bundle = store.bundle(run)?;
    let r = agentvcs_query::verify(&bundle);
    if !r.valid {
        return Err(Error::new(
            "E_INVALID_LEDGER",
            "bisect refuses a ledger that does not verify",
        ));
    }
    let plan = bisect::plan(run, bundle["ledger"].as_array().expect("verified"))?;
    let out = bisect::search(&plan, &cond, |mid| {
        let file = store
            .root()
            .join("manifests")
            .join(format!("{}.json", agentvcs_core::hash::hex_of(mid)));
        let env = [
            ("AGENTVCS_RUN", run.clone()),
            ("AGENTVCS_MANIFEST", mid.to_owned()),
            (
                "AGENTVCS_MANIFEST_FILE",
                file.to_string_lossy().into_owned(),
            ),
            ("AGENTVCS_FROM_STEP", plan.from_step.to_string()),
            (
                "AGENTVCS_CHECKPOINT_REF",
                plan.checkpoint_ref.clone().unwrap_or_default(),
            ),
            ("AGENTVCS_METRIC", metric.to_owned()),
            (
                "AGENTVCS_STORE",
                store.root().to_string_lossy().into_owned(),
            ),
        ];
        let stdout = shell(cmd, &ctx.cwd, &env)?;
        let v = parse_bytes(&stdout)
            .map_err(|e| Error::new("E_GATE_COMMAND", format!("--exec did not print JSON: {e}")))?;
        v.as_f64()
            .or_else(|| metrics_of(&v).and_then(|m| m.get(metric).and_then(Value::as_f64)))
            .ok_or_else(|| {
                Error::new(
                    "E_GATE_COMMAND",
                    format!("--exec printed no number for {metric}"),
                )
            })
    })?;
    let mut v = out.to_value();
    v["from_step"] = plan.from_step.into();
    v["checkpoint_ref"] = plan.checkpoint_ref.clone().into();
    okv(v)
}

fn freeze(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let mid = &inv.pos[0];
    store.get_manifest(mid)?;
    let gates = store.passed_gates_for(mid)?;
    if gates.is_empty() {
        return Err(Error::new(
            "E_NOT_GATED",
            format!("no passed gate names manifest {mid}"),
        ));
    }
    store.freeze(
        mid,
        &json!({"protocol": PROTOCOL, "manifest_id": mid, "gates": gates, "frozen_at": agentvcs_core::time::now()}),
    )?;
    okv(json!({"ok": true, "manifest_id": mid, "frozen": true, "gates": gates}))
}

fn export_audit(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let run = &inv.pos[0];
    let bundle = store.bundle(run)?;
    let entries = bundle["ledger"].as_array().map_or(0, Vec::len);
    match inv.flag("output") {
        None => okv(json!({"ok": true, "run_id": run, "entries": entries, "bundle": bundle})),
        Some(p) => {
            let path = ctx.path(p);
            if path.exists() && !inv.yes {
                return Err(Error::new(
                    "E_EXISTS",
                    format!("{p} exists; pass --yes to overwrite"),
                ));
            }
            // serde_json keeps floats as floats (1e20 stays 1e20), so the file
            // re-parses strictly; see ADR-0006 §1
            let mut text = serde_json::to_string_pretty(&bundle)
                .map_err(|e| Error::new("E_IO", e.to_string()))?;
            text.push('\n');
            std::fs::write(&path, text)?;
            okv(json!({"ok": true, "run_id": run, "entries": entries, "path": p}))
        }
    }
}

// ---------------------------------------------------------------- merge (v0.2 draft)

fn merge_sides(inv: &Invocation, ctx: &Ctx, store: Option<&Store>) -> Result<[Manifest; 3]> {
    let get = |f: &str| load_manifest(ctx, store, inv.flag(f).unwrap_or_default());
    Ok([get("base")?, get("ours")?, get("theirs")?])
}

fn merge_prepare(inv: &Invocation, ctx: &Ctx) -> Out {
    let [b, o, t] = merge_sides(inv, ctx, None)?;
    let run = |f: &str| inv.flag(f).map(|r| load_bundle(ctx, r)).transpose();
    let (ours_run, theirs_run) = (run("ours-run")?, run("theirs-run")?);
    let p = agentvcs_merge::prepare(
        &b,
        &o,
        &t,
        ours_run.as_ref(),
        theirs_run.as_ref(),
        inv.values("metric"),
    )?;
    okv(p.to_value())
}

fn merge_commit(inv: &Invocation, ctx: &Ctx) -> Out {
    let store = ctx.store()?;
    let [b, o, t] = merge_sides(inv, ctx, Some(&store))?;
    let resolution = load_doc(ctx, inv.flag("resolution").unwrap_or_default())?;
    let mut c = agentvcs_merge::commit(&b, &o, &t, &resolution)?;
    // the merged manifest first: when its id is already one of the sides, the
    // first annotation stored wins (ADR-0005) and this one carries parent_ids
    for m in [&c.merged, &b, &o, &t] {
        store.put_manifest(m)?;
    }
    let merged = c.merged.manifest_id.clone();
    let gate = match inv.flag("suite") {
        None => Value::Null,
        Some(suite) => {
            let env = [
                (
                    "AGENTVCS_MERGE_ID",
                    c.record["merge_id"].as_str().unwrap_or_default().to_owned(),
                ),
                ("AGENTVCS_FROM_MANIFEST", o.manifest_id.clone()),
                ("AGENTVCS_TO_MANIFEST", merged.clone()),
                ("AGENTVCS_MANIFEST", merged.clone()),
                ("AGENTVCS_MANIFEST_FILE", manifest_file(&store, &merged)),
                (
                    "AGENTVCS_STORE",
                    store.root().to_string_lossy().into_owned(),
                ),
            ];
            run_suite(ctx, &store, suite, &env)?
        }
    };
    c.record["gate"] = gate.clone();
    // a rejected merge is history too: the record is stored whatever the gate says
    let record = store.put_json(&c.record)?;
    let code = if gate["passed"] == false { 1 } else { 0 };
    Ok((
        code,
        json!({"ok": true, "merge_id": c.record["merge_id"], "merged": merged,
               "record": record, "gate": gate}),
    ))
}
