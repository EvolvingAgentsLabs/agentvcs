//! Property tests for canonicalization (Gate F1 item 3).

use agentvcs_core::json::{canonical, format_ecmascript, parse_with, Mode};
use proptest::prelude::*;
use serde_json::{Map, Number, Value};

fn arb_value() -> impl Strategy<Value = Value> {
    let leaf = prop_oneof![
        Just(Value::Null),
        any::<bool>().prop_map(Value::Bool),
        (-9_007_199_254_740_991i64..=9_007_199_254_740_991i64)
            .prop_map(|i| Value::Number(i.into())),
        any::<f64>()
            .prop_filter("finite", |f| f.is_finite())
            .prop_map(|f| Value::Number(Number::from_f64(f).unwrap())),
        "\\PC{0,12}".prop_map(Value::String),
        any::<String>().prop_map(Value::String),
    ];
    leaf.prop_recursive(4, 48, 6, |inner| {
        prop_oneof![
            prop::collection::vec(inner.clone(), 0..6).prop_map(Value::Array),
            prop::collection::vec((any::<String>(), inner), 0..6)
                .prop_map(|kv| Value::Object(kv.into_iter().collect::<Map<_, _>>())),
        ]
    })
}

fn reversed(v: &Value) -> Value {
    match v {
        Value::Object(m) => {
            let mut out = Map::new();
            for (k, x) in m.iter().rev() {
                out.insert(k.clone(), reversed(x));
            }
            Value::Object(out)
        }
        Value::Array(a) => Value::Array(a.iter().map(reversed).collect()),
        x => x.clone(),
    }
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(2000))]

    #[test]
    fn key_order_invariance(v in arb_value()) {
        prop_assert_eq!(canonical(&v).unwrap(), canonical(&reversed(&v)).unwrap());
    }

    #[test]
    fn idempotence(v in arb_value()) {
        let c = canonical(&v).unwrap();
        let again = canonical(&parse_with(&c, Mode::CanonicalForm).unwrap()).unwrap();
        prop_assert_eq!(c, again);
    }

    #[test]
    fn finite_floats_round_trip(f in any::<f64>().prop_filter("finite", |f| f.is_finite())) {
        let s = format_ecmascript(f).unwrap();
        let back: f64 = s.parse().unwrap();
        // -0 canonicalizes to 0, which is the same value
        prop_assert!(back == f, "{} -> {} -> {}", f, s, back);
        // and through the JSON parser too
        let v = parse_with(&s, Mode::CanonicalForm).unwrap();
        prop_assert!(v.as_f64().unwrap() == f);
    }
}
