//! `merge resolve` (spec/MERGE.md §6): Claude Code resolves a merge's conflicts;
//! the runtime keeps every guarantee on its side.
//!
//! The agent works in a fresh workspace holding only the prepared merge, with
//! `Read` and two MCP tools served by `agentvcs mcp --merge-session <dir>`:
//! `prepare` and `commit`, bound to this merge. `commit` validates and *stages* a
//! resolution; nothing reaches the store while the agent runs. When the session
//! ends, the runtime audits the transcript (any tool outside the three allowed,
//! or any `Read` outside the workspace, denied or not, refuses the merge) and only
//! then commits the staged resolution exactly as `merge commit` does, recording
//! the resolver. The isolation recipe is the one experiment M0 validated against
//! the real Claude Code, where an allow-list alone let a `Bash` call through.

use crate::commands::{commit_merge, load_bundle, merge_sides, okv, Ctx, Out};
use crate::Invocation;
use agentvcs_core::hash::b3_bytes;
use agentvcs_core::json::parse_bytes;
use agentvcs_core::manifest::{normalize, Manifest};
use agentvcs_core::{Error, Result, PROTOCOL};
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

/// The resolver's system prompt (appended to Claude Code's own). Fixed: it says
/// what the workspace holds, the two tools and the resolution contract, and
/// nothing about any particular merge.
pub const PROMPT: &str = include_str!("resolve_prompt.md");
/// The task, on the agent's stdin.
pub const TASK: &str =
    "Resolve the merge in your working directory: read prepare.json, decide every \
conflict, and call the `commit` tool with your resolution until it returns \"ok\": true.";
/// The MCP server name in the agent's config: its tools are `mcp__agentvcs__*`.
pub const SERVER: &str = "agentvcs";
pub const PREPARE_TOOL: &str = "mcp__agentvcs__prepare";
pub const COMMIT_TOOL: &str = "mcp__agentvcs__commit";
/// The only tools the agent may call (spec/MERGE.md §6 step 5).
pub const ALLOWED_TOOLS: [&str; 3] = ["Read", PREPARE_TOOL, COMMIT_TOOL];
/// The author every staged resolution carries (spec/MERGE.md §6 step 6).
pub fn author() -> Value {
    json!({"type": "agent", "id": "claude-code"})
}

const WORKSPACE_FILES: [&str; 3] = ["base", "ours", "theirs"];

fn err(code: &'static str, msg: impl Into<String>) -> Error {
    Error::new(code, msg)
}

/// The claude command line of spec/MERGE.md §6 step 4, flag for flag.
pub fn command(
    claude: &str,
    mcp_config: &str,
    model: Option<&str>,
    budget_usd: Option<&str>,
    max_turns: Option<&str>,
) -> Vec<String> {
    let mut v: Vec<String> = [
        claude,
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
        &ALLOWED_TOOLS.join(","),
        "--mcp-config",
        mcp_config,
        "--append-system-prompt",
        PROMPT,
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    for (flag, val) in [
        ("--model", model),
        ("--max-budget-usd", budget_usd),
        ("--max-turns", max_turns),
    ] {
        if let Some(x) = val {
            v.push(flag.into());
            v.push(x.into());
        }
    }
    v
}

/// `--claude <path>`, or `claude` on PATH. A path must be an executable file.
fn find_claude(given: Option<&str>, cwd: &Path) -> Option<PathBuf> {
    fn executable(p: &Path) -> bool {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            p.metadata()
                .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        }
        #[cfg(not(unix))]
        {
            p.is_file()
        }
    }
    match given {
        Some(g) if g.contains('/') || g.contains(std::path::MAIN_SEPARATOR) => {
            let p = Path::new(g);
            let p = if p.is_absolute() {
                p.to_path_buf()
            } else {
                cwd.join(p)
            };
            executable(&p).then_some(p)
        }
        g => {
            let name = g.unwrap_or("claude");
            std::env::split_paths(&std::env::var_os("PATH")?)
                .map(|d| d.join(name))
                .find(|p| executable(p))
        }
    }
}

static SELF_COMMAND: std::sync::OnceLock<Vec<String>> = std::sync::OnceLock::new();

/// How to start this agentvcs again, for an embedder whose executable is not
/// agentvcs (the Python SDK sets `<python> -m agentvcs`). First call wins.
pub fn set_self_command(argv: Vec<String>) {
    let _ = SELF_COMMAND.set(argv);
}

