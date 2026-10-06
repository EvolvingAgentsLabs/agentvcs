"""Reference functions used ONLY to generate golden cases.

This is not an implementation of agentvcs. It computes ids, diffs, verdicts and
blame segments so gen.py can write them into case files. Verdicts that a case
asserts (which violation, which op) are declared by hand in gen.py; this module
must agree with them or generation fails. External vectors (RFC 8785, BLAKE3)
in gen.py were not produced by this module.

Requires: blake3 (pip). Tooling dependency only.
"""
from __future__ import annotations

import copy
import json
import math
from decimal import Decimal

import blake3

PROTOCOL = "agentvcs/0.1"
KINDS = ("prompt", "model", "sampling", "tool", "adapter", "router", "config")


# ---------------------------------------------------------------- canonical form

class CanonicalError(ValueError):
    pass


def _num(x) -> str:
    if isinstance(x, bool):
        raise TypeError
    if isinstance(x, int) and abs(x) > 2**53 - 1 and _num(float(x)) != str(x):
        raise CanonicalError("integer outside the IEEE-754 safe range that is not a canonical double")
    f = float(x)
    if math.isnan(f) or math.isinf(f):
        raise CanonicalError("non-finite number")
    if f == 0:
        return "0"
    sign = "-" if f < 0 else ""
    _, dg, ex = Decimal(repr(abs(f))).as_tuple()  # repr = shortest round-trip digits
    digits = "".join(map(str, dg))
    stripped = digits.rstrip("0")
    ex += len(digits) - len(stripped)
    digits = stripped.lstrip("0")
    n = len(digits) + ex  # value = 0.digits * 10^n, ECMAScript's n
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        s = digits + "e" + es if k == 1 else digits[0] + "." + digits[1:] + "e" + es
    return sign + s


def _str(s: str) -> str:
    for ch in s:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise CanonicalError("lone surrogate")
    return json.dumps(s, ensure_ascii=False)


