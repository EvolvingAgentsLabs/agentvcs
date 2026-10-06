//! The agentvcs CLI as a library: argv in, `(exit code, one JSON object)` out.
//! The binary, the MCP server and the Python binding all go through [`run`].

pub mod commands;
pub mod mcp;
pub mod spec;

use agentvcs_core::Error;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;

/// Global options, accepted anywhere on the command line.
#[derive(Debug, Clone, Default)]
pub struct Globals {
    pub dir: Option<PathBuf>,
    pub json: bool,
    pub yes: bool,
    pub help: bool,
}

/// A parsed command line.
#[derive(Debug, Clone)]
pub struct Invocation {
    pub cmd: &'static spec::Cmd,
    pub pos: Vec<String>,
    pub flags: HashMap<&'static str, String>,
    /// Values of repeatable flags, in command-line order.
    pub lists: HashMap<&'static str, Vec<String>>,
    pub yes: bool,
}

impl Invocation {
    pub fn flag(&self, name: &str) -> Option<&str> {
        self.flags.get(name).map(String::as_str)
    }

    pub fn has(&self, name: &str) -> bool {
        self.flags.contains_key(name)
    }

    /// Every value of a repeatable flag (empty when not given).
    pub fn values(&self, name: &str) -> &[String] {
        self.lists.get(name).map_or(&[], Vec::as_slice)
    }
}

fn usage(msg: impl Into<String>) -> Error {
    Error::new("E_USAGE", msg)
}

/// Strip the global options out of `args`.
pub fn split_globals(args: &[String]) -> Result<(Globals, Vec<String>), Error> {
    let mut g = Globals::default();
    let mut rest = Vec::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-C" => {
                let d = it.next().ok_or_else(|| usage("-C needs a directory"))?;
                g.dir = Some(PathBuf::from(d));
            }
            "--json" => g.json = true,
            "--yes" | "-y" => g.yes = true,
            "--help" | "-h" => g.help = true,
            _ => rest.push(a.clone()),
        }
    }
    Ok((g, rest))
}

/// Parse the command words, positionals and flags of a command line.
pub fn parse(args: &[String], yes: bool) -> Result<Invocation, Error> {
    let cmd = spec::lookup(args).ok_or_else(|| {
        usage(match args.first() {
            None => "no command given".to_string(),
            Some(_) => format!("unknown command: {}", args.join(" ")),
        })
    })?;
    let mut pos = Vec::new();
    let mut flags = HashMap::new();
    let mut lists: HashMap<&'static str, Vec<String>> = HashMap::new();
    let mut it = args[cmd.words.len()..].iter();
    while let Some(a) = it.next() {
        let name_val: Option<(&str, Option<&str>)> = if a == "-o" {
            Some(("output", None))
        } else if let Some(s) = a.strip_prefix("--") {
            Some(match s.split_once('=') {
                Some((n, v)) => (n, Some(v)),
                None => (s, None),
            })
        } else {
            None
        };
        match name_val {
            None => pos.push(a.clone()),
            Some((name, inline)) => {
                let fl = cmd.flags.iter().find(|f| f.name == name).ok_or_else(|| {
                    usage(format!("{}: unknown flag --{name}", cmd.words.join(" ")))
                })?;
                let v = if fl.value {
                    match inline {
                        Some(v) => v.to_owned(),
                        None => it
                            .next()
                            .ok_or_else(|| usage(format!("--{name} needs a value")))?
                            .clone(),
                    }
                } else {
                    if inline.is_some() {
                        return Err(usage(format!("--{name} takes no value")));
                    }
                    String::new()
                };
                if fl.multi {
                    lists.entry(fl.name).or_default().push(v);
                } else if flags.insert(fl.name, v).is_some() {
                    return Err(usage(format!("--{name} given twice")));
                }
            }
        }
    }
    if pos.len() != cmd.positionals.len() {
        let names: Vec<&str> = cmd.positionals.iter().map(|p| p.0).collect();
        return Err(usage(format!(
            "{} takes {} positional argument(s): {}",
            cmd.words.join(" "),
            names.len(),
            names.join(" ")
        )));
    }
    for fl in cmd.flags {
        if fl.required && !flags.contains_key(fl.name) && !lists.contains_key(fl.name) {
            return Err(usage(format!(
                "{} needs --{}",
                cmd.words.join(" "),
                fl.name
            )));
        }
    }
    Ok(Invocation {
        cmd,
        pos,
        flags,
        lists,
        yes,
    })
}