/// The command that starts this agentvcs (for the MCP config): `AGENTVCS_BIN` if
/// set; what the embedder set; else the running executable.
fn self_command() -> Vec<String> {
    if let Some(b) = std::env::var_os("AGENTVCS_BIN") {
        return vec![b.to_string_lossy().into_owned()];
    }
    if let Some(v) = SELF_COMMAND.get() {
        return v.clone();
    }
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("agentvcs"));
    vec![exe.to_string_lossy().into_owned()]
}

/// A fresh directory under the system temp dir, canonical (on macOS `/var` is
/// `/private/var`: the audit compares canonical paths).
fn fresh_root(merge_id: &str) -> Result<PathBuf> {
    let tmp = std::env::temp_dir();
    for i in 0..100u32 {
        let salt = b3_bytes(
            format!(
                "{merge_id}{}{:?}{i}",
                std::process::id(),
                std::time::SystemTime::now()
            )
            .as_bytes(),
        );
        let p = tmp.join(format!(
            "agentvcs-merge-{}-{}",
            &merge_id[3..15.min(merge_id.len())],
            &salt[3..11]
        ));
        match std::fs::create_dir(&p) {
            Ok(()) => return Ok(p.canonicalize()?),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.into()),
        }
    }
    Err(err("E_IO", "cannot create a temporary merge directory"))
}

fn pretty(v: &Value) -> Result<String> {
    let mut s = serde_json::to_string_pretty(v).map_err(|e| err("E_IO", e.to_string()))?;
    s.push('\n');
    Ok(s)
}

