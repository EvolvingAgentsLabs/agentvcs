//! JSON parsing and RFC 8785 (JCS) canonicalization, as `spec/PROTOCOL.md §1` defines them.
//!
//! The parser is our own rather than `serde_json::from_str` for three reasons the
//! spec makes observable:
//! - an integer literal above 2^53 − 1 must be refused (`E_CANONICAL`), not rounded,
//!   so integer literals and float literals must stay distinguishable;
//! - a lone surrogate escape (`"\ud800"`) must be `E_CANONICAL`, not a syntax error;
//! - `NaN` / `Infinity` tokens (accepted by some producers) must be `E_CANONICAL`.
//!
//! Values are ordinary `serde_json::Value`s: integer literals become `i64` numbers,
//! every other number an `f64`.

use serde_json::{Map, Number, Value};
use std::fmt::Write as _;

/// Largest integer an IEEE-754 double represents exactly with its neighbours.
pub const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
const MAX_DEPTH: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JsonError {
    /// Not JSON at all (the CLI reports this as `E_SCHEMA`).
    Syntax(String),
    /// JSON, but not canonicalizable: lone surrogate, non-finite or unsafe integer.
    Canonical,
}

impl std::fmt::Display for JsonError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JsonError::Syntax(m) => write!(f, "invalid JSON: {m}"),
            JsonError::Canonical => write!(
                f,
                "value cannot be canonicalized (lone surrogate, non-finite number or integer beyond 2^53-1)"
            ),
        }
    }
}

impl std::error::Error for JsonError {}

/// How integer literals beyond 2^53 − 1 are treated.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// `spec/PROTOCOL.md §1` as written: any such literal is `E_CANONICAL`.
    Strict,
    /// Also accept such a literal when it is exactly the JCS serialization of the
    /// double nearest to it (e.g. `100000000000000000000`, the canonical form of
    /// `1e20`). Needed to read back canonical bytes we wrote ourselves; see
    /// `docs/adr/0006-f1-implementation-notes.md` §1.
    CanonicalForm,
}

/// Parse one JSON document (surrounding whitespace allowed, nothing else), strictly.
pub fn parse(s: &str) -> Result<Value, JsonError> {
    parse_with(s, Mode::Strict)
}

/// Parse one JSON document with the given integer policy.
pub fn parse_with(s: &str, mode: Mode) -> Result<Value, JsonError> {
    let mut p = Parser {
        b: s.as_bytes(),
        i: 0,
        depth: 0,
        mode,
    };
    p.ws();
    let v = p.value()?;
    p.ws();
    if p.i != p.b.len() {
        return Err(p.err("trailing characters"));
    }
    Ok(v)
}

/// Parse bytes that must be UTF-8 JSON, strictly.
pub fn parse_bytes(b: &[u8]) -> Result<Value, JsonError> {
    parse_bytes_with(b, Mode::Strict)
}

/// Parse bytes that must be UTF-8 JSON.
pub fn parse_bytes_with(b: &[u8], mode: Mode) -> Result<Value, JsonError> {
    let s = std::str::from_utf8(b).map_err(|_| JsonError::Syntax("not UTF-8".into()))?;
    parse_with(s.strip_prefix('\u{feff}').unwrap_or(s), mode)
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
    depth: usize,
    mode: Mode,
}

