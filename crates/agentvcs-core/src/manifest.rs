//! HarnessManifest normalization (`spec/PROTOCOL.md §2`).

use crate::error::{Error, Result};
use crate::hash::hash_value;
use crate::json::canonical;
use crate::schema::{manifest_ok, KINDS};
use crate::PROTOCOL;
use serde_json::{Map, Value};

/// A validated manifest with every `content_hash` and the `manifest_id` filled in.
#[derive(Debug, Clone, PartialEq)]
pub struct Manifest {
    /// The full normalized manifest, annotations included.
    pub value: Value,
    pub manifest_id: String,
}

impl Manifest {
    pub fn dimensions(&self) -> &Map<String, Value> {
        self.value["dimensions"].as_object().expect("validated")
    }

    /// `{name: content_hash}`, as `snapshot` reports it.
    pub fn dimension_hashes(&self) -> Map<String, Value> {
        self.dimensions()
            .iter()
            .map(|(k, d)| (k.clone(), d["content_hash"].clone()))
            .collect()
    }
}

/// Validate a manifest in the spec's order and fill in its hashes:
/// `E_CANONICAL`, `E_PROTOCOL_VERSION`, `E_UNKNOWN_KIND`, `E_SCHEMA`,
/// `E_CONTENT_HASH`, `E_MANIFEST_ID`.
pub fn normalize(v: &Value) -> Result<Manifest> {
    canonical(v)?;
    let Some(m) = v.as_object() else {
        return Err(Error::new("E_SCHEMA", "a manifest is a JSON object"));
    };
    if m.get("protocol").and_then(Value::as_str) != Some(PROTOCOL) {
        return Err(Error::new(
            "E_PROTOCOL_VERSION",
            format!("manifest protocol must be {PROTOCOL}"),
        ));
    }
    if let Some(dims) = m.get("dimensions").and_then(Value::as_object) {
        for (name, d) in dims {
            if let Some(d) = d.as_object() {
                let k = d.get("kind").and_then(Value::as_str);
                if !k.is_some_and(|k| KINDS.contains(&k)) {
                    return Err(Error::new(
                        "E_UNKNOWN_KIND",
                        format!("dimension {name:?} has an unknown kind"),
                    ));
                }
            }
        }
    }
    if !manifest_ok(v) {
        return Err(Error::new(
            "E_SCHEMA",
            "manifest does not match harness_manifest.schema.json",
        ));
    }
    let mut out = m.clone();
    let dims = out
        .get_mut("dimensions")
        .and_then(Value::as_object_mut)
        .expect("validated");
    let mut id_dims = Map::new();
    for (name, d) in dims.iter_mut() {
        let d = d.as_object_mut().expect("validated");
        let ch = hash_value(&d["content"])?;
        if let Some(stated) = d.get("content_hash") {
            if stated != &Value::String(ch.clone()) {
                return Err(Error::new(
                    "E_CONTENT_HASH",
                    format!("dimension {name:?}: content_hash does not match its content"),
                ));
            }
        }
        d.insert("content_hash".into(), Value::String(ch));
        id_dims.insert(name.clone(), Value::Object(d.clone()));
    }
    let mut id_obj = Map::new();
    id_obj.insert("protocol".into(), Value::String(PROTOCOL.into()));
    id_obj.insert("dimensions".into(), Value::Object(id_dims));
    let mid = hash_value(&Value::Object(id_obj))?;
    if let Some(stated) = out.get("manifest_id") {
        if stated != &Value::String(mid.clone()) {
            return Err(Error::new(
                "E_MANIFEST_ID",
                "manifest_id does not match {protocol, dimensions}",
            ));
        }
    }
    out.insert("manifest_id".into(), Value::String(mid.clone()));
    Ok(Manifest {
        value: Value::Object(out),
        manifest_id: mid,
    })
}