fn write_atomic(p: &Path, text: &str) -> Result<()> {
    let tmp = p.with_extension("tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, p)?;
    Ok(())
}

/// `BRANCHES.md`: each side's patch rationales, in ledger order.
fn branches_md(runs: &[(&str, Option<&Value>); 2]) -> String {
    let mut s = String::from(
        "# Branches\n\nWhat each side's recorded run changed, in the order its patches were applied \
         (the author's rationale for each patch). The same patches, restricted to each conflict and \
         with their gate results and metric deltas, are the `evidence` in prepare.json.\n",
    );
    for (side, bundle) in runs {
        s.push_str(&format!("\n## {side}"));
        let Some(b) = bundle else {
            s.push_str("\n\nNo run was given for this side.\n");
            continue;
        };
        s.push_str(&format!(
            " (run `{}`)\n\n",
            b["run_id"].as_str().unwrap_or("?")
        ));
        let patches: Vec<&Value> = b["ledger"]
            .as_array()
            .map(|l| {
                l.iter()
                    .filter(|e| e["kind"] == "patch")
                    .map(|e| &e["body"])
                    .collect()
            })
            .unwrap_or_default();
        if patches.is_empty() {
            s.push_str("No patches.\n");
        }
        for (i, p) in patches.iter().enumerate() {
            let a = &p["author"];
            let dims: Vec<&str> = p["semantic_diff"]
                .as_array()
                .map(|d| d.iter().filter_map(|c| c["dimension"].as_str()).collect())
                .unwrap_or_default();
            s.push_str(&format!(
                "{}. step {} · {}:{} · changes {} · patch {}{}\n   {}\n",
                i + 1,
                p["applied_at_step"],
                a["type"].as_str().unwrap_or("?"),
                a["id"].as_str().unwrap_or("?"),
                dims.join(", "),
                p["patch_id"].as_str().unwrap_or("?"),
                if p["rollback_of"].is_string() {
                    " (rollback)"
                } else {
                    ""
                },
                p["rationale"].as_str().unwrap_or("").replace('\n', "\n   "),
            ));
        }
    }
    s
}

fn positive_number(inv: &Invocation, flag: &str, integer: bool) -> Result<Option<String>> {
    let Some(v) = inv.flag(flag) else {
        return Ok(None);
    };
    let ok = if integer {
        v.parse::<u32>().is_ok_and(|n| n > 0)
    } else {
        v.parse::<f64>().is_ok_and(|x| x.is_finite() && x > 0.0)
    };
    if !ok {
        return Err(err(
            "E_USAGE",
            format!(
                "--{flag} must be a positive {}",
                if integer { "integer" } else { "number" }
            ),
        ));
    }
    Ok(Some(v.to_owned()))
}

// ------------------------------------------------------------------ the command

pub fn merge_resolve(inv: &Invocation, ctx: &Ctx) -> Out {
    let budget = positive_number(inv, "budget-usd", false)?;
    let turns = positive_number(inv, "max-turns", true)?;
    let model = inv.flag("model");
    let dry_run = inv.has("dry-run");
    let store = ctx.store()?;
    let sides = merge_sides(inv, ctx, Some(&store))?;
    let runs = [inv.flag("ours-run"), inv.flag("theirs-run")];
    let bundles = [
        runs[0].map(|r| load_bundle(ctx, r)).transpose()?,
        runs[1].map(|r| load_bundle(ctx, r)).transpose()?,
    ];
    let [b, o, t] = &sides;
    let prep = agentvcs_merge::prepare(
        b,
        o,
        t,
        bundles[0].as_ref(),
        bundles[1].as_ref(),
        inv.values("metric"),
    )?;

    // 1. nothing to judge: commit mechanically, no agent
    if prep.conflicts.is_empty() {
        if dry_run {
            return okv(
                json!({"ok": true, "dry_run": true, "merge_id": prep.merge_id,
                              "conflicts": 0, "command": null}),
            );
        }
        let res = json!({
            "protocol": PROTOCOL, "type": "merge_resolution", "merge_id": prep.merge_id,
            "resolutions": {},
            "rationale": "no conflicts: every dimension merged mechanically (spec/MERGE.md §1)",
            "author": {"type": "agent", "id": "agentvcs"},
        });
        return commit_merge(
            ctx,
            &store,
            &sides,
            &res,
            inv.flag("suite"),
            Some(Value::Null),
        );
    }

    let claude = find_claude(inv.flag("claude"), &ctx.cwd);
    if claude.is_none() && !dry_run {
        return Err(err(
            "E_RESOLVER_NOT_FOUND",
            match inv.flag("claude") {
                Some(c) => format!("--claude {c:?} is not an executable file"),
                None => "no `claude` on PATH (install Claude Code, or pass --claude <path>)".into(),
            },
        ));
    }
    let claude = claude.map_or_else(
        || inv.flag("claude").unwrap_or("claude").to_owned(),
        |p| p.to_string_lossy().into_owned(),
    );

    // 2. workspace (what the agent sees) and session (what only agentvcs sees)
    let root = fresh_root(&prep.merge_id)?;
    let ws = root.join("workspace");
    let session = root.join("session");
    std::fs::create_dir(&ws)?;
    std::fs::create_dir(&session)?;
    std::fs::write(ws.join("prepare.json"), pretty(&prep.to_value())?)?;
    let mut files = serde_json::Map::new();
    for (name, m) in WORKSPACE_FILES.iter().zip(&sides) {
        let text = pretty(&m.value)?;
        std::fs::write(ws.join(format!("{name}.json")), &text)?;
        let f = session.join(format!("{name}.json"));
        std::fs::write(&f, &text)?;
        files.insert((*name).into(), f.to_string_lossy().into_owned().into());
    }
    if bundles.iter().any(Option::is_some) {
        let md = branches_md(&[
            ("ours", bundles[0].as_ref()),
            ("theirs", bundles[1].as_ref()),
        ]);
        std::fs::write(ws.join("BRANCHES.md"), md)?;
    }
    let sess = json!({
        "protocol": PROTOCOL, "type": "merge_session", "merge_id": prep.merge_id,
        "base": prep.base, "ours": prep.ours, "theirs": prep.theirs, "files": files,
        "store": ctx.cwd.to_string_lossy(),
        "ours_run": runs[0], "theirs_run": runs[1], "metrics": inv.values("metric"),
        "workspace": ws.to_string_lossy(),
    });
    std::fs::write(session.join("session.json"), pretty(&sess)?)?;

    // 3. the agent's only MCP server: this merge's prepare and commit
    let mut server = self_command();
    let exe = server.remove(0);
    server.extend([
        "mcp".into(),
        "--merge-session".into(),
        session.to_string_lossy().into_owned(),
    ]);
    let mcp_path = session.join("mcp.json");
    std::fs::write(
        &mcp_path,
        pretty(
            &json!({"mcpServers": {SERVER: {"type": "stdio", "command": exe, "args": server}}}),
        )?,
    )?;
    let mcp_str = mcp_path.to_string_lossy().into_owned();

    // 4. the command line
    let argv = command(
        &claude,
        &mcp_str,
        model,
        budget.as_deref(),
        turns.as_deref(),
    );
    if dry_run {
        return okv(json!({
            "ok": true, "dry_run": true, "merge_id": prep.merge_id,
            "conflicts": prep.conflicts.len(), "workspace": ws.to_string_lossy(),
            "session": session.to_string_lossy(), "mcp_config": mcp_str,
            "cwd": ws.to_string_lossy(), "command": argv, "stdin": TASK,
        }));
    }
    let version = Command::new(&claude)
        .arg("--version")
        .stdin(Stdio::null())
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned());
    let transcript = run_agent(&argv, &ws, &session)?;
    let events: Vec<Value> = transcript
        .split(|&c| c == b'\n')
        .filter_map(|l| serde_json::from_slice(l).ok())
        .collect();

    // 5. audit before commit
    let violations = audit(&events, &ws);
    if !violations.is_empty() {
        return Err(err(
            "E_RESOLVER_ESCAPED",
            format!(
                "the resolver used tools outside its sandbox; nothing was committed ({}). \
                 Session kept at {}",
                violations.join("; "),
                root.display()
            ),
        ));
    }
    let staged = match std::fs::read(session.join("staged.json")) {
        Ok(bytes) => parse_bytes(&bytes)?,
        Err(_) => {
            return Err(err(
                "E_RESOLVER_NO_COMMIT",
                format!(
                    "the session ended without a valid staged resolution; nothing was committed. \
                     Session kept at {}",
                    root.display()
                ),
            ))
        }
    };

    // 6. commit as `merge commit`, with the resolver in the record
    let result = events.iter().rev().find(|e| e["type"] == "result");
    let init_model = events
        .iter()
        .find(|e| e["type"] == "system" && e["subtype"] == "init")
        .and_then(|e| e["model"].as_str());
    let resolver = json!({
        "agent": "claude-code",
        "version": version,
        "model": init_model.or(model),
        "cost_usd": result.map_or(Value::Null, |r| r["total_cost_usd"].clone()),
        "turns": result.map_or(Value::Null, |r| r["num_turns"].clone()),
        "transcript": b3_bytes(&transcript),
    });
    let out = commit_merge(
        ctx,
        &store,
        &sides,
        &staged,
        inv.flag("suite"),
        Some(resolver),
    )?;
    store.put_blob(&transcript)?;
    let _ = std::fs::remove_dir_all(&root);
    Ok(out)
}

