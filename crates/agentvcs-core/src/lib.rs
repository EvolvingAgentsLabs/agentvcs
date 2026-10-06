//! agentvcs protocol v0.1 core: canonical JSON, BLAKE3 ids, manifests, ledger
//! entries and the local store.
pub mod error;
pub mod hash;
pub mod json;
pub mod manifest;
pub mod schema;
#[doc(hidden)]
pub mod testutil;

pub use error::{Error, Result};

/// The protocol tag carried by every object.
pub const PROTOCOL: &str = "agentvcs/0.1";