impl Parser<'_> {
    fn err(&self, m: &str) -> JsonError {
        JsonError::Syntax(format!("{m} at byte {}", self.i))
    }

    fn ws(&mut self) {
        while let Some(&c) = self.b.get(self.i) {
            if c == b' ' || c == b'\t' || c == b'\n' || c == b'\r' {
                self.i += 1;
            } else {
                break;
            }
        }
    }

    fn eat(&mut self, lit: &[u8]) -> bool {
        if self.b[self.i..].starts_with(lit) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Result<Value, JsonError> {
        match self.b.get(self.i) {
            None => Err(self.err("unexpected end")),
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => Ok(Value::String(self.string()?)),
            Some(b't') if self.eat(b"true") => Ok(Value::Bool(true)),
            Some(b'f') if self.eat(b"false") => Ok(Value::Bool(false)),
            Some(b'n') if self.eat(b"null") => Ok(Value::Null),
            Some(b'N') if self.eat(b"NaN") => Err(JsonError::Canonical),
            Some(b'I') if self.eat(b"Infinity") => Err(JsonError::Canonical),
            Some(b'-') if self.b[self.i..].starts_with(b"-Infinity") => Err(JsonError::Canonical),
            Some(b'-' | b'0'..=b'9') => self.number(),
            _ => Err(self.err("unexpected character")),
        }
    }

    fn enter(&mut self) -> Result<(), JsonError> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(self.err("nesting too deep"));
        }
        Ok(())
    }

    fn object(&mut self) -> Result<Value, JsonError> {
        self.enter()?;
        self.i += 1;
        let mut m = Map::new();
        self.ws();
        if self.b.get(self.i) == Some(&b'}') {
            self.i += 1;
            self.depth -= 1;
            return Ok(Value::Object(m));
        }
        loop {
            self.ws();
            if self.b.get(self.i) != Some(&b'"') {
                return Err(self.err("expected object key"));
            }
            let k = self.string()?;
            self.ws();
            if self.b.get(self.i) != Some(&b':') {
                return Err(self.err("expected ':'"));
            }
            self.i += 1;
            self.ws();
            let v = self.value()?;
            m.insert(k, v);
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b'}') => {
                    self.i += 1;
                    break;
                }
                _ => return Err(self.err("expected ',' or '}'")),
            }
        }
        self.depth -= 1;
        Ok(Value::Object(m))
    }

    fn array(&mut self) -> Result<Value, JsonError> {
        self.enter()?;
        self.i += 1;
        let mut a = Vec::new();
        self.ws();
        if self.b.get(self.i) == Some(&b']') {
            self.i += 1;
            self.depth -= 1;
            return Ok(Value::Array(a));
        }
        loop {
            self.ws();
            a.push(self.value()?);
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b']') => {
                    self.i += 1;
                    break;
                }
                _ => return Err(self.err("expected ',' or ']'")),
            }
        }
        self.depth -= 1;
        Ok(Value::Array(a))
    }

    fn hex4(&mut self) -> Result<u32, JsonError> {
        let h = self
            .b
            .get(self.i..self.i + 4)
            .ok_or_else(|| self.err("short \\u escape"))?;
        let mut v = 0u32;
        for &c in h {
            let d = (c as char)
                .to_digit(16)
                .ok_or_else(|| self.err("bad \\u escape"))?;
            v = v * 16 + d;
        }
        self.i += 4;
        Ok(v)
    }

    fn string(&mut self) -> Result<String, JsonError> {
        self.i += 1; // opening quote
        let start = self.i;
        // fast path: no escapes
        while let Some(&c) = self.b.get(self.i) {
            match c {
                b'"' => {
                    let s = std::str::from_utf8(&self.b[start..self.i])
                        .map_err(|_| self.err("not UTF-8"))?
                        .to_owned();
                    self.i += 1;
                    return Ok(s);
                }
                b'\\' => break,
                0..=0x1f => return Err(self.err("control character in string")),
                _ => self.i += 1,
            }
        }
        let mut out: Vec<u8> = self.b[start..self.i].to_vec();
        loop {
            let c = *self
                .b
                .get(self.i)
                .ok_or_else(|| self.err("unterminated string"))?;
            match c {
                b'"' => {
                    self.i += 1;
                    return String::from_utf8(out).map_err(|_| self.err("not UTF-8"));
                }
                b'\\' => {
                    self.i += 1;
                    let e = *self.b.get(self.i).ok_or_else(|| self.err("bad escape"))?;
                    self.i += 1;
                    let ch: char = match e {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{8}',
                        b'f' => '\u{c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => {
                            let u = self.hex4()?;
                            if (0xD800..0xDC00).contains(&u) {
                                // must be followed by a low surrogate escape
                                if !self.b[self.i..].starts_with(b"\\u") {
                                    return Err(JsonError::Canonical);
                                }
                                self.i += 2;
                                let lo = self.hex4()?;
                                if !(0xDC00..0xE000).contains(&lo) {
                                    return Err(JsonError::Canonical);
                                }
                                let cp = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
                                char::from_u32(cp).ok_or(JsonError::Canonical)?
                            } else if (0xDC00..0xE000).contains(&u) {
                                return Err(JsonError::Canonical);
                            } else {
                                char::from_u32(u).ok_or(JsonError::Canonical)?
                            }
                        }
                        _ => return Err(self.err("bad escape")),
                    };
                    let mut buf = [0u8; 4];
                    out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                }
                0..=0x1f => return Err(self.err("control character in string")),
                _ => {
                    out.push(c);
                    self.i += 1;
                }
            }
        }
    }

    fn number(&mut self) -> Result<Value, JsonError> {
        let start = self.i;
        if self.b[self.i] == b'-' {
            self.i += 1;
        }
        let digits = |p: &mut Self| {
            let s = p.i;
            while matches!(p.b.get(p.i), Some(b'0'..=b'9')) {
                p.i += 1;
            }
            p.i - s
        };
        let int_start = self.i;
        let n = digits(self);
        if n == 0 {
            return Err(self.err("expected digit"));
        }
        if n > 1 && self.b[int_start] == b'0' {
            return Err(self.err("leading zero"));
        }
        let mut is_int = true;
        if self.b.get(self.i) == Some(&b'.') {
            is_int = false;
            self.i += 1;
            if digits(self) == 0 {
                return Err(self.err("expected digit after '.'"));
            }
        }
        if matches!(self.b.get(self.i), Some(b'e' | b'E')) {
            is_int = false;
            self.i += 1;
            if matches!(self.b.get(self.i), Some(b'+' | b'-')) {
                self.i += 1;
            }
            if digits(self) == 0 {
                return Err(self.err("expected exponent digit"));
            }
        }
        let text = std::str::from_utf8(&self.b[start..self.i]).expect("ascii");
        if is_int {
            if let Some(v) = text
                .parse::<i64>()
                .ok()
                .filter(|v| v.abs() <= MAX_SAFE_INTEGER)
            {
                // -0 is an integer literal whose value is zero
                return Ok(Value::Number(Number::from(v)));
            }
            if self.mode == Mode::CanonicalForm {
                let f: f64 = text.parse().map_err(|_| self.err("bad number"))?;
                if format_ecmascript(f).ok().as_deref() == Some(text) {
                    return Ok(Value::Number(Number::from_f64(f).expect("finite")));
                }
            }
            Err(JsonError::Canonical)
        } else {
            let f: f64 = text.parse().map_err(|_| self.err("bad number"))?;
            Number::from_f64(f)
                .map(Value::Number)
                .ok_or(JsonError::Canonical)
        }
    }
}