/// Run the agent in `ws` with the task on stdin; stream its stdout to
/// `session/transcript.jsonl` as it lands (the run's position is visible from
/// outside) and return it.
fn run_agent(argv: &[String], ws: &Path, session: &Path) -> Result<Vec<u8>> {
    let log = session.join("transcript.jsonl");
    eprintln!(
        "agentvcs merge resolve: running {} in {}; transcript: {}",
        argv[0],
        ws.display(),
        log.display()
    );
    let stderr = std::fs::File::create(session.join("stderr.txt"))?;
    let mut child = Command::new(&argv[0])
        .args(&argv[1..])
        .current_dir(ws)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(stderr)
        .spawn()
        .map_err(|e| {
            err(
                "E_RESOLVER_NOT_FOUND",
                format!("cannot run {}: {e}", argv[0]),
            )
        })?;
    if let Some(mut si) = child.stdin.take() {
        let _ = si.write_all(TASK.as_bytes());
    }
    let mut sink = std::fs::File::create(&log)?;
    let mut all = Vec::new();
    let mut rd = BufReader::new(child.stdout.take().expect("piped"));
    let mut line = Vec::new();
    loop {
        line.clear();
        if rd.read_until(b'\n', &mut line)? == 0 {
            break;
        }
        sink.write_all(&line)?;
        sink.flush()?;
        all.extend_from_slice(&line);
    }
    child.wait()?;
    Ok(all)
}

// ------------------------------------------------------------------ the audit

