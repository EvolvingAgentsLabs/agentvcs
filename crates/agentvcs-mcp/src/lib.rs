//! A minimal MCP server: JSON-RPC 2.0 over stdio, newline-delimited
//! (`initialize`, `tools/list`, `tools/call`, `ping`). It knows nothing about
//! agentvcs: the caller provides the tools and a function that executes one.

use serde_json::{json, Value};
use std::io::{BufRead, Write};

/// Protocol revision this server speaks when the client does not ask for one.
pub const DEFAULT_PROTOCOL_VERSION: &str = "2025-06-18";

/// One tool: name, description and JSON Schema of its arguments.
#[derive(Debug, Clone)]
pub struct Tool {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

/// The result of executing a tool: the CLI exit code and its JSON output.
pub type CallResult = (i32, Value);

pub struct Server<F> {
    pub name: String,
    pub version: String,
    pub tools: Vec<Tool>,
    pub call: F,
}

fn response(id: &Value, result: Value) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "result": result})
}

fn error(id: &Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})
}

impl<F: FnMut(&str, &Value) -> Option<CallResult>> Server<F> {
    /// Handle one JSON-RPC message; `None` for notifications.
    pub fn handle(&mut self, msg: &Value) -> Option<Value> {
        let id = msg.get("id").cloned();
        let method = msg.get("method").and_then(Value::as_str);
        let Some(id) = id else {
            return None; // notification (e.g. notifications/initialized)
        };
        let Some(method) = method else {
            return Some(error(&id, -32600, "invalid request"));
        };
        let params = msg.get("params").cloned().unwrap_or(json!({}));
        Some(match method {
            "initialize" => {
                let pv = params
                    .get("protocolVersion")
                    .and_then(Value::as_str)
                    .unwrap_or(DEFAULT_PROTOCOL_VERSION);
                response(
                    &id,
                    json!({
                        "protocolVersion": pv,
                        "capabilities": {"tools": {"listChanged": false}},
                        "serverInfo": {"name": self.name, "version": self.version},
                    }),
                )
            }
            "ping" => response(&id, json!({})),
            "tools/list" => {
                let tools: Vec<Value> = self
                    .tools
                    .iter()
                    .map(|t| json!({"name": t.name, "description": t.description, "inputSchema": t.input_schema}))
                    .collect();
                response(&id, json!({"tools": tools}))
            }
            "tools/call" => {
                let name = params.get("name").and_then(Value::as_str).unwrap_or("");
                let args = params.get("arguments").cloned().unwrap_or(json!({}));
                match (self.call)(name, &args) {
                    None => error(&id, -32602, &format!("unknown tool: {name}")),
                    Some((code, out)) => {
                        let text = serde_json::to_string(&out).unwrap_or_default();
                        response(
                            &id,
                            json!({
                                "content": [{"type": "text", "text": text}],
                                "structuredContent": out,
                                "isError": out.get("ok") != Some(&Value::Bool(true)),
                                "_meta": {"exitCode": code},
                            }),
                        )
                    }
                }
            }
            _ => error(&id, -32601, &format!("method not found: {method}")),
        })
    }

    /// Serve until EOF.
    pub fn serve<R: BufRead, W: Write>(&mut self, input: R, mut output: W) -> std::io::Result<()> {
        for line in input.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let reply = match serde_json::from_str::<Value>(&line) {
                Err(_) => Some(error(&Value::Null, -32700, "parse error")),
                Ok(Value::Array(batch)) => {
                    let out: Vec<Value> = batch.iter().filter_map(|m| self.handle(m)).collect();
                    (!out.is_empty()).then_some(Value::Array(out))
                }
                Ok(msg) => self.handle(&msg),
            };
            if let Some(r) = reply {
                writeln!(output, "{}", serde_json::to_string(&r).unwrap_or_default())?;
                output.flush()?;
            }
        }
        Ok(())
    }
}
