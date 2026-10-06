//! The local store (ADR-0004): `.agentvcs/` inside the project.
//!
//! ```text
//! .agentvcs/
//!   objects/<2 hex>/<62 hex>   content-addressed blobs: raw bytes, or JCS bytes for JSON
//!   manifests/<64 hex>.json    normalized manifests by manifest_id (first annotation wins)
//!   runs/<run_id>.jsonl        append-only hash-chained ledgers, one JCS entry per line
//!   patches/<64 hex>.json      patch proposals and their gate result (mutable record)
//!   frozen/<64 hex>.json       freeze markers
//!   index.sqlite               derived; `rebuild_index` recreates it from the files above
//! ```
//!
//! Nothing is true only in the index.

use crate::error::{Error, Result};
use crate::hash::{b3_bytes, hex_of, is_hash};
use crate::json::{canonical, parse_bytes_with, Mode};
use crate::ledger::RunState;
use crate::manifest::{normalize, Manifest};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::cell::OnceCell;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

pub const STORE_DIR: &str = ".agentvcs";

pub struct Store {
    root: PathBuf,
    index: OnceCell<Connection>,
}

impl std::fmt::Debug for Store {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Store").field("root", &self.root).finish()
    }
}

/// Run ids become file names: `[A-Za-z0-9._-]+`, not starting with `.`.
pub fn check_run_id(run_id: &str) -> Result<()> {
    let ok = !run_id.is_empty()
        && run_id.len() <= 200
        && !run_id.starts_with('.')
        && run_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'));
    if ok {
        Ok(())
    } else {
        Err(Error::new(
            "E_USAGE",
            format!("run id {run_id:?} must match [A-Za-z0-9._-]+ and not start with '.'"),
        ))
    }
}

fn check_id(id: &str) -> Result<&str> {
    if is_hash(id) {
        Ok(hex_of(id))
    } else {
        Err(Error::new(
            "E_USAGE",
            format!("{id:?} is not an id (b3:<64 hex>)"),
        ))
    }
}

/// Write a file atomically (temp file + rename).
fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    fs::write(&tmp, bytes)?;
    fs::rename(&tmp, path)?;
    Ok(())
}

fn read_json(path: &Path) -> Result<Value> {
    Ok(parse_bytes_with(&fs::read(path)?, Mode::CanonicalForm)?)
}

/// The last line of a file that ends with `\n` (or `None` if empty).
fn last_line(path: &Path) -> Result<Option<Vec<u8>>> {
    let mut f = File::open(path)?;
    let len = f.metadata()?.len();
    if len == 0 {
        return Ok(None);
    }
    let mut buf: Vec<u8> = Vec::new();
    let mut pos = len;
    let chunk = 4096u64;
    loop {
        let start = pos.saturating_sub(chunk);
        let mut part = vec![0u8; (pos - start) as usize];
        f.seek(SeekFrom::Start(start))?;
        f.read_exact(&mut part)?;
        part.extend_from_slice(&buf);
        buf = part;
        pos = start;
        // ignore the trailing newline, look for the one before it
        let body = buf.strip_suffix(b"\n").unwrap_or(&buf);
        if let Some(nl) = body.iter().rposition(|c| *c == b'\n') {
            return Ok(Some(body[nl + 1..].to_vec()));
        }
        if pos == 0 {
            return Ok(Some(body.to_vec()));
        }
    }
}

impl Store {
    /// Create `.agentvcs/` (idempotent) and open it.
    pub fn init(project: &Path) -> Result<Store> {
        let root = project.join(STORE_DIR);
        for d in ["objects", "manifests", "runs", "patches", "frozen"] {
            fs::create_dir_all(root.join(d))?;
        }
        let s = Store {
            root,
            index: OnceCell::new(),
        };
        s.index()?;
        Ok(s)
    }