/// Lexically resolve `.` and `..`, then canonicalize the longest existing
/// ancestor (so `/var/…` and `/private/var/…` compare equal on macOS).
fn real_path(p: &Path) -> PathBuf {
    let mut norm = PathBuf::new();
    for c in p.components() {
        match c {
            Component::ParentDir => {
                norm.pop();
            }
            Component::CurDir => {}
            c => norm.push(c),
        }
    }
    let mut base = norm.clone();
    let mut rest = Vec::new();
    while !base.exists() {
        match (base.file_name().map(|n| n.to_owned()), base.parent()) {
            (Some(n), Some(parent)) => {
                rest.push(n);
                base = parent.to_path_buf();
            }
            _ => return norm,
        }
    }
    let mut out = base.canonicalize().unwrap_or(base);
    for n in rest.into_iter().rev() {
        out.push(n);
    }
    out
}

fn inside(path: &str, ws: &Path) -> bool {
    let p = Path::new(path);
    let p = if p.is_absolute() {
        p.to_path_buf()
    } else {
        ws.join(p)
    };
    real_path(&p).starts_with(real_path(ws))
}

/// Every out-of-sandbox call in a stream-json transcript: a tool other than
/// `Read`, `mcp__agentvcs__prepare` and `mcp__agentvcs__commit`, or a `Read`
/// outside `ws`. Denied calls count: an attempt is a violation (spec/MERGE.md §6).
pub fn audit(events: &[Value], ws: &Path) -> Vec<String> {
    let mut out = Vec::new();
    for e in events.iter().filter(|e| e["type"] == "assistant") {
        let Some(content) = e["message"]["content"].as_array() else {
            continue;
        };
        for c in content.iter().filter(|c| c["type"] == "tool_use") {
            let name = c["name"].as_str().unwrap_or("?");
            if !ALLOWED_TOOLS.contains(&name) {
                out.push(format!("tool {name}"));
                continue;
            }
            if name == "Read" {
                for k in ["file_path", "path", "notebook_path"] {
                    if let Some(p) = c["input"][k].as_str() {
                        if !inside(p, ws) {
                            out.push(format!("Read {p}"));
                        }
                    }
                }
            }
        }
    }
    out
}

// ------------------------------------------------------------------ the session server

/// The merge a session server is bound to (`<dir>/session.json`).
pub struct Session {
    dir: PathBuf,
    ctx: Ctx,
    files: [PathBuf; 3],
    runs: [Option<String>; 2],
    metrics: Vec<String>,
}

