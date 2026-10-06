//! `agentvcs mcp`: every command of [`crate::spec::COMMANDS`] as an MCP tool.
//! A tool call is turned into the same argv the CLI takes, so the JSON is the
//! CLI's JSON byte for byte.

use crate::spec::{Cmd, COMMANDS};
use agentvcs_mcp::{Server, Tool};
use serde_json::{json, Map, Value};
use std::path::PathBuf;

fn prop(name: &str) -> String {
    name.replace('-', "_")
}

/// The tool definition of one command.
pub fn tool_of(c: &Cmd) -> Tool {
    let mut props = Map::new();
    let mut required = Vec::new();
    for (name, help) in c.positionals {
        props.insert(prop(name), json!({"type": "string", "description": help}));
        required.push(prop(name));
    }
    for f in c.flags {
        let schema = if f.multi {
            json!({"type": ["string", "array"], "items": {"type": "string"}, "description": f.help})
        } else if f.value {
            json!({"type": ["string", "number", "array"], "description": f.help})
        } else {
            json!({"type": "boolean", "description": f.help})
        };
        props.insert(prop(f.name), schema);
        if f.required {
            required.push(prop(f.name));
        }
    }
    if c.stdin {
        props.insert(
            "body".into(),
            json!({"type": "object", "description": "the JSON body the CLI reads on stdin"}),
        );
        required.push("body".into());
    }
    props.insert(
        "dir".into(),
        json!({"type": "string", "description": "project directory (like -C); default: the server's"}),
    );
    props.insert(
        "yes".into(),
        json!({"type": "boolean", "description": "confirm a destructive operation (like --yes)"}),
    );
    Tool {
        name: c.tool.into(),
        description: format!("agentvcs {}: {}", c.words.join(" "), c.help),
        input_schema: json!({"type": "object", "properties": props, "required": required,
                             "additionalProperties": false}),
    }
}

fn arg_text(v: &Value) -> Option<String> {
    match v {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        Value::Array(a) => Some(
            a.iter()
                .map(|x| arg_text(x).unwrap_or_default())
                .collect::<Vec<_>>()
                .join(","),
        ),
        Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

/// argv (and stdin) for a tool call, or a usage error message.
pub fn argv_of(c: &Cmd, args: &Value) -> Result<(Vec<String>, Option<String>), String> {
    let empty = Map::new();
    let a = args.as_object().unwrap_or(&empty);
    let known: Vec<String> = c
        .positionals
        .iter()
        .map(|p| prop(p.0))
        .chain(c.flags.iter().map(|f| prop(f.name)))
        .chain(["body", "dir", "yes"].iter().map(|s| s.to_string()))
        .collect();
    if let Some(k) = a.keys().find(|k| !known.contains(k)) {
        return Err(format!("unknown argument {k:?} for {}", c.tool));
    }
    let mut argv: Vec<String> = Vec::new();
    if let Some(d) = a.get("dir").and_then(Value::as_str) {
        argv.push("-C".into());
        argv.push(d.into());
    }
    argv.extend(c.words.iter().map(|w| w.to_string()));
    for (name, _) in c.positionals {
        let v = a
            .get(&prop(name))
            .and_then(arg_text)
            .ok_or_else(|| format!("missing argument {:?}", prop(name)))?;
        argv.push(v);
    }
    for f in c.flags {
        match a.get(&prop(f.name)) {
            None | Some(Value::Null) => {}
            Some(Value::Bool(false)) if !f.value => {}
            Some(Value::Array(vs)) if f.multi => {
                for v in vs {
                    argv.push(format!("--{}", f.name));
                    argv.push(arg_text(v).ok_or_else(|| format!("bad value for {}", f.name))?);
                }
            }
            Some(v) => {
                argv.push(format!("--{}", f.name));
                if f.value {
                    argv.push(arg_text(v).ok_or_else(|| format!("bad value for {}", f.name))?);
                }
            }
        }
    }
    if a.get("yes") == Some(&Value::Bool(true)) {
        argv.push("--yes".into());
    }
    argv.push("--json".into());
    let stdin = if c.stdin {
        Some(
            a.get("body")
                .map(|b| b.to_string())
                .ok_or("missing argument \"body\"")?,
        )
    } else {
        None
    };
    Ok((argv, stdin))
}

/// Serve MCP on stdin/stdout from `cwd`. Returns the process exit code.
pub fn serve_stdio(cwd: PathBuf) -> i32 {
    let mut server = Server {
        name: "agentvcs".into(),
        version: env!("CARGO_PKG_VERSION").into(),
        tools: COMMANDS.iter().map(tool_of).collect(),
        call: |name: &str, args: &Value| {
            let c = COMMANDS.iter().find(|c| c.tool == name)?;
            Some(match argv_of(c, args) {
                Ok((argv, stdin)) => crate::run(&argv, stdin, cwd.clone()),
                Err(m) => (
                    2,
                    crate::error_json(&agentvcs_core::Error::new("E_USAGE", m)),
                ),
            })
        },
    };
    let stdin = std::io::stdin();
    match server.serve(stdin.lock(), std::io::stdout().lock()) {
        Ok(()) => 0,
        Err(_) => 4,
    }
}
