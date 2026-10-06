//! `agentvcs_py`: thin wrappers over the Rust core. No logic lives here; every
//! function returns the same JSON the CLI prints, as Python objects. Errors raise
//! `AgentvcsError` whose message starts with the protocol code (`E_…`).

use agentvcs_core::json::parse;
use agentvcs_core::store::Store;
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use serde_json::Value;
use std::path::PathBuf;

create_exception!(agentvcs_py, AgentvcsError, PyException);

fn to_py(py: Python<'_>, v: &Value) -> PyResult<Py<PyAny>> {
    let json = py.import("json")?;
    Ok(json.call_method1("loads", (v.to_string(),))?.unbind())
}

fn err(e: agentvcs_core::Error) -> PyErr {
    AgentvcsError::new_err(format!("{}: {}", e.code, e.message))
}

/// Run a CLI command line in `dir`; raise unless it succeeded (exit 0 or 1).
fn cli(py: Python<'_>, dir: &str, args: &[&str], stdin: Option<String>) -> PyResult<Py<PyAny>> {
    let argv: Vec<String> = args.iter().map(|s| s.to_string()).collect();
    let (code, out) = agentvcs_cli::run(&argv, stdin, PathBuf::from(dir));
    if code > 1 {
        let e = &out["error"];
        return Err(AgentvcsError::new_err(format!(
            "{}: {}",
            e["code"].as_str().unwrap_or("E_UNKNOWN"),
            e["message"].as_str().unwrap_or("")
        )));
    }
    to_py(py, &out)
}

/// Create the store in `dir` (idempotent).
#[pyfunction]
#[pyo3(signature = (dir = "."))]
fn init(py: Python<'_>, dir: &str) -> PyResult<Py<PyAny>> {
    cli(py, dir, &["init"], None)
}

/// Validate, fill and store a manifest file.
#[pyfunction]
#[pyo3(signature = (manifest_path, dir = "."))]
fn snapshot(py: Python<'_>, manifest_path: &str, dir: &str) -> PyResult<Py<PyAny>> {
    cli(py, dir, &["snapshot", manifest_path], None)
}

/// Start a run under a manifest id (or file).
#[pyfunction]
#[pyo3(signature = (manifest, run_id = None, dir = "."))]
fn run_start(
    py: Python<'_>,
    manifest: &str,
    run_id: Option<&str>,
    dir: &str,
) -> PyResult<Py<PyAny>> {
    let mut args = vec!["run", "start", "--manifest", manifest];
    if let Some(r) = run_id {
        args.extend(["--run-id", r]);
    }
    cli(py, dir, &args, None)
}

/// Append a step; `body` is a JSON string (the StepRecord body). This is the
/// in-process library path — no subprocess.
#[pyfunction]
#[pyo3(signature = (run_id, body, dir = "."))]
fn step_record(py: Python<'_>, run_id: &str, body: &str, dir: &str) -> PyResult<Py<PyAny>> {
    let store = Store::open(&PathBuf::from(dir)).map_err(err)?;
    let body = parse(body).map_err(|e| err(e.into()))?;
    let out = agentvcs_cli::commands::record_step(&store, run_id, body).map_err(err)?;
    to_py(py, &out)
}

/// Apply a gated patch (raises `E_PATCH_UNGATED` otherwise).
#[pyfunction]
#[pyo3(signature = (patch_id, at_step = None, dir = "."))]
fn patch_apply(
    py: Python<'_>,
    patch_id: &str,
    at_step: Option<u64>,
    dir: &str,
) -> PyResult<Py<PyAny>> {
    let store = Store::open(&PathBuf::from(dir)).map_err(err)?;
    let out = agentvcs_cli::commands::apply_patch(&store, patch_id, at_step).map_err(err)?;
    to_py(py, &out)
}

/// Verify a run id or bundle file.
#[pyfunction]
#[pyo3(signature = (target, dir = "."))]
fn verify(py: Python<'_>, target: &str, dir: &str) -> PyResult<Py<PyAny>> {
    cli(py, dir, &["verify", target], None)
}

/// Blame a run id or bundle file for a metric.
#[pyfunction]
#[pyo3(signature = (target, metric, dir = "."))]
fn blame(py: Python<'_>, target: &str, metric: &str, dir: &str) -> PyResult<Py<PyAny>> {
    cli(py, dir, &["blame", target, "--metric", metric], None)
}

/// Any CLI command line, e.g. `run(["patch", "propose", ...])`.
#[pyfunction]
#[pyo3(signature = (args, stdin = None, dir = "."))]
fn run(py: Python<'_>, args: Vec<String>, stdin: Option<String>, dir: &str) -> PyResult<Py<PyAny>> {
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    cli(py, dir, &refs, stdin)
}

#[pymodule]
fn agentvcs_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("AgentvcsError", m.py().get_type::<AgentvcsError>())?;
    m.add("PROTOCOL", agentvcs_core::PROTOCOL)?;
    for f in [
        wrap_pyfunction!(init, m)?,
        wrap_pyfunction!(snapshot, m)?,
        wrap_pyfunction!(run_start, m)?,
        wrap_pyfunction!(step_record, m)?,
        wrap_pyfunction!(patch_apply, m)?,
        wrap_pyfunction!(verify, m)?,
        wrap_pyfunction!(blame, m)?,
        wrap_pyfunction!(run, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
