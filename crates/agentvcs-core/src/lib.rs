//! agentvcs protocol v0.1 core: canonical JSON, BLAKE3 ids, manifests, ledger
//! entries and the local store.
pub mod error;
pub mod hash;
pub mod json;
pub mod manifest;
pub mod schema;

pub use error::{Error, Result};

/// The protocol tag carried by every object.
pub const PROTOCOL: &str = "agentvcs/0.1";
