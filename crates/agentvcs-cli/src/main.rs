//! `agentvcs` — prints exactly one JSON object on stdout and exits with the
//! codes of `spec/cli/EXIT_CODES.md`. Never prompts.

use agentvcs_cli::{error_json, run, spec, split_globals};
use std::io::{Read, Write};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cwd = std::env::current_dir().unwrap_or_else(|_| ".".into());
    let (globals, rest) = match split_globals(&args) {
        Ok(x) => x,
        Err(e) => finish(e.exit_code(), &error_json(&e), true),
    };
    if rest.first().map(String::as_str) == Some("mcp") {
        let base = match &globals.dir {
            Some(d) if d.is_absolute() => d.clone(),
            Some(d) => cwd.join(d),
            None => cwd,
        };
        let code = agentvcs_cli::mcp::serve_stdio(base);
        std::process::exit(code);
    }
    let stdin = match spec::lookup(&rest) {
        Some(c) if c.stdin => {
            let mut s = String::new();
            let _ = std::io::stdin().read_to_string(&mut s);
            Some(s)
        }
        _ => None,
    };
    let (code, out) = run(&args, stdin, cwd);
    finish(code, &out, globals.json)
}

fn finish(code: i32, out: &serde_json::Value, compact: bool) -> ! {
    let text = if compact {
        serde_json::to_string(out)
    } else {
        serde_json::to_string_pretty(out)
    }
    .unwrap_or_else(|_| "{\"ok\":false}".into());
    let mut so = std::io::stdout().lock();
    let _ = writeln!(so, "{text}");
    let _ = so.flush();
    std::process::exit(code)
}