/// `{"ok": false, "error": {...}}`.
pub fn error_json(e: &Error) -> Value {
    json!({"ok": false, "error": {"code": e.code, "message": e.message}})
}

/// The help text as JSON.
pub fn help_json() -> Value {
    let cmds: Vec<Value> = spec::COMMANDS
        .iter()
        .map(|c| {
            let mut syn = c.words.join(" ");
            for p in c.positionals {
                syn.push_str(&format!(" <{}>", p.0));
            }
            for f in c.flags {
                let s = if f.value {
                    format!("--{} <v>", f.name)
                } else {
                    format!("--{}", f.name)
                };
                syn.push(' ');
                syn.push_str(&if f.required { s } else { format!("[{s}]") });
                if f.multi {
                    syn.push_str("...");
                }
            }
            json!({"usage": syn, "help": c.help})
        })
        .collect();
    json!({"ok": true, "version": env!("CARGO_PKG_VERSION"), "protocol": agentvcs_core::PROTOCOL,
           "global": "-C <dir>, --json, --yes", "commands": cmds})
}

/// Run one command line (global options included) with `stdin` as the body of
/// commands that read one. Returns the exit code and the JSON output.
pub fn run(args: &[String], stdin: Option<String>, cwd: PathBuf) -> (i32, Value) {
    let (g, rest) = match split_globals(args) {
        Ok(x) => x,
        Err(e) => return (e.exit_code(), error_json(&e)),
    };
    if g.help || rest.is_empty() || rest[0] == "help" {
        return (0, help_json());
    }
    let cwd = match &g.dir {
        Some(d) if d.is_absolute() => d.clone(),
        Some(d) => cwd.join(d),
        None => cwd,
    };
    let inv = match parse(&rest, g.yes) {
        Ok(i) => i,
        Err(e) => return (e.exit_code(), error_json(&e)),
    };
    let ctx = commands::Ctx { cwd, stdin };
    match commands::dispatch(&inv, &ctx) {
        Ok((code, v)) => (code, v),
        Err(e) => (e.exit_code(), error_json(&e)),
    }
}

/// The whole `agentvcs` executable as a function: reads stdin for the commands
/// that take a body, serves MCP for `mcp`, prints one JSON object on stdout and
/// returns the exit code. The binary and the Python SDK's `python -m agentvcs`
/// both call this, so they cannot drift apart.
pub fn main_with(args: &[String], cwd: PathBuf) -> i32 {
    use std::io::Read;
    let (globals, rest) = match split_globals(args) {
        Ok(x) => x,
        Err(e) => return print_out(e.exit_code(), &error_json(&e), true),
    };
    if rest.first().map(String::as_str) == Some("mcp") {
        let base = match &globals.dir {
            Some(d) if d.is_absolute() => d.clone(),
            Some(d) => cwd.join(d),
            None => cwd,
        };
        return mcp::serve_stdio(base);
    }
    let stdin = match spec::lookup(&rest) {
        Some(c) if c.stdin => {
            let mut s = String::new();
            let _ = std::io::stdin().read_to_string(&mut s);
            Some(s)
        }
        _ => None,
    };
    let (code, out) = run(args, stdin, cwd);
    print_out(code, &out, globals.json)
}

fn print_out(code: i32, out: &Value, compact: bool) -> i32 {
    use std::io::Write;
    let text = if compact {
        serde_json::to_string(out)
    } else {
        serde_json::to_string_pretty(out)
    }
    .unwrap_or_else(|_| "{\"ok\":false}".into());
    let mut so = std::io::stdout().lock();
    let _ = writeln!(so, "{text}");
    let _ = so.flush();
    code
}
