//! BLAKE3-256 identifiers: `b3:` + 64 lowercase hex digits.

use crate::json::{canonical, JsonError};
use serde_json::Value;

/// `b3:` + hex(BLAKE3(bytes)).
pub fn b3_bytes(b: &[u8]) -> String {
    let mut s = String::with_capacity(67);
    s.push_str("b3:");
    s.push_str(blake3::hash(b).to_hex().as_str());
    s
}

/// `hash(x)` of the spec: BLAKE3 over the JCS bytes of `x`.
pub fn hash_value(v: &Value) -> Result<String, JsonError> {
    Ok(b3_bytes(canonical(v)?.as_bytes()))
}

/// Whether `s` has the form of a protocol hash.
pub fn is_hash(s: &str) -> bool {
    s.len() == 67
        && s.starts_with("b3:")
        && s.as_bytes()[3..]
            .iter()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c))
}

/// The 64 hex digits of a protocol hash (no prefix).
pub fn hex_of(id: &str) -> &str {
    id.strip_prefix("b3:").unwrap_or(id)
}
