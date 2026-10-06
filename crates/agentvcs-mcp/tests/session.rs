//! A scripted stdio session against the generic server.

use agentvcs_mcp::{Server, Tool};
use serde_json::{json, Value};

#[test]
fn scripted_session() {
    let mut s = Server {
        name: "t".into(),
        version: "0".into(),
        tools: vec![Tool {
            name: "echo".into(),
            description: "echo".into(),
            input_schema: json!({"type": "object"}),
        }],
        call: |name: &str, args: &Value| {
            (name == "echo").then(|| (0, json!({"ok": true, "args": args})))
        },
    };
    let input = [
        json!({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
        json!({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json!({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json!({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "echo", "arguments": {"x": 1}}}),
        json!({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}),
        json!({"jsonrpc": "2.0", "id": 5, "method": "bogus"}),
    ]
    .iter()
    .map(|v| v.to_string())
    .collect::<Vec<_>>()
    .join("\n")
        + "\nnot json\n";
    let mut out = Vec::new();
    s.serve(input.as_bytes(), &mut out).unwrap();
    let lines: Vec<Value> = String::from_utf8(out)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(lines.len(), 6, "the notification gets no reply");
    assert_eq!(lines[0]["result"]["protocolVersion"], "2025-03-26");
    assert_eq!(lines[1]["result"]["tools"][0]["name"], "echo");
    assert_eq!(lines[2]["result"]["structuredContent"]["args"]["x"], 1);
    assert_eq!(lines[2]["result"]["isError"], false);
    assert_eq!(lines[3]["error"]["code"], -32602);
    assert_eq!(lines[4]["error"]["code"], -32601);
    assert_eq!(lines[5]["error"]["code"], -32700);
}
