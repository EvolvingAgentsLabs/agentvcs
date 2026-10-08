//! Errors carry a stable protocol code (`spec/cli/EXIT_CODES.md`); consumers branch on it.

use crate::json::JsonError;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error {
    pub code: &'static str,
    pub message: String,
}

impl Error {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Error {
            code,
            message: message.into(),
        }
    }

    /// Process exit code for this error (`spec/cli/EXIT_CODES.md`).
    pub fn exit_code(&self) -> i32 {
        exit_code_for(self.code)
    }
}

/// Exit code of an error code. Codes not listed in EXIT_CODES.md are mapped by
/// the class they belong to (ADR-0006 §3).
pub fn exit_code_for(code: &str) -> i32 {
    match code {
        "E_USAGE" | "E_EXISTS" => 2,
        "E_RESOLVER_NO_COMMIT" => 1,
        "E_NO_STORE"
        | "E_NOT_FOUND"
        | "E_IO"
        | "E_RUN_EXISTS"
        | "E_INDEX"
        | "E_RESOLVER_NOT_FOUND" => 4,
        "E_PATCH_UNGATED" | "E_NOT_GATED" | "E_RESOLVER_ESCAPED" => 5,
        _ => 3,
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for Error {}

impl From<JsonError> for Error {
    fn from(e: JsonError) -> Self {
        match e {
            JsonError::Canonical => Error::new("E_CANONICAL", e.to_string()),
            JsonError::Syntax(_) => Error::new("E_SCHEMA", e.to_string()),
        }
    }
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::new("E_IO", e.to_string())
    }
}

impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Error::new("E_INDEX", e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;