def jcs(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return _num(v)
    if isinstance(v, str):
        return _str(v)
    if isinstance(v, list):
        return "[" + ",".join(jcs(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted(v, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_str(k) + ":" + jcs(v[k]) for k in keys) + "}"
    raise TypeError(type(v))


def b3_bytes(b: bytes) -> str:
    return "b3:" + blake3.blake3(b).hexdigest()


def h(v) -> str:
    return b3_bytes(jcs(v).encode("utf-8"))


def ckey(s: str):
    return s.encode("utf-16-be")


# ---------------------------------------------------------------- manifests

def normalize_manifest(m: dict) -> dict:
    """Fill content hashes and manifest_id. Raises ValueError(code) if stated ones are wrong."""
    m = copy.deepcopy(m)
    if m.get("protocol") != PROTOCOL:
        raise ValueError("E_PROTOCOL_VERSION")
    for name, d in m["dimensions"].items():
        if d.get("kind") not in KINDS:
            raise ValueError("E_UNKNOWN_KIND")
        ch = h(d["content"])
        if "content_hash" in d and d["content_hash"] != ch:
            raise ValueError("E_CONTENT_HASH")
        d["content_hash"] = ch
    mid = manifest_id(m)
    if "manifest_id" in m and m["manifest_id"] != mid:
        raise ValueError("E_MANIFEST_ID")
    m["manifest_id"] = mid
    return m


def manifest_id(m: dict) -> str:
    dims = {}
    for name, d in m["dimensions"].items():
        dd = {k: v for k, v in d.items()}
        dd.setdefault("content_hash", h(d["content"]))
        dims[name] = dd
    return h({"protocol": m["protocol"], "dimensions": dims})


# ---------------------------------------------------------------- diff

def field_diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=ckey):
            p = path + "/" + k.replace("~", "~0").replace("/", "~1")
            if k not in b:
                out.append({"path": p, "op": "removed", "from": a[k]})
            elif k not in a:
                out.append({"path": p, "op": "added", "to": b[k]})
            else:
                out.extend(field_diff(a[k], b[k], p))
    elif jcs(a) != jcs(b):
        out.append({"path": path, "op": "changed", "from": a, "to": b})
    return sorted(out, key=lambda c: ckey(c["path"]))


def lcs_len(x, y) -> int:
    prev = [0] * (len(y) + 1)
    for xi in x:
        cur = [0]
        for j, yj in enumerate(y):
            cur.append(prev[j] + 1 if xi == yj else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _details(kind, a, b):
    if kind == "prompt":
        ta, tb = a["template"], b["template"]
        if ta == tb:
            tmpl = None
        else:
            la, lb = ta.split("\n"), tb.split("\n")
            L = lcs_len(la, lb)
            tmpl = {"lines_added": len(lb) - L, "lines_removed": len(la) - L}
        va, vb = set(a.get("variables", [])), set(b.get("variables", []))
        rest = lambda c: {k: v for k, v in c.items() if k not in ("template", "variables")}
        return {"template": tmpl, "variables_added": sorted(vb - va, key=ckey),
                "variables_removed": sorted(va - vb, key=ckey), "fields": field_diff(rest(a), rest(b))}
    d = {"fields": field_diff(a, b)}
    if kind == "tool":
        d["code_changed"] = a.get("code_hash") != b.get("code_hash")
        d["signature_changed"] = jcs(a.get("signature")) != jcs(b.get("signature"))
    if kind == "adapter":
        d["weights_changed"] = a.get("weights_hash") != b.get("weights_hash")
    return d


def diff(A: dict, B: dict) -> dict:
    A, B = normalize_manifest(A), normalize_manifest(B)
    da, db = A["dimensions"], B["dimensions"]
    changes = []
    for name in sorted(set(da) | set(db), key=ckey):
        if name not in db:
            changes.append({"dimension": name, "kind": da[name]["kind"], "op": "removed",
                            "details": {"content_hash": da[name]["content_hash"]}})
        elif name not in da:
            changes.append({"dimension": name, "kind": db[name]["kind"], "op": "added",
                            "details": {"content_hash": db[name]["content_hash"]}})
        elif da[name]["content_hash"] == db[name]["content_hash"] and da[name]["kind"] == db[name]["kind"]:
            continue
        elif da[name]["kind"] != db[name]["kind"]:
            changes.append({"dimension": name, "kind": db[name]["kind"], "op": "kind_changed",
                            "details": {"from_kind": da[name]["kind"], "to_kind": db[name]["kind"],
                                        "from_hash": da[name]["content_hash"], "to_hash": db[name]["content_hash"]}})
        else:
            k = da[name]["kind"]
            changes.append({"dimension": name, "kind": k, "op": "modified",
                            "details": _details(k, da[name]["content"], db[name]["content"])})
    return {"from": A["manifest_id"], "to": B["manifest_id"], "identical": not changes, "changes": changes}


# ---------------------------------------------------------------- ledger

def entry_hash(e: dict) -> str:
    return h({k: v for k, v in e.items() if k != "entry_hash"})


def patch_id(body: dict) -> str:
    return h({"protocol": PROTOCOL, **{k: body[k] for k in
              ("from_manifest", "to_manifest", "rationale", "evidence", "author", "rollback_of")}})


def gate_passes(g: dict) -> bool:
    if not g["thresholds"]:
        return False
    ops = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
           "<": lambda a, b: a < b, "==": lambda a, b: a == b}
    for m, t in g["thresholds"].items():
        if m not in g["metrics"] or not ops[t["op"]](g["metrics"][m], t["value"]):
            return False
    return True


def _schema_ok(e) -> bool:
    req = ("protocol", "type", "run_id", "seq", "prev_hash", "kind", "body", "entry_hash")
    if not isinstance(e, dict) or set(e) != set(req) or e["type"] != "ledger_entry":
        return False
    need = {"run_start": ("manifest_id", "started_at", "parent"),
            "step": ("step_index", "manifest_id", "agent_id", "inputs", "outputs", "started_at",
                     "ended_at", "tokens", "latency_ms", "checkpoint_ref"),
            "patch": ("patch_id", "from_manifest", "to_manifest", "semantic_diff", "rationale",
                      "evidence", "author", "applied_at_step", "rollback_of", "gate_result"),
            "run_end": ("ended_at", "status")}
    if e["kind"] not in need or not isinstance(e["body"], dict):
        return False
    return all(k in e["body"] for k in need[e["kind"]])


def verify(bundle: dict) -> dict:
    v = []
    for key in sorted(bundle["manifests"], key=ckey):
        m = bundle["manifests"][key]
        try:
            n = normalize_manifest(m)
        except ValueError as ex:
            v.append({"code": str(ex), "manifest_id": key})
            continue
        if n["manifest_id"] != key:
            v.append({"code": "E_MANIFEST_KEY", "manifest_id": key})
    led = bundle["ledger"]
    active = None
    next_step = 0
    ended = False
    patches = {}
    for i, e in enumerate(led):
        def bad(code):
            v.append({"code": code, "seq": i})
        if not _schema_ok(e):
            bad("E_SCHEMA"); continue
        if e["protocol"] != PROTOCOL:
            bad("E_PROTOCOL_VERSION"); continue
        if e["run_id"] != bundle["run_id"]:
            bad("E_RUN_ID")
        if e["seq"] != i:
            bad("E_SEQ")
        exp_prev = None if i == 0 else led[i - 1].get("entry_hash")
        if e["prev_hash"] != exp_prev:
            bad("E_PREV_HASH")
        if e["entry_hash"] != entry_hash(e):
            bad("E_ENTRY_HASH")
        k, b = e["kind"], e["body"]
        if i == 0 and k != "run_start":
            bad("E_FIRST_NOT_RUN_START")
        if i > 0 and k == "run_start":
            bad("E_DUPLICATE_RUN_START")
        if ended:
            bad("E_AFTER_RUN_END")
        named = [b.get(x) for x in ("manifest_id", "from_manifest", "to_manifest") if x in b]
        if any(x not in bundle["manifests"] for x in named):
            bad("E_UNKNOWN_MANIFEST")
        if k == "run_start":
            active = b["manifest_id"]
            next_step = b["parent"]["from_step"] if b["parent"] else 0
        elif k == "step":
            if b["step_index"] != next_step:
                bad("E_STEP_INDEX")
            if b["manifest_id"] != active:
                bad("E_STEP_MANIFEST")
            next_step = b["step_index"] + 1
        elif k == "patch":
            if b["from_manifest"] == b["to_manifest"]:
                bad("E_PATCH_NOOP")
            if b["patch_id"] != patch_id(b):
                bad("E_PATCH_ID")
            if b["from_manifest"] != active:
                bad("E_PATCH_FROM")
            if b["applied_at_step"] != next_step:
                bad("E_PATCH_STEP")
            g = b["gate_result"]
            if b["rollback_of"] is not None:
                orig = patches.get(b["rollback_of"])
                if orig is None:
                    bad("E_ROLLBACK_UNKNOWN")
                elif (orig["from_manifest"], orig["to_manifest"]) != (b["to_manifest"], b["from_manifest"]):
                    bad("E_ROLLBACK_TARGET")
            elif g is None or not g["passed"]:
                bad("E_PATCH_UNGATED")
            if g is not None and g["passed"] != gate_passes(g):
                bad("E_GATE_INCONSISTENT")
            M = bundle["manifests"]
            if b["from_manifest"] in M and b["to_manifest"] in M:
                if jcs(b["semantic_diff"]) != jcs(diff(M[b["from_manifest"]], M[b["to_manifest"]])["changes"]):
                    bad("E_PATCH_DIFF")
            patches[b["patch_id"]] = b
            active = b["to_manifest"]
        elif k == "run_end":
            ended = True
    return {"ok": True, "valid": not v, "entries": len(led), "open": not ended, "violations": v}


def blame(bundle: dict, metric: str) -> dict:
    if not verify(bundle)["valid"]:
        return {"ok": False, "error": {"code": "E_INVALID_LEDGER"}}
    segs, pending = [], []
    for e in bundle["ledger"]:
        b = e["body"]
        if e["kind"] == "patch":
            pending.append(b["patch_id"])
        elif e["kind"] == "step":
            if segs and segs[-1]["manifest_id"] == b["manifest_id"] and not pending:
                s = segs[-1]
            else:
                s = {"manifest_id": b["manifest_id"], "from_step": b["step_index"], "to_step": b["step_index"],
                     "_vals": [], "introduced_by": pending if segs else []}
                segs.append(s)
                pending = []
            s["to_step"] = b["step_index"]
            if metric in b.get("metrics", {}):
                s["_vals"].append(b["metrics"][metric])
    for s in segs:
        vals = s.pop("_vals")
        s["n"] = len(vals)
        s["mean"] = sum(vals) / len(vals) if vals else None
    attr = []
    for i in range(1, len(segs)):
        a, c = segs[i - 1]["mean"], segs[i]["mean"]
        attr.append({"patches": segs[i]["introduced_by"], "from_segment": i - 1, "to_segment": i,
                     "delta": None if a is None or c is None else c - a})
    return {"ok": True, "metric": metric, "segments": segs, "attributions": attr}