    /// Open an existing store (`E_NO_STORE` if there is none).
    pub fn open(project: &Path) -> Result<Store> {
        let root = project.join(STORE_DIR);
        if !root.join("objects").is_dir() || !root.join("runs").is_dir() {
            return Err(Error::new(
                "E_NO_STORE",
                format!(
                    "no agentvcs store in {} (run `agentvcs init`)",
                    project.display()
                ),
            ));
        }
        Ok(Store {
            root,
            index: OnceCell::new(),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    // ------------------------------------------------------------- objects

    fn object_path(&self, hex: &str) -> PathBuf {
        self.root.join("objects").join(&hex[..2]).join(&hex[2..])
    }

    /// Store raw bytes; returns their id.
    pub fn put_blob(&self, bytes: &[u8]) -> Result<String> {
        let id = b3_bytes(bytes);
        let p = self.object_path(hex_of(&id));
        if !p.exists() {
            fs::create_dir_all(p.parent().expect("parent"))?;
            write_atomic(&p, bytes)?;
        }
        Ok(id)
    }

    /// Store a JSON value as its canonical bytes; returns `hash(v)`.
    pub fn put_json(&self, v: &Value) -> Result<String> {
        self.put_blob(canonical(v)?.as_bytes())
    }

    pub fn get_object(&self, id: &str) -> Result<Vec<u8>> {
        let p = self.object_path(check_id(id)?);
        fs::read(&p).map_err(|_| Error::new("E_NOT_FOUND", format!("object {id} not found")))
    }

    // ------------------------------------------------------------- manifests

    fn manifest_path(&self, id: &str) -> Result<PathBuf> {
        Ok(self
            .root
            .join("manifests")
            .join(format!("{}.json", check_id(id)?)))
    }

    /// Store a normalized manifest and its dimension contents. If a manifest with
    /// the same id exists, its annotations win (ADR-0005).
    pub fn put_manifest(&self, m: &Manifest) -> Result<()> {
        let p = self.manifest_path(&m.manifest_id)?;
        if p.exists() {
            return Ok(());
        }
        for d in m.dimensions().values() {
            self.put_json(&d["content"])?;
        }
        write_atomic(&p, canonical(&m.value)?.as_bytes())?;
        let name = m.value.get("name").and_then(Value::as_str);
        self.index()?.execute(
            "INSERT OR IGNORE INTO manifests(manifest_id, name) VALUES (?1, ?2)",
            params![m.manifest_id, name],
        )?;
        Ok(())
    }

    pub fn has_manifest(&self, id: &str) -> bool {
        self.manifest_path(id).is_ok_and(|p| p.exists())
    }

    pub fn get_manifest(&self, id: &str) -> Result<Manifest> {
        let p = self.manifest_path(id)?;
        if !p.exists() {
            return Err(Error::new(
                "E_NOT_FOUND",
                format!("manifest {id} not found"),
            ));
        }
        normalize(&read_json(&p)?)
    }

    // ------------------------------------------------------------- runs

    fn run_path(&self, run_id: &str) -> Result<PathBuf> {
        check_run_id(run_id)?;
        Ok(self.root.join("runs").join(format!("{run_id}.jsonl")))
    }

    pub fn run_exists(&self, run_id: &str) -> Result<bool> {
        Ok(self.run_path(run_id)?.exists())
    }

    /// The writer state of a run, read from its last ledger line.
    pub fn run_state(&self, run_id: &str) -> Result<RunState> {
        let p = self.run_path(run_id)?;
        if !p.exists() {
            return Err(Error::new("E_NOT_FOUND", format!("run {run_id} not found")));
        }
        match last_line(&p)? {
            None => Ok(RunState::new(run_id)),
            Some(line) => {
                let e = parse_bytes_with(&line, Mode::CanonicalForm)?;
                let mut st = RunState::after(&e)?;
                if st.ended {
                    // run_end alone does not say which manifest was active
                    st.active = None;
                }
                Ok(st)
            }
        }
    }

    /// Append the next entry of a run. `state` must match the ledger on disk
    /// (a stale writer would fork the chain); it is advanced on success.
    pub fn append(&self, state: &mut RunState, kind: &str, body: Value) -> Result<Value> {
        let p = self.run_path(&state.run_id)?;
        // Build (and check) the entry first: a refused entry must not leave an
        // empty ledger file behind.
        let mut next = state.clone();
        let (entry, mut line) = next.append(kind, body)?;
        // Advisory exclusive lock around compare-and-append, so a harness recording
        // steps and a supervisor applying a patch from another process cannot both
        // append the same `seq` (ADR-0007 §4). Released when `f` is dropped.
        let mut f = OpenOptions::new().create(true).append(true).open(&p)?;
        f.lock()?;
        let on_disk = if f.metadata()?.len() == 0 {
            None
        } else {
            Some(self.run_state(&state.run_id)?)
        };
        let disk_seq = on_disk.as_ref().map_or(0, |s| s.next_seq);
        let disk_hash = on_disk.as_ref().and_then(|s| s.last_hash.clone());
        if disk_seq != state.next_seq || disk_hash != state.last_hash {
            return Err(Error::new(
                "E_STALE_STATE",
                format!(
                    "run {} is at seq {disk_seq}, writer thought {}",
                    state.run_id, state.next_seq
                ),
            ));
        }
        line.push('\n');
        f.write_all(line.as_bytes())?;
        if std::env::var_os("AGENTVCS_FSYNC").is_some() {
            f.sync_data()?;
        }
        *state = next;
        self.index_run(state)?;
        Ok(entry)
    }

    /// Every entry of a run, in order.
    pub fn read_ledger(&self, run_id: &str) -> Result<Vec<Value>> {
        let p = self.run_path(run_id)?;
        let bytes = fs::read(&p)
            .map_err(|_| Error::new("E_NOT_FOUND", format!("run {run_id} not found")))?;
        bytes
            .split(|c| *c == b'\n')
            .filter(|l| !l.is_empty())
            .map(|l| Ok(parse_bytes_with(l, Mode::CanonicalForm)?))
            .collect()
    }

    /// Run ids in the store, sorted.
    pub fn runs(&self) -> Result<Vec<String>> {
        let mut out: Vec<String> = fs::read_dir(self.root.join("runs"))?
            .filter_map(|e| e.ok())
            .filter_map(|e| {
                e.file_name()
                    .to_str()
                    .and_then(|n| n.strip_suffix(".jsonl"))
                    .map(str::to_owned)
            })
            .collect();
        out.sort();
        Ok(out)
    }

    /// The audit bundle of a run (`PROTOCOL.md §4`).
    pub fn bundle(&self, run_id: &str) -> Result<Value> {
        let ledger = self.read_ledger(run_id)?;
        let mut manifests = serde_json::Map::new();
        for e in &ledger {
            for k in ["manifest_id", "from_manifest", "to_manifest"] {
                if let Some(id) = e["body"].get(k).and_then(Value::as_str) {
                    if !manifests.contains_key(id) {
                        manifests.insert(id.to_owned(), self.get_manifest(id)?.value);
                    }
                }
            }
        }
        Ok(serde_json::json!({
            "protocol": crate::PROTOCOL,
            "type": "audit_bundle",
            "run_id": run_id,
            "manifests": manifests,
            "ledger": ledger,
        }))
    }

    // ------------------------------------------------------------- patches

    fn patch_path(&self, id: &str) -> Result<PathBuf> {
        Ok(self
            .root
            .join("patches")
            .join(format!("{}.json", check_id(id)?)))
    }

    /// Store (or overwrite) a patch record: the proposal fields plus `run_id`,
    /// `semantic_diff` and `gate_result`.
    pub fn put_patch(&self, record: &Value) -> Result<()> {
        let id = record["patch_id"].as_str().unwrap_or_default();
        write_atomic(&self.patch_path(id)?, canonical(record)?.as_bytes())?;
        self.index_patch(record)
    }

    pub fn get_patch(&self, id: &str) -> Result<Value> {
        let p = self.patch_path(id)?;
        if !p.exists() {
            return Err(Error::new("E_NOT_FOUND", format!("patch {id} not found")));
        }
        read_json(&p)
    }

    /// Patch records whose gate passed and whose `to_manifest` is `id`.
    pub fn passed_gates_for(&self, manifest_id: &str) -> Result<Vec<String>> {
        let mut st = self.index()?.prepare(
            "SELECT patch_id FROM patches WHERE to_manifest = ?1 AND gate_passed = 1 ORDER BY patch_id",
        )?;
        let rows = st.query_map(params![manifest_id], |r| r.get::<_, String>(0))?;
        Ok(rows.collect::<std::result::Result<_, _>>()?)
    }

    // ------------------------------------------------------------- freeze

    pub fn freeze(&self, manifest_id: &str, record: &Value) -> Result<()> {
        let p = self
            .root
            .join("frozen")
            .join(format!("{}.json", check_id(manifest_id)?));
        if !p.exists() {
            write_atomic(&p, canonical(record)?.as_bytes())?;
        }
        Ok(())
    }

    pub fn is_frozen(&self, manifest_id: &str) -> Result<bool> {
        Ok(self
            .root
            .join("frozen")
            .join(format!("{}.json", check_id(manifest_id)?))
            .exists())
    }

    // ------------------------------------------------------------- index

    fn index(&self) -> Result<&Connection> {
        if let Some(c) = self.index.get() {
            return Ok(c);
        }
        let c = Connection::open(self.root.join("index.sqlite"))?;
        c.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             CREATE TABLE IF NOT EXISTS manifests(manifest_id TEXT PRIMARY KEY, name TEXT);
             CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, head_seq INTEGER,
                 head_hash TEXT, active_manifest TEXT, next_step INTEGER, ended INTEGER);
             CREATE TABLE IF NOT EXISTS patches(patch_id TEXT PRIMARY KEY, run_id TEXT,
                 from_manifest TEXT, to_manifest TEXT, gate_passed INTEGER);",
        )?;
        Ok(self.index.get_or_init(|| c))
    }

    fn index_run(&self, st: &RunState) -> Result<()> {
        self.index()?.execute(
            "INSERT OR REPLACE INTO runs(run_id, head_seq, head_hash, active_manifest, next_step, ended)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                st.run_id,
                st.next_seq as i64 - 1,
                st.last_hash,
                st.active,
                st.next_step as i64,
                st.ended
            ],
        )?;
        Ok(())
    }