/// RFC 8785 canonical form of a value.
pub fn canonical(v: &Value) -> Result<String, JsonError> {
    let mut out = String::with_capacity(128);
    write_canonical(v, &mut out)?;
    Ok(out)
}

/// Append the canonical form of `v` to `out`.
pub fn write_canonical(v: &Value, out: &mut String) -> Result<(), JsonError> {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => write_number(n, out)?,
        Value::String(s) => write_string(s, out),
        Value::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(x, out)?;
            }
            out.push(']');
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort_by(|a, b| cmp_utf16(a, b));
            out.push('{');
            for (i, k) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_string(k, out);
                out.push(':');
                write_canonical(&m[k.as_str()], out)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

/// Order of two strings by UTF-16 code units (JCS key order).
pub fn cmp_utf16(a: &str, b: &str) -> std::cmp::Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{c}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_number(n: &Number, out: &mut String) -> Result<(), JsonError> {
    if let Some(i) = n.as_i64() {
        if i.abs() > MAX_SAFE_INTEGER {
            return Err(JsonError::Canonical);
        }
        let _ = write!(out, "{i}");
        return Ok(());
    }
    if n.is_u64() {
        return Err(JsonError::Canonical); // above i64::MAX, certainly unsafe
    }
    let f = n.as_f64().ok_or(JsonError::Canonical)?;
    out.push_str(&format_ecmascript(f)?);
    Ok(())
}

/// ECMAScript `Number.prototype.toString` for a finite double.
pub fn format_ecmascript(f: f64) -> Result<String, JsonError> {
    if !f.is_finite() {
        return Err(JsonError::Canonical);
    }
    if f == 0.0 {
        return Ok("0".into());
    }
    let sign = if f < 0.0 { "-" } else { "" };
    // Rust's `{:e}` without precision prints the shortest digits that round-trip.
    let e = format!("{:e}", f.abs());
    let (mant, exp) = e.split_once('e').expect("exponent form");
    let exp: i32 = exp.parse().expect("exponent");
    let mut digits: String = mant.chars().filter(|c| *c != '.').collect();
    while digits.len() > 1 && digits.ends_with('0') {
        digits.pop();
    }
    let k = digits.len() as i32;
    let n = exp + 1; // value = 0.d1d2… × 10^n
    let s = if k <= n && n <= 21 {
        let mut s = digits.clone();
        s.extend(std::iter::repeat_n('0', (n - k) as usize));
        s
    } else if 0 < n && n <= 21 {
        format!("{}.{}", &digits[..n as usize], &digits[n as usize..])
    } else if -6 < n && n <= 0 {
        format!("0.{}{}", "0".repeat((-n) as usize), digits)
    } else {
        let e = n - 1;
        let es = if e >= 0 {
            format!("+{e}")
        } else {
            format!("-{}", -e)
        };
        if k == 1 {
            format!("{digits}e{es}")
        } else {
            format!("{}.{}e{es}", &digits[..1], &digits[1..])
        }
    };
    Ok(format!("{sign}{s}"))
}

/// Two values are equal under the canonical form (so `1` equals `1.0`).
pub fn canon_eq(a: &Value, b: &Value) -> bool {
    match (canonical(a), canonical(b)) {
        (Ok(x), Ok(y)) => x == y,
        _ => false,
    }
}
