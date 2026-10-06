use agentvcs_diff::{field_diff, lcs_len, pointer_escape};
use serde_json::json;

#[test]
fn lcs_counts() {
    let a: Vec<&str> = "a\nb\nc".split('\n').collect();
    let b: Vec<&str> = "a\nx\nc\nd".split('\n').collect();
    assert_eq!(lcs_len(&a, &b), 2);
    assert_eq!(lcs_len::<&str>(&[], &b), 0);
}

#[test]
fn pointer_escaping() {
    assert_eq!(pointer_escape("a/b~c"), "a~1b~0c");
}

#[test]
fn field_diff_leaves_and_sorting() {
    let d = field_diff(
        &json!({"b": 1, "a": {"x": [1, 2], "y": 1.0}, "z": {"k": 1}}),
        &json!({"b": 2, "a": {"x": [1, 3], "y": 1}, "z": 5, "n": true}),
    );
    let paths: Vec<&str> = d.iter().map(|c| c["path"].as_str().unwrap()).collect();
    assert_eq!(paths, ["/a/x", "/b", "/n", "/z"]);
    assert_eq!(d[2], json!({"path": "/n", "op": "added", "to": true}));
    assert_eq!(d[3]["op"], "changed");
}