impl Session {
    pub fn load(dir: &Path) -> Result<Session> {
        let s = parse_bytes(&std::fs::read(dir.join("session.json")).map_err(|e| {
            err(
                "E_NOT_FOUND",
                format!("{}: no session.json: {e}", dir.display()),
            )
        })?)?;
        if s["type"] != "merge_session" {
            return Err(err("E_SCHEMA", "session.json is not a merge_session"));
        }
        let file = |k: &str| {
            s["files"][k]
                .as_str()
                .map(PathBuf::from)
                .ok_or_else(|| err("E_SCHEMA", format!("session.json has no files.{k}")))
        };
        let run = |k: &str| s[k].as_str().map(str::to_owned);
        Ok(Session {
            dir: dir.to_path_buf(),
            ctx: Ctx {
                cwd: PathBuf::from(s["store"].as_str().unwrap_or(".")),
                stdin: None,
            },
            files: [file("base")?, file("ours")?, file("theirs")?],
            runs: [run("ours_run"), run("theirs_run")],
            metrics: s["metrics"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|m| m.as_str().map(str::to_owned))
                        .collect()
                })
                .unwrap_or_default(),
        })
    }

    fn sides(&self) -> Result<[Manifest; 3]> {
        let get = |p: &PathBuf| -> Result<Manifest> {
            normalize(&parse_bytes(&std::fs::read(p).map_err(|e| {
                err("E_NOT_FOUND", format!("{}: {e}", p.display()))
            })?)?)
        };
        Ok([
            get(&self.files[0])?,
            get(&self.files[1])?,
            get(&self.files[2])?,
        ])
    }

    /// `prepare`: the prepare output of this merge (what prepare.json holds).
    pub fn prepare(&self) -> Result<Value> {
        let [b, o, t] = self.sides()?;
        let bundles = [
            self.runs[0]
                .as_deref()
                .map(|r| load_bundle(&self.ctx, r))
                .transpose()?,
            self.runs[1]
                .as_deref()
                .map(|r| load_bundle(&self.ctx, r))
                .transpose()?,
        ];
        Ok(agentvcs_merge::prepare(
            &b,
            &o,
            &t,
            bundles[0].as_ref(),
            bundles[1].as_ref(),
            &self.metrics,
        )?
        .to_value())
    }

    /// `commit`: the checks of spec/MERGE.md §4, then the resolution is staged in
    /// `<dir>/staged.json` (its author set to claude-code). The store is not touched.
    pub fn commit(&self, args: &Value) -> Result<Value> {
        if let Some(k) = args
            .as_object()
            .and_then(|a| a.keys().find(|k| *k != "resolution"))
        {
            return Err(err("E_USAGE", format!("unknown argument {k:?} for commit")));
        }
        let mut res = match &args["resolution"] {
            Value::Null => return Err(err("E_SCHEMA", "missing argument `resolution`")),
            // a resolution sent as JSON text is the same resolution
            Value::String(s) => parse_bytes(s.as_bytes())?,
            v => v.clone(),
        };
        if let Some(m) = res.as_object_mut() {
            m.insert("author".into(), author());
        }
        let [b, o, t] = self.sides()?;
        let c = agentvcs_merge::commit(&b, &o, &t, &res)?;
        write_atomic(&self.dir.join("staged.json"), &pretty(&res)?)?;
        Ok(json!({
            "ok": true, "staged": true, "merge_id": c.record["merge_id"],
            "merged": c.merged.manifest_id,
            "message": "the resolution is valid and staged; agentvcs commits it after this session ends",
        }))
    }

    /// One tool call, as `(exit code, JSON)`; `None` for an unknown tool.
    pub fn call(&self, name: &str, args: &Value) -> Option<(i32, Value)> {
        let r = match name {
            "prepare" => self.prepare(),
            "commit" => self.commit(args),
            _ => return None,
        };
        Some(match r {
            Ok(v) => (0, v),
            Err(e) => (e.exit_code(), crate::error_json(&e)),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read(p: &str) -> Value {
        json!({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": p}}]}})
    }

    fn tool(name: &str) -> Value {
        json!({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t", "name": name, "input": {}}]}})
    }

    #[test]
    fn audit_allows_reads_inside_the_workspace_however_spelled() {
        let d = tempfile::tempdir().unwrap();
        let ws = d.path().canonicalize().unwrap().join("workspace");
        std::fs::create_dir(&ws).unwrap();
        std::fs::write(ws.join("prepare.json"), "{}").unwrap();
        // the temp dir as the OS names it (on macOS /var/..., a symlink to /private/var/...)
        let raw = d.path().join("workspace/prepare.json");
        let ok = [
            read("prepare.json"),
            read("./BRANCHES.md"),
            read(ws.join("prepare.json").to_str().unwrap()),
            read(raw.to_str().unwrap()),
            read(ws.join("sub/../ours.json").to_str().unwrap()),
            tool(PREPARE_TOOL),
            tool(COMMIT_TOOL),
            json!({"type": "user", "message": {"content": [{"type": "tool_result"}]}}),
        ];
        assert_eq!(audit(&ok, &ws), Vec::<String>::new());
    }

    #[test]
    fn audit_flags_every_escape() {
        let d = tempfile::tempdir().unwrap();
        let ws = d.path().canonicalize().unwrap().join("workspace");
        std::fs::create_dir(&ws).unwrap();
        let sibling = d.path().join("workspace-evil/x");
        let bad = [
            read("../session/session.json"),
            read("/etc/hosts"),
            read(sibling.to_str().unwrap()),
            read(d.path().to_str().unwrap()),
            tool("Bash"),
            tool("Write"),
            tool("Glob"),
            tool("mcp__agentvcs__merge_commit"),
            tool("mcp__other__prepare"),
        ];
        let v = audit(&bad, &ws);
        assert_eq!(v.len(), bad.len(), "{v:?}");
    }

    #[test]
    fn command_is_the_spec_line() {
        let argv = command("claude", "/s/mcp.json", None, None, None);
        assert_eq!(argv.len(), 21);
        assert_eq!(
            argv[16],
            "Read,mcp__agentvcs__prepare,mcp__agentvcs__commit"
        );
        let argv = command("claude", "/s/mcp.json", Some("m"), Some("1"), Some("3"));
        assert_eq!(
            argv[21..],
            ["--model", "m", "--max-budget-usd", "1", "--max-turns", "3"]
        );
    }
}
