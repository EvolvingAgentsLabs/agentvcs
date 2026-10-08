//! `agentvcs._native`: thin wrappers over the Rust core for the Python SDK
//! (ADR-0007). No protocol logic lives here or in the Python layer above it:
//! every function forwards to `agentvcs-core` / `agentvcs-cli` and returns the
//! same JSON the CLI prints, as Python objects. Errors raise `AgentvcsError`,
//! whose `code` attribute is the protocol code (`E_…`).

use agentvcs_core::json::parse;
use agentvcs_core::manifest::normalize;
use agentvcs_core::store::Store;
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::Mutex;

create_exception!(agentvcs._native, AgentvcsError, PyException);

fn to_py(py: Python<'_>, v: &Value) -> PyResult<Py<PyAny>> {
    let json = py.import("json")?;
    Ok(json.call_method1("loads", (v.to_string(),))?.unbind())
}

fn raise(py: Python<'_>, code: &str, message: &str) -> PyErr {
    let e = AgentvcsError::new_err(format!("{code}: {message}"));
    // best effort: the attribute is what Python callers branch on
    let _ = e.value(py).setattr("code", code);
    e
}

fn err(py: Python<'_>, e: agentvcs_core::Error) -> PyErr {
    raise(py, e.code, &e.message)
}

fn parse_text(py: Python<'_>, text: &str) -> PyResult<Value> {
    parse(text).map_err(|e| err(py, e.into()))
}

/// Run one CLI command line in `dir`. Returns `(exit_code, output)`; never raises
/// for a command-level error — the output carries `{"ok": false, "error": …}`.
#[pyfunction]
#[pyo3(signature = (args, stdin = None, dir = "."))]
fn cli(
    py: Python<'_>,
    args: Vec<String>,
    stdin: Option<String>,
    dir: &str,
) -> PyResult<(i32, Py<PyAny>)> {
    let (code, out) = agentvcs_cli::run(&args, stdin, PathBuf::from(dir));
    Ok((code, to_py(py, &out)?))
}

/// The `agentvcs` executable, in-process (`python -m agentvcs`): prints one JSON
/// object on stdout and returns the exit code.
#[pyfunction]
fn main(argv: Vec<String>) -> PyResult<i32> {
    let cwd = std::env::current_dir().unwrap_or_else(|_| ".".into());
    Ok(agentvcs_cli::main_with(&argv, cwd))
}

/// `hash(x)` of PROTOCOL §1 for a JSON text, without a store.
#[pyfunction]
fn hash_json(py: Python<'_>, text: &str) -> PyResult<String> {
    let v = parse_text(py, text)?;
    agentvcs_core::hash::hash_value(&v).map_err(|e| err(py, e.into()))
}

/// BLAKE3 of raw bytes, `b3:`-prefixed.
#[pyfunction]
fn hash_bytes(data: &[u8]) -> String {
    agentvcs_core::hash::b3_bytes(data)
}

/// An open store. Holding one avoids re-opening the store (and its SQLite index)
/// on every step — the library path that meets the 2 ms `step record` target
/// (docs/BENCHMARKS.md).
#[pyclass(frozen, module = "agentvcs._native")]
struct NativeStore {
    inner: Mutex<Store>,
    dir: PathBuf,
}

impl NativeStore {
    fn with<T>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&Store) -> agentvcs_core::Result<T>,
    ) -> PyResult<T> {
        let s = self
            .inner
            .lock()
            .map_err(|_| raise(py, "E_IO", "store lock poisoned"))?;
        f(&s).map_err(|e| err(py, e))
    }
}

#[pymethods]
impl NativeStore {
    /// Open the store of the project in `dir`; with `init`, create it first.
    #[new]
    #[pyo3(signature = (dir = ".", init = false))]
    fn new(py: Python<'_>, dir: &str, init: bool) -> PyResult<Self> {
        let d = PathBuf::from(dir);
        let s = if init {
            Store::init(&d)
        } else {
            Store::open(&d)
        }
        .map_err(|e| err(py, e))?;
        Ok(NativeStore {
            inner: Mutex::new(s),
            dir: d,
        })
    }

    #[getter]
    fn dir(&self) -> String {
        self.dir.to_string_lossy().into_owned()
    }

