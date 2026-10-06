//! Canonical JSON (RFC 8785) and BLAKE3 hashing against published vectors.

use agentvcs_core::hash::{b3_bytes, hash_value};
use agentvcs_core::json::{canonical, parse, parse_with, JsonError, Mode};

fn canon(s: &str) -> String {
    canonical(&parse(s).expect("parse")).expect("canonical")
}

#[test]
fn blake3_empty_vector() {
    assert_eq!(
        b3_bytes(b""),
        "b3:af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    );
}

#[test]
fn rfc8785_example() {
    let input = r#"{
  "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
  "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/",
  "literals": [null, true, false]
}"#;
    assert_eq!(
        canon(input),
        "{\"literals\":[null,true,false],\"numbers\":[333333333.3333333,1e+30,4.5,0.002,1e-27],\"string\":\"€$\\u000f\\nA'B\\\"\\\\\\\\\\\"/\"}"
    );
}

#[test]
fn rfc8785_sorting_by_utf16() {
    let input = r#"{"\u20ac":"Euro Sign","\r":"Carriage Return","\ufb33":"Hebrew","1":"One","\ud83d\ude00":"Emoji","\u0080":"Control","\u00f6":"o"}"#;
    assert_eq!(
        canon(input),
        "{\"\\r\":\"Carriage Return\",\"1\":\"One\",\"\u{80}\":\"Control\",\"ö\":\"o\",\"€\":\"Euro Sign\",\"😀\":\"Emoji\",\"\u{fb33}\":\"Hebrew\"}"
    );
}

#[test]
fn ecmascript_numbers() {
    assert_eq!(canon("[0, -0, 0.0, -0.0]"), "[0,0,0,0]");
    assert_eq!(
        canon("[1e20, 1e21, 1e23]"),
        "[100000000000000000000,1e+21,1e+23]"
    );
    assert_eq!(
        canon("[0.000001, 1e-7, 0.002, 5e-324]"),
        "[0.000001,1e-7,0.002,5e-324]"
    );
    assert_eq!(
        canon("[1.7976931348623157e308, 9007199254740991, -9007199254740991, -1.5]"),
        "[1.7976931348623157e+308,9007199254740991,-9007199254740991,-1.5]"
    );
    assert_eq!(
        canon("[2.9514790517935283e20, 1.2345678901234567e19]"),
        "[295147905179352830000,12345678901234567000]"
    );
    assert_eq!(
        canon("[0.30000000000000004, 1.0, 4.50, 100]"),
        "[0.30000000000000004,1,4.5,100]"
    );
}

#[test]
fn control_characters() {
    assert_eq!(
        canon(r#"["\b\t\n\f\r\u0001\u001F\u007f/"]"#),
        "[\"\\b\\t\\n\\f\\r\\u0001\\u001f\u{7f}/\"]"
    );
}

#[test]
fn key_order_and_escapes_hash_equal() {
    let a = hash_value(&parse(r#"{"a":"é","b":[1,2,{"x":null,"y":true}]}"#).unwrap()).unwrap();
    let b = hash_value(&parse(r#"{"b":[1,2.0,{"y":true,"x":null}],"a":"é"}"#).unwrap()).unwrap();
    let c = hash_value(&parse(r#"{"b":[1,2,{"x":null,"y":true}],"a":"\u00e9"}"#).unwrap()).unwrap();
    assert_eq!(a, b);
    assert_eq!(a, c);
    assert_eq!(
        a,
        "b3:af64c4be9611c15c3059db79ec8c703c3cd8e932136973c22f7a44b472364760"
    );
}

#[test]
fn lone_surrogate_is_canonical_error() {
    assert_eq!(parse(r#"{"a":"\ud800"}"#), Err(JsonError::Canonical));
    assert_eq!(parse(r#""\udc00x""#), Err(JsonError::Canonical));
    assert_eq!(parse(r#""\ud800\u0041""#), Err(JsonError::Canonical));
}

#[test]
fn unsafe_integer_is_canonical_error() {
    assert_eq!(
        parse(r#"{"seed": 9007199254740993}"#),
        Err(JsonError::Canonical)
    );
    assert_eq!(parse("-9007199254740992"), Err(JsonError::Canonical));
    // a float literal of the same magnitude is fine: it is a double by construction
    assert!(parse("9007199254740993.0").is_ok());
}

#[test]
fn non_finite_is_canonical_error() {
    assert_eq!(parse("[NaN]"), Err(JsonError::Canonical));
    assert_eq!(parse("[Infinity]"), Err(JsonError::Canonical));
    assert_eq!(parse("[-Infinity]"), Err(JsonError::Canonical));
    assert_eq!(parse("[1e400]"), Err(JsonError::Canonical));
}

#[test]
fn malformed_is_syntax_error() {
    for bad in [
        "",
        "{",
        "[1,]",
        "{\"a\" 1}",
        "01",
        "1.",
        "\"\\x\"",
        "[1] 2",
        "tru",
    ] {
        assert!(
            matches!(parse(bad), Err(JsonError::Syntax(_))),
            "{bad:?} should be a syntax error"
        );
    }
}

#[test]
fn integer_literals_stay_integers() {
    let v = parse("[1, 1.0, -5, 2e0]").unwrap();
    let a = v.as_array().unwrap();
    assert!(a[0].is_i64());
    assert!(a[1].is_f64());
    assert!(a[2].is_i64());
    assert!(a[3].is_f64());
}

/// Spec bug recorded in ADR-0006 §1: the canonical form of 1e20 is an integer
/// literal above 2^53 - 1, which the spec's own rule refuses on re-parse.
#[test]
fn canonical_form_of_large_doubles_is_not_strictly_reparseable() {
    let c = canon("[1e20, 2.9514790517935283e20]");
    assert_eq!(c, "[100000000000000000000,295147905179352830000]");
    assert_eq!(parse(&c), Err(JsonError::Canonical));
    let v = parse_with(&c, Mode::CanonicalForm).unwrap();
    assert_eq!(canonical(&v).unwrap(), c);
    // ...while a literal that would be silently rounded is still refused
    assert_eq!(
        parse_with("9007199254740993", Mode::CanonicalForm),
        Err(JsonError::Canonical)
    );
}