    fn index_patch(&self, r: &Value) -> Result<()> {
        let passed = r["gate_result"]["passed"].as_bool().unwrap_or(false);
        self.index()?.execute(
            "INSERT OR REPLACE INTO patches(patch_id, run_id, from_manifest, to_manifest, gate_passed)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                r["patch_id"].as_str(),
                r["run_id"].as_str(),
                r["from_manifest"].as_str(),
                r["to_manifest"].as_str(),
                passed
            ],
        )?;
        Ok(())
    }

    /// Recreate the index from the files of the store.
    pub fn rebuild_index(&self) -> Result<()> {
        let c = self.index()?;
        c.execute_batch("DELETE FROM manifests; DELETE FROM runs; DELETE FROM patches;")?;
        for e in fs::read_dir(self.root.join("manifests"))? {
            let m = normalize(&read_json(&e?.path())?)?;
            c.execute(
                "INSERT OR IGNORE INTO manifests(manifest_id, name) VALUES (?1, ?2)",
                params![m.manifest_id, m.value.get("name").and_then(Value::as_str)],
            )?;
        }
        for run in self.runs()? {
            let st = self.run_state(&run)?;
            // an ended run's active manifest comes from the full ledger
            let mut full = RunState::new(&run);
            for e in self.read_ledger(&run)? {
                full.observe(&e)?;
            }
            debug_assert_eq!(full.next_seq, st.next_seq);
            self.index_run(&full)?;
        }
        for e in fs::read_dir(self.root.join("patches"))? {
            self.index_patch(&read_json(&e?.path())?)?;
        }
        Ok(())
    }

    /// Every index row as text, sorted (tests compare rebuilds with this).
    pub fn index_snapshot(&self) -> Result<Vec<String>> {
        let c = self.index()?;
        let mut out = Vec::new();
        for (table, cols) in [("manifests", 2), ("runs", 6), ("patches", 5)] {
            let mut st = c.prepare(&format!("SELECT * FROM {table}"))?;
            let rows = st.query_map([], |r| {
                let mut s = format!("{table}:");
                for i in 0..cols {
                    let v: rusqlite::types::Value = r.get(i)?;
                    s.push_str(&format!("{v:?}|"));
                }
                Ok(s)
            })?;
            for r in rows {
                out.push(r?);
            }
        }
        out.sort();
        Ok(out)
    }
}