    /// Validate, fill and store a manifest given as JSON text (authoring form).
    fn snapshot_json(&self, py: Python<'_>, text: &str) -> PyResult<Py<PyAny>> {
        let v = parse_text(py, text)?;
        let out = self.with(py, |s| {
            let m = normalize(&v)?;
            s.put_manifest(&m)?;
            Ok(json!({"ok": true, "manifest_id": m.manifest_id, "dimensions": m.dimension_hashes()}))
        })?;
        to_py(py, &out)
    }

    /// A stored manifest (normalized form).
    fn get_manifest(&self, py: Python<'_>, manifest_id: &str) -> PyResult<Py<PyAny>> {
        let v = self.with(py, |s| Ok(s.get_manifest(manifest_id)?.value))?;
        to_py(py, &v)
    }

    /// The writer state of a run, from its last ledger line: what a harness polls
    /// between steps to learn that a patch was applied (ADR-0007 §3).
    fn run_state(&self, py: Python<'_>, run_id: &str) -> PyResult<Py<PyAny>> {
        let v = self.with(py, |s| {
            let st = s.run_state(run_id)?;
            Ok(json!({
                "run_id": st.run_id, "next_seq": st.next_seq, "next_step": st.next_step,
                "active": st.active, "ended": st.ended, "last_hash": st.last_hash,
            }))
        })?;
        to_py(py, &v)
    }

    /// The entries of a run with `seq >= from_seq`, in order.
    #[pyo3(signature = (run_id, from_seq = 0))]
    fn ledger(&self, py: Python<'_>, run_id: &str, from_seq: u64) -> PyResult<Py<PyAny>> {
        let v = self.with(py, |s| {
            Ok(Value::Array(
                s.read_ledger(run_id)?
                    .into_iter()
                    .filter(|e| e["seq"].as_u64().is_some_and(|q| q >= from_seq))
                    .collect(),
            ))
        })?;
        to_py(py, &v)
    }

    /// Append a step; `body` is the StepRecord body as JSON text.
    fn step_record(&self, py: Python<'_>, run_id: &str, body: &str) -> PyResult<Py<PyAny>> {
        let b = parse_text(py, body)?;
        let v = self.with(py, |s| agentvcs_cli::commands::record_step(s, run_id, b))?;
        to_py(py, &v)
    }

    /// Apply a gated patch (raises `E_PATCH_UNGATED` otherwise).
    #[pyo3(signature = (patch_id, at_step = None))]
    fn patch_apply(
        &self,
        py: Python<'_>,
        patch_id: &str,
        at_step: Option<u64>,
    ) -> PyResult<Py<PyAny>> {
        let v = self.with(py, |s| {
            agentvcs_cli::commands::apply_patch(s, patch_id, at_step)
        })?;
        to_py(py, &v)
    }

    /// Store raw bytes; returns their id.
    fn put_blob(&self, py: Python<'_>, data: &[u8]) -> PyResult<String> {
        self.with(py, |s| s.put_blob(data))
    }

    /// Store a JSON text as its canonical bytes; returns `hash(value)`.
    fn put_json(&self, py: Python<'_>, text: &str) -> PyResult<String> {
        let v = parse_text(py, text)?;
        self.with(py, |s| s.put_json(&v))
    }

    /// The bytes of a stored object.
    fn get_object<'py>(&self, py: Python<'py>, id: &str) -> PyResult<Bound<'py, PyBytes>> {
        let b = self.with(py, |s| s.get_object(id))?;
        Ok(PyBytes::new(py, &b))
    }
}

#[pymodule]
#[pyo3(name = "_native")]
fn agentvcs_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("AgentvcsError", m.py().get_type::<AgentvcsError>())?;
    m.add("PROTOCOL", agentvcs_core::PROTOCOL)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<NativeStore>()?;
    // `merge resolve` starts `agentvcs mcp --merge-session` for the agent; in-process,
    // the running executable is the interpreter, so the command is `<python> -m agentvcs`
    let exe: String = m.py().import("sys")?.getattr("executable")?.extract()?;
    if !exe.is_empty() {
        agentvcs_cli::resolve::set_self_command(vec![exe, "-m".into(), "agentvcs".into()]);
    }
    for f in [
        wrap_pyfunction!(cli, m)?,
        wrap_pyfunction!(main, m)?,
        wrap_pyfunction!(hash_json, m)?,
        wrap_pyfunction!(hash_bytes, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
