import json, os, sys

TABLE = {
 "b3:c2cbbb2956e53dc3ab707d2d11b66a9b9f25010ee382b6ed08e25d0a2cb9d023": 0.9,
 "b3:460db309ecd68bda3d06faac9d3974db1327935546de701ac5c385ceb43a77c8": 0.9,
 "b3:4e466361435092735eac2c6e7147ecf93cfba29b42effd0c6a9311d628d97570": 0.88,
 "b3:ed6da2b1546b6b7a1dad81a99dd9cbf6c3b7709e50a155f2e05c0f25c27bd133": 0.91,
 "b3:a0ddd7d70ce38a3e1751b29df11265770934a04ad434952bd4b640fb844e49d4": 0.3,
 "b3:a7524bb2f6d552f2e099d2acbd9e5323ce95018cde74a0232fc28876bf18e28c": 0.25,
 "b3:b2d98e2a74128116fdd6a74bc6e367316194ebfc497d3d657d82fbefda9016ee": 0.2
}
EXPECT = {
 "AGENTVCS_RUN": "run-conformance",
 "AGENTVCS_METRIC": "f1",
 "AGENTVCS_FROM_STEP": "2",
 "AGENTVCS_CHECKPOINT_REF": "ckpt/1"
}
FORM = 'none'


def main():
    env = os.environ
    for k, v in EXPECT.items():
        if env.get(k) != v:
            print(f"{k}={env.get(k)!r}, expected {v!r}", file=sys.stderr)
            return 7
    mid = env["AGENTVCS_MANIFEST"]
    with open(env["AGENTVCS_MANIFEST_FILE"], encoding="utf-8") as f:
        if json.load(f).get("manifest_id") != mid:
            print("AGENTVCS_MANIFEST_FILE is not the candidate", file=sys.stderr)
            return 8
    x = TABLE[mid]
    if FORM == "none":
        print(json.dumps({"note": "no metric here"}))
    elif FORM == "text":
        print("metric is", x)
    elif FORM == "fail":
        return 1
    else:
        print(json.dumps(x if FORM == "bare" else {"metrics": {"f1": x}} if FORM == "metrics" else {"f1": x}))
    return 0


sys.exit(main())
