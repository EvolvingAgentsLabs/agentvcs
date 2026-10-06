"""Generate conformance/cases/ from the declarations below.

Each case declares by hand what it asserts (exit code, error code, first
violation, diff op). ref.py fills in hashes and must agree with every declared
verdict, or generation aborts. Run:  python conformance/tools/gen.py
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import ref
from ref import PROTOCOL, h

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"
B3 = lambda s: ref.b3_bytes(s.encode())  # stable fake hashes for code/weights/blobs

cases: list[dict] = []


def case(cid, group, desc, argv, files, expect, source="generated"):
    cases.append({"id": cid, "group": group, "description": desc, "source": source,
                  "argv": argv, "files": files, "expect": expect})


def jtext(v) -> str:
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


# ======================================================================= hash
case("hash-001-blake3-empty", "hash", "BLAKE3 of empty input, published vector",
     ["hash", "empty.bin"], {"empty.bin": ""},
     {"exit": 0, "json": {"ok": True, "hash": "b3:af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"}},
     source="BLAKE3 spec test vector (input length 0)")

# Escapes are assembled from BS so no editor or tool can decode them in this file.
BS = "\\"
U = BS + "u"
RFC_322_IN = ('{\n  "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],\n'
              '  "string": "' + U + '20ac$' + U + '000F' + U + "000aA'" + U + '0042' + U + '0022' + U + '005c'
              + BS + BS + BS + '"' + BS + '/",\n  "literals": [null, true, false]\n}\n')
RFC_322_OUT = ('{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"'
               + chr(0x20AC) + '$' + U + '000f' + BS + "nA'B" + BS + '"' + BS + BS + BS + BS + BS + '"/"}')
case("hash-002-rfc8785-example", "hash", "RFC 8785 §3.2.2 canonicalization example",
     ["hash", "--canonical", "in.json"], {"in.json": RFC_322_IN},
     {"exit": 0, "json": {"ok": True, "canonical": RFC_322_OUT, "hash": B3(RFC_322_OUT)}},
     source="RFC 8785 §3.2.2")

_sort_keys = [(U + "20ac", "Euro Sign"), (BS + "r", "Carriage Return"), (U + "fb33", "Hebrew Letter Dalet With Dagesh"),
              ("1", "One"), (U + "d83d" + U + "de00", "Emoji: Grinning Face"), (U + "0080", "Control"),
              (U + "00f6", "Latin Small Letter O With Diaeresis")]
RFC_SORT_IN = "{\n" + ",\n".join(f'  "{k}": "{v}"' for k, v in _sort_keys) + "\n}\n"
RFC_SORT_OUT = ('{"' + BS + 'r":"Carriage Return","1":"One","' + chr(0x80) + '":"Control","' + chr(0xF6)
                + '":"Latin Small Letter O With Diaeresis","' + chr(0x20AC) + '":"Euro Sign","' + chr(0x1F600)
                + '":"Emoji: Grinning Face","' + chr(0xFB33) + '":"Hebrew Letter Dalet With Dagesh"}')
case("hash-003-rfc8785-sorting", "hash", "keys sort by UTF-16 code units (emoji before U+FB33)",
     ["hash", "--canonical", "in.json"], {"in.json": RFC_SORT_IN},
     {"exit": 0, "json": {"ok": True, "canonical": RFC_SORT_OUT}}, source="RFC 8785 §3.2.3")

NUMS = [
    ("hash-004-num-zero", "[0, -0, 0.0, -0.0]", "[0,0,0,0]"),
    ("hash-005-num-1e21-boundary", "[1e20, 1e21, 1e23]", "[100000000000000000000,1e+21,1e+23]"),
    ("hash-006-num-small", "[0.000001, 1e-7, 0.002, 5e-324]", "[0.000001,1e-7,0.002,5e-324]"),
    ("hash-007-num-extremes", "[1.7976931348623157e308, 9007199254740991, -9007199254740991, -1.5]",
     "[1.7976931348623157e+308,9007199254740991,-9007199254740991,-1.5]"),
    ("hash-008-num-float-beyond-2p53", "[2.9514790517935283e20, 1.2345678901234567e19]",
     "[295147905179352830000,12345678901234567000]"),
    ("hash-009-num-shortest", "[0.30000000000000004, 1.0, 4.50, 100]", "[0.30000000000000004,1,4.5,100]"),
]
for cid, src, out in NUMS:
    assert ref.jcs(json.loads(src)) == out, (cid, ref.jcs(json.loads(src)))
    case(cid, "hash", "ECMAScript Number serialization", ["hash", "--canonical", "in.json"], {"in.json": src + "\n"},
         {"exit": 0, "json": {"ok": True, "canonical": out}}, source="ECMA-262 Number::toString via RFC 8785 §3.2.2.3")

INV = {"b": [1, 2, {"y": True, "x": None}], "a": "é"}
inv_hash = h(INV)
case("hash-010-key-order-a", "hash", "key order does not change the hash (1/3)", ["hash", "--canonical", "in.json"],
     {"in.json": '{"a":"é","b":[1,2,{"x":null,"y":true}]}'}, {"exit": 0, "json": {"ok": True, "hash": inv_hash}})
case("hash-011-key-order-b", "hash", "key order does not change the hash (2/3)", ["hash", "--canonical", "in.json"],
     {"in.json": '{\n  "b": [1, 2.0, {"y": true, "x": null}],\n  "a": "é"\n}\n'}, {"exit": 0, "json": {"ok": True, "hash": inv_hash}})
case("hash-012-escape-forms", "hash", "\\u00e9 escape and literal é hash the same (3/3)", ["hash", "--canonical", "in.json"],
     {"in.json": '{"b":[1,2,{"x":null,"y":true}],"a":"\\u00e9"}'}, {"exit": 0, "json": {"ok": True, "hash": inv_hash}})
case("hash-015-int-beyond-safe-range", "hash", "an integer literal above 2^53-1 is refused, not rounded",
     ["hash", "--canonical", "in.json"], {"in.json": '{"seed": 9007199254740993}'}, {"exit": 3, "json": {"ok": False}})
case("hash-013-lone-surrogate", "hash", "a lone surrogate cannot be canonicalized", ["hash", "--canonical", "in.json"],
     {"in.json": '{"a":"\\ud800"}'}, {"exit": 3, "json": {"ok": False}})
case("hash-014-control-chars", "hash", "control characters: named escapes and lowercase \\u00xx",
     ["hash", "--canonical", "in.json"], {"in.json": '["\\b\\t\\n\\f\\r\\u0001\\u001F\\u007f/"]'},
     {"exit": 0, "json": {"ok": True, "canonical": '["\\b\\t\\n\\f\\r\\u0001\\u001f\x7f/"]'}})
assert ref.jcs(json.loads('["\\b\\t\\n\\f\\r\\u0001\\u001F\\u007f/"]')) == '["\\b\\t\\n\\f\\r\\u0001\\u001f\x7f/"]'


# =================================================================== manifests
def dim(kind, content):
    return {"kind": kind, "content": content}


FULL = {
    "protocol": PROTOCOL, "type": "harness_manifest", "name": "due-diligence v1",
    "dimensions": {
        "extract.prompt": dim("prompt", {"template": "Find every {clause} clause.\nQuote it verbatim.", "variables": ["clause"]}),
        "extract.model": dim("model", {"provider": "llama.cpp", "id": "gemma-4-12b", "quantization": "Q4_K_M"}),
        "extract.sampling": dim("sampling", {"temperature": 0.2, "top_p": 0.95, "max_tokens": 512, "grammar": None}),
        "segment.tool": dim("tool", {"name": "split_sections", "signature": {"type": "object", "properties": {"doc": {"type": "string"}}},
                                     "code_hash": B3("def split_sections(doc): ...")}),
        "extract.adapter": dim("adapter", {"adapter_id": "cuad-lora-r16", "weights_hash": B3("weights-v1")}),
        "route": dim("router", {"rules": [{"if": "len(doc) > 40000", "then": "extract.long"}]}),
        "run.config": dim("config", {"value": {"batch": 4, "docs": 120}}),
    },
}
EMPTY = {"protocol": PROTOCOL, "type": "harness_manifest", "dimensions": {}}


def filled(m):
    return ref.normalize_manifest(m)


def snap_expect(m):
    n = filled(m)
    return {"exit": 0, "json": {"ok": True, "manifest_id": n["manifest_id"],
                                "dimensions": {k: d["content_hash"] for k, d in n["dimensions"].items()}}}


def bad_snap(cid, desc, m, code):
    try:
        ref.normalize_manifest(m)
        got = None
    except ValueError as ex:
        got = str(ex)
    except (KeyError, TypeError):
        got = "E_SCHEMA"
    if code != "E_SCHEMA":
        assert got == code, (cid, got)
    case(cid, "manifest", desc, ["snapshot", "m.json"], {"m.json": jtext(m)},
         {"exit": 3, "json": {"ok": False, "error": {"code": code}}})


case("manifest-001-empty", "manifest", "zero dimensions is a valid manifest", ["snapshot", "m.json"],
     {"m.json": jtext(EMPTY)}, snap_expect(EMPTY))
case("manifest-002-all-kinds-authoring", "manifest", "all seven kinds, hashes omitted (authoring form)",
     ["snapshot", "m.json"], {"m.json": jtext(FULL)}, snap_expect(FULL))
case("manifest-003-all-kinds-filled", "manifest", "same manifest with hashes and id filled in: same id",
     ["snapshot", "m.json"], {"m.json": jtext(filled(FULL))}, snap_expect(FULL))
annot = copy.deepcopy(FULL); annot["name"] = "renamed"; annot["parent_ids"] = [filled(EMPTY)["manifest_id"]]
assert filled(annot)["manifest_id"] == filled(FULL)["manifest_id"]
case("manifest-004-annotations-excluded", "manifest", "name and parent_ids are not part of the id (ADR-0005)",
     ["snapshot", "m.json"], {"m.json": jtext(annot)}, snap_expect(FULL))
one = copy.deepcopy(FULL); one["dimensions"]["extract.sampling"]["content"]["temperature"] = 1
onef = copy.deepcopy(FULL); onef["dimensions"]["extract.sampling"]["content"]["temperature"] = 1.0
txt_onef = jtext(onef).replace('"temperature": 1,', '"temperature": 1.0,')
assert '"temperature": 1.0' in txt_onef
case("manifest-005-int-float-same", "manifest", "temperature 1.0 and 1 give the same id",
     ["snapshot", "m.json"], {"m.json": txt_onef}, snap_expect(one))
reord = {"dimensions": dict(reversed(list(FULL["dimensions"].items()))), "type": "harness_manifest", "protocol": PROTOCOL}
case("manifest-006-dimension-order", "manifest", "dimension order in the file does not matter",
     ["snapshot", "m.json"], {"m.json": jtext(reord)}, snap_expect(FULL))

wrong_ch = filled(FULL); wrong_ch["dimensions"]["extract.model"]["content_hash"] = B3("nope")
bad_snap("manifest-007-wrong-content-hash", "stated content_hash does not match content", wrong_ch, "E_CONTENT_HASH")
wrong_id = filled(FULL); wrong_id["manifest_id"] = B3("nope")
bad_snap("manifest-008-wrong-manifest-id", "stated manifest_id does not match", wrong_id, "E_MANIFEST_ID")
uk = copy.deepcopy(FULL); uk["dimensions"]["x"] = dim("embedding", {"id": "e5"})
bad_snap("manifest-009-unknown-kind", "kind outside the v0.1 set", uk, "E_UNKNOWN_KIND")
pv = copy.deepcopy(FULL); pv["protocol"] = "agentvcs/0.2"
bad_snap("manifest-010-protocol-version", "unknown protocol version", pv, "E_PROTOCOL_VERSION")
bn = copy.deepcopy(EMPTY); bn["dimensions"]["Extract Prompt"] = dim("prompt", {"template": "x"})
bad_snap("manifest-011-bad-dimension-name", "dimension names are lowercase slugs", bn, "E_SCHEMA")
nt = copy.deepcopy(EMPTY); nt["dimensions"]["t"] = dim("tool", {"name": "f", "signature": {}})
bad_snap("manifest-012-tool-without-code-hash", "tool content must carry code_hash", nt, "E_SCHEMA")
np_ = copy.deepcopy(EMPTY); np_["dimensions"]["p"] = dim("prompt", {"variables": []})
bad_snap("manifest-013-prompt-without-template", "prompt content must carry template", np_, "E_SCHEMA")


# ======================================================================== diff
def variant(base, edits):
    m = copy.deepcopy(base)
    for path, val in edits:
        cur = m["dimensions"]
        *head, last = path
        for p in head:
            cur = cur[p]
        if val is DEL:
            del cur[last]
        else:
            cur[last] = val
    return m


DEL = object()


def diff_case(cid, desc, a, b, expect_ops):
    d = ref.diff(a, b)
    ops = [(c["dimension"], c["op"]) for c in d["changes"]]
    assert ops == expect_ops, (cid, ops)
    case(cid, "diff", desc, ["diff", "a.json", "b.json"], {"a.json": jtext(a), "b.json": jtext(b)},
         {"exit": 0, "json": {"ok": True, **d}})


diff_case("diff-001-identical", "identical manifests", FULL, filled(FULL), [])
diff_case("diff-002-prompt-lines-vars", "prompt: one line rewritten, one appended, variable added",
          FULL, variant(FULL, [(("extract.prompt", "content", "template"),
                                "Find every {clause} clause.\nQuote it verbatim with {cap_amount}.\nCite the section."),
                               (("extract.prompt", "content", "variables"), ["clause", "cap_amount"])]),
          [("extract.prompt", "modified")])
diff_case("diff-003-prompt-trailing-newline", "a trailing newline is one added (empty) line",
          FULL, variant(FULL, [(("extract.prompt", "content", "template"), "Find every {clause} clause.\nQuote it verbatim.\n")]),
          [("extract.prompt", "modified")])
diff_case("diff-004-prompt-other-field", "prompt: template equal, extra field changed → template null",
          FULL, variant(FULL, [(("extract.prompt", "content", "system"), "You are a paralegal.")]),
          [("extract.prompt", "modified")])
diff_case("diff-005-sampling-fields", "sampling: temperature changed, grammar set, top_p removed",
          FULL, variant(FULL, [(("extract.sampling", "content", "temperature"), 0.0),
                               (("extract.sampling", "content", "grammar"), 'root ::= "yes" | "no"'),
                               (("extract.sampling", "content", "top_p"), DEL)]),
          [("extract.sampling", "modified")])
diff_case("diff-006-sampling-int-float", "temperature 1 vs 1.0 is no change",
          variant(FULL, [(("extract.sampling", "content", "temperature"), 1)]),
          variant(FULL, [(("extract.sampling", "content", "temperature"), 1.0)]), [])
diff_case("diff-007-model-quantization", "model: quantization changed",
          FULL, variant(FULL, [(("extract.model", "content", "quantization"), "Q8_0")]), [("extract.model", "modified")])
diff_case("diff-008-tool-code-only", "tool: code changed, signature unchanged",
          FULL, variant(FULL, [(("segment.tool", "content", "code_hash"), B3("def split_sections(doc, max_len=40000): ..."))]),
          [("segment.tool", "modified")])
diff_case("diff-009-tool-signature", "tool: signature gained a parameter",
          FULL, variant(FULL, [(("segment.tool", "content", "signature", "properties", "max_len"), {"type": "integer"})]),
          [("segment.tool", "modified")])
diff_case("diff-010-adapter-weights", "adapter: new weights, same id",
          FULL, variant(FULL, [(("extract.adapter", "content", "weights_hash"), B3("weights-v2"))]), [("extract.adapter", "modified")])
diff_case("diff-011-added-removed", "a dimension added and another removed",
          FULL, variant(FULL, [(("route",), DEL), (("verify.prompt",), dim("prompt", {"template": "Check: {x}", "variables": ["x"]}))]),
          [("route", "removed"), ("verify.prompt", "added")])
diff_case("diff-012-kind-changed", "same name, different kind",
          FULL, variant(FULL, [(("route",), dim("config", {"rules": []}))]), [("route", "kind_changed")])
diff_case("diff-013-pointer-escaping", "config keys with / and ~ are escaped in JSON Pointer",
          variant(FULL, [(("run.config", "content", "value"), {"a/b": 1, "m~n": {"k": 1}})]),
          variant(FULL, [(("run.config", "content", "value"), {"a/b": 2, "m~n": {"k": 2}})]), [("run.config", "modified")])
diff_case("diff-014-array-is-leaf", "arrays compare as whole values",
          FULL, variant(FULL, [(("route", "content", "rules"), [{"if": "len(doc) > 60000", "then": "extract.long"}])]),
          [("route", "modified")])
diff_case("diff-015-many-sorted", "several dimensions change; output sorted by name",
          FULL, variant(FULL, [(("run.config", "content", "value", "batch"), 8),
                               (("extract.model", "content", "id"), "gemma-4-26b"),
                               (("segment.tool", "content", "name"), "split")]),
          [("extract.model", "modified"), ("run.config", "modified"), ("segment.tool", "modified")])
diff_case("diff-016-empty-to-full", "from zero dimensions to seven", EMPTY, FULL,
          [(n, "added") for n in sorted(FULL["dimensions"], key=ref.ckey)])


# ====================================================================== ledger
M0 = filled(FULL)
M1 = filled(variant(FULL, [(("extract.prompt", "content", "template"),
                            "Find every {clause} clause.\nQuote it verbatim, including any cap amount.")]))
M2 = filled(variant(FULL, [(("extract.sampling", "content", "temperature"), 0.0),
                           (("extract.sampling", "content", "grammar"), 'root ::= clause+')]))
MAN = {m["manifest_id"]: m for m in (M0, M1, M2)}
RUN = "run-conformance"


def gate(passed=True, f1=0.71, thr=0.65):
    return {"suite": "cuad-smoke", "suite_hash": B3("suite: cuad-smoke"), "metrics": {"f1.macro": f1},
            "thresholds": {"f1.macro": {"op": ">=", "value": thr}}, "passed": passed, "evidence": []}


class L:
    """Ledger builder that chains correctly unless told otherwise."""

    def __init__(self, manifest=M0, parent=None):
        self.entries = []
        self.active = manifest["manifest_id"]
        self.next = parent["from_step"] if parent else 0
        self.add("run_start", {"manifest_id": self.active, "started_at": "2026-10-06T12:00:00Z", "parent": parent})

    def add(self, kind, body):
        e = {"protocol": PROTOCOL, "type": "ledger_entry", "run_id": RUN, "seq": len(self.entries),
             "prev_hash": self.entries[-1]["entry_hash"] if self.entries else None, "kind": kind, "body": body}
        e["entry_hash"] = ref.entry_hash(e)
        self.entries.append(e)
        return self

    def step(self, n=1, metric=None, agent="extractor"):
        for _ in range(n):
            i = self.next
            body = {"step_index": i, "manifest_id": self.active, "agent_id": agent, "inputs": [B3(f"in{i}")],
                    "outputs": [B3(f"out{i}")], "started_at": "2026-10-06T12:00:00Z", "ended_at": "2026-10-06T12:00:01Z",
                    "tokens": {"in": 800, "out": 120}, "latency_ms": 1000, "checkpoint_ref": f"ckpt/{i}"}
            if metric is not None:
                body["metrics"] = {"f1": metric(i) if callable(metric) else metric}
            self.add("step", body)
            self.next += 1
        return self

    def patch(self, to, g="ok", rollback_of=None, rationale="fix extraction"):
        frm = self.active
        body = {"from_manifest": frm, "to_manifest": to["manifest_id"],
                "semantic_diff": ref.diff(MAN[frm], to)["changes"] if frm in MAN else [],
                "rationale": rationale, "evidence": [max(self.next - 1, 0)],
                "author": {"type": "agent", "id": "supervisor-v0"}, "applied_at_step": self.next,
                "rollback_of": rollback_of, "gate_result": gate() if g == "ok" else g}
        body["patch_id"] = ref.patch_id(body)
        self.add("patch", body)
        self.active = to["manifest_id"]
        return body["patch_id"]

    def end(self, status="completed"):
        return self.add("run_end", {"ended_at": "2026-10-06T13:00:00Z", "status": status})

    def bundle(self, manifests=None):
        return {"protocol": PROTOCOL, "type": "audit_bundle", "run_id": RUN,
                "manifests": manifests if manifests is not None else MAN, "ledger": self.entries}


def rehash(b, i):
    e = b["ledger"][i]
    e["entry_hash"] = ref.entry_hash(e)


def verify_case(cid, desc, b, first=None, valid=None, open_=None):
    r = ref.verify(b)
    got = r["violations"][0] if r["violations"] else None
    assert got == first, (cid, got, r["violations"][:3])
    exp = {"ok": True, "valid": first is None, "entries": len(b["ledger"])}
    if open_ is not None:
        exp["open"] = open_
    expect = {"exit": 0 if first is None else 1, "json": exp}
    if first:
        expect["first_violation"] = first
    case(cid, "verify", desc, ["verify", "bundle.json"], {"bundle.json": jtext(b)}, expect)


verify_case("verify-001-minimal", "run_start, three steps, run_end", L().step(3).end().bundle(), open_=False)
l = L().step(3); l.patch(M1); l.step(3).end()
verify_case("verify-002-gated-patch", "a gated patch between steps", l.bundle())
l = L().step(2); p = l.patch(M1); l.step(2); l.patch(M0, g=None, rollback_of=p); l.step(2).end()
verify_case("verify-003-rollback-ungated", "a rollback needs no gate", l.bundle())
verify_case("verify-004-open-run", "no run_end: valid and open", L().step(2).bundle(), open_=True)
verify_case("verify-005-resumed", "child run resumed from step 5 starts at step_index 5",
            L(parent={"run_id": "run-parent", "from_step": 5, "checkpoint_ref": "ckpt/5"}).step(3).end().bundle())
l = L().step(2); l.patch(M1); l.patch(M2); l.step(1).end()
verify_case("verify-006-two-patches-back-to-back", "two patches with no step between", l.bundle())

b = L().step(4).end().bundle(); b["ledger"][2]["prev_hash"] = B3("forged"); rehash(b, 2)
verify_case("verify-007-broken-chain", "prev_hash does not point at the previous entry", b, {"code": "E_PREV_HASH", "seq": 2})
b = L().step(4).end().bundle(); b["ledger"][3]["body"]["tokens"]["out"] = 1
verify_case("verify-008-tampered-body", "body edited after hashing", b, {"code": "E_ENTRY_HASH", "seq": 3})
b = L().step(3).bundle(); b["ledger"][2]["seq"] = 7; rehash(b, 2)
verify_case("verify-009-seq-gap", "seq does not match position", b, {"code": "E_SEQ", "seq": 2})
l = L(); l.entries = []; l.add("step", {**L().step(1).entries[1]["body"]})
verify_case("verify-010-first-not-run-start", "ledger starts with a step", l.bundle(), {"code": "E_FIRST_NOT_RUN_START", "seq": 0})
l = L().step(1); l.add("run_start", l.entries[0]["body"])
verify_case("verify-011-duplicate-run-start", "a second run_start", l.bundle(), {"code": "E_DUPLICATE_RUN_START", "seq": 2})
l = L().step(1).end(); l.step(1)
verify_case("verify-012-after-run-end", "a step after run_end", l.bundle(), {"code": "E_AFTER_RUN_END", "seq": 3})
l = L().step(1); l.active = B3("manifest nobody stored"); l.step(1)
verify_case("verify-013-step-without-manifest", "a step names a manifest not in the bundle", l.bundle(),
            {"code": "E_UNKNOWN_MANIFEST", "seq": 2})
l = L().step(1); l.active = M1["manifest_id"]; l.step(1)
verify_case("verify-014-step-wrong-manifest", "a step runs under a manifest no patch activated", l.bundle(),
            {"code": "E_STEP_MANIFEST", "seq": 2})
l = L().step(1); l.next += 1; l.step(1)
verify_case("verify-015-step-index-skip", "step_index skips one", l.bundle(), {"code": "E_STEP_INDEX", "seq": 2})
l = L().step(1); l.patch(M1, g=None)
verify_case("verify-016-patch-without-gate", "patch with no gate result", l.bundle(), {"code": "E_PATCH_UNGATED", "seq": 2})
l = L().step(1); l.patch(M1, g=gate(passed=False, f1=0.5))
verify_case("verify-017-patch-gate-failed", "patch whose gate failed", l.bundle(), {"code": "E_PATCH_UNGATED", "seq": 2})
l = L().step(1); l.patch(M1, g=gate(passed=True, f1=0.5))
verify_case("verify-018-gate-inconsistent", "gate says passed but its metric is under threshold", l.bundle(),
            {"code": "E_GATE_INCONSISTENT", "seq": 2})
l = L().step(1); l.patch(M1, g={**gate(), "thresholds": {}, "passed": False})
verify_case("verify-019-empty-gate", "a gate with no thresholds never passes", l.bundle(), {"code": "E_PATCH_UNGATED", "seq": 2})
l = L().step(1); l.active = M2["manifest_id"]; l.patch(M1)
verify_case("verify-020-patch-wrong-from", "patch from a manifest that is not active", l.bundle(), {"code": "E_PATCH_FROM", "seq": 2})
l = L().step(2); l.next = 5; l.patch(M1)
verify_case("verify-021-patch-wrong-step", "applied_at_step is not the next step", l.bundle(), {"code": "E_PATCH_STEP", "seq": 3})
b = L().step(1).bundle(); l = L().step(1); l.patch(M1); b = l.bundle(); b["ledger"][2]["body"]["rationale"] = "edited later"; rehash(b, 2)
verify_case("verify-022-patch-id-mismatch", "rationale edited after the patch id was computed", b, {"code": "E_PATCH_ID", "seq": 2})
l = L().step(1); l.patch(M1); b = l.bundle(); b["ledger"][2]["body"]["semantic_diff"] = []; rehash(b, 2)
verify_case("verify-023-patch-diff-mismatch", "semantic_diff does not match the manifests", b, {"code": "E_PATCH_DIFF", "seq": 2})
l = L().step(1); l.patch(M0)
verify_case("verify-024-patch-noop", "patch to the same manifest", l.bundle(), {"code": "E_PATCH_NOOP", "seq": 2})
l = L().step(1); l.patch(M1); l.step(1); l.patch(M0, g=None, rollback_of=B3("no such patch"))
verify_case("verify-025-rollback-unknown", "rollback of a patch not in the ledger", l.bundle(), {"code": "E_ROLLBACK_UNKNOWN", "seq": 4})
l = L().step(1); p = l.patch(M1); l.step(1); l.patch(M2, g=None, rollback_of=p)
verify_case("verify-026-rollback-wrong-target", "rollback that goes somewhere else", l.bundle(), {"code": "E_ROLLBACK_TARGET", "seq": 4})
b = L().step(2).bundle(); b["ledger"][1]["run_id"] = "other-run"; rehash(b, 1)
for i in (2,):
    b["ledger"][i]["prev_hash"] = b["ledger"][i - 1]["entry_hash"]; rehash(b, i)
verify_case("verify-027-run-id-mismatch", "an entry from another run", b, {"code": "E_RUN_ID", "seq": 1})
b = L().step(1).bundle(); b["manifests"] = {**MAN, B3("wrong key"): M1}
verify_case("verify-028-manifest-key", "a manifest stored under the wrong key", b,
            {"code": "E_MANIFEST_KEY", "manifest_id": B3("wrong key")})
bad = copy.deepcopy(M2); bad["dimensions"]["extract.model"]["content"]["id"] = "swapped-after-hashing"
b = L().step(1).bundle({**MAN, M2["manifest_id"]: bad})
first_key = sorted(b["manifests"], key=ref.ckey)
verify_case("verify-029-manifest-tampered", "a manifest's content edited after hashing", b,
            {"code": "E_CONTENT_HASH", "manifest_id": M2["manifest_id"]})
b = L().step(2).bundle(); b["ledger"][2]["protocol"] = "agentvcs/0.2"; rehash(b, 2)
verify_case("verify-030-entry-protocol", "an entry with an unknown protocol", b, {"code": "E_PROTOCOL_VERSION", "seq": 2})
b = L().step(2).bundle(); del b["ledger"][2]["body"]["agent_id"]; rehash(b, 2)
verify_case("verify-031-step-missing-field", "a step without agent_id", b, {"code": "E_SCHEMA", "seq": 2})


# ======================================================================= blame
def blame_case(cid, desc, b, metric="f1", expect_deltas=None, exit_=0):
    r = ref.blame(b, metric)
    if exit_:
        assert not r["ok"]
        case(cid, "blame", desc, ["blame", "bundle.json", "--metric", metric], {"bundle.json": jtext(b)},
             {"exit": exit_, "json": r})
        return
    deltas = [None if a["delta"] is None else round(a["delta"], 9) for a in r["attributions"]]
    assert deltas == expect_deltas, (cid, deltas)
    case(cid, "blame", desc, ["blame", "bundle.json", "--metric", metric], {"bundle.json": jtext(b)},
         {"exit": 0, "json": r})


l = L().step(4, metric=0.4); l.patch(M1); l.step(4, metric=0.7).end()
blame_case("blame-001-one-patch", "one patch, metric rises 0.3", l.bundle(), expect_deltas=[0.3])
l = L().step(3, metric=0.6); p = l.patch(M1); l.step(3, metric=0.2); l.patch(M0, g=None, rollback_of=p); l.step(3, metric=0.6).end()
blame_case("blame-002-regression-rolled-back", "patch regresses, rollback restores (A,B,A)", l.bundle(), expect_deltas=[-0.4, 0.4])
l = L().step(2, metric=0.5); p = l.patch(M1); l.patch(M0, g=None, rollback_of=p); l.step(2, metric=0.5).end()
blame_case("blame-003-patch-and-rollback-adjacent", "patch then rollback with no step between: two segments on one manifest",
           l.bundle(), expect_deltas=[0.0])
l = L().step(3); l.patch(M1); l.step(3, metric=0.8).end()
blame_case("blame-004-missing-metric", "first segment never reports the metric: mean and delta null", l.bundle(), expect_deltas=[None])
l = L().step(2, metric=0.5); l.patch(M1); l.patch(M2); l.step(2, metric=0.9).end()
blame_case("blame-005-joint-attribution", "two patches with no step between are attributed jointly", l.bundle(), expect_deltas=[0.4])
l = L().step(3, metric=lambda i: [0.1, 0.2, 0.6][i]); l.patch(M1); l.step(2, metric=lambda i: [0.3, 0.5][i - 3]); l.patch(M2)
blame_case("blame-006-trailing-patch", "a patch after the last step introduces no segment", l.bundle(), expect_deltas=[0.1])
blame_case("blame-007-other-metric", "asking for a metric no step carries", L().step(2, metric=0.5).end().bundle(),
           metric="latency", expect_deltas=[])
b = L().step(2, metric=0.5).end().bundle(); b["ledger"][1]["body"]["metrics"]["f1"] = 0.99
blame_case("blame-008-invalid-ledger", "blame refuses a ledger that does not verify", b, exit_=3)


# ======================================================================= merge (v0.2 draft)
def mvar(edits):
    return variant(FULL, edits)


TPL = ("extract.prompt", "content", "template")
P_OURS = "Find every {clause} clause.\nQuote it verbatim, including any cap amount."
P_THEIRS = "Find every {clause} clause.\nQuote it verbatim and cite its section."


def prep_case(cid, desc, base, ours, theirs, expect_auto, expect_conf, extra_files=None, extra_argv=(),
              bundles=(None, None), metrics=()):
    r = ref.merge_prepare(base, ours, theirs, *bundles, metrics=metrics)
    auto = [(a["dimension"], a["resolution"]) for a in r["auto"]]
    conf = [(c["dimension"], c["type"]) for c in r["conflicts"]]
    assert auto == expect_auto, (cid, auto)
    assert conf == expect_conf, (cid, conf)
    files = {"base.json": jtext(base), "ours.json": jtext(ours), "theirs.json": jtext(theirs), **(extra_files or {})}
    case(cid, "merge", desc, ["merge", "prepare", "--base", "base.json", "--ours", "ours.json",
                              "--theirs", "theirs.json", *extra_argv], files, {"exit": 0, "json": r})


ALL_SAME = [(d, "same") for d in sorted(FULL["dimensions"], key=ref.ckey)]


def with_res(auto, **over):
    return [(d, over.get(d, r)) for d, r in auto]


prep_case("merge-001-nothing-changed", "no side changed anything", FULL, FULL, FULL, ALL_SAME, [])
prep_case("merge-002-only-theirs", "only theirs changed sampling: taken mechanically", FULL, FULL,
          mvar([(("extract.sampling", "content", "temperature"), 0.0)]),
          with_res(ALL_SAME, **{"extract.sampling": "theirs"}), [])
prep_case("merge-003-only-ours", "only ours changed the prompt: taken mechanically", FULL,
          mvar([(TPL, P_OURS)]), FULL, with_res(ALL_SAME, **{"extract.prompt": "ours"}), [])
prep_case("merge-004-same-change", "both sides made the same change", FULL, mvar([(TPL, P_OURS)]),
          mvar([(TPL, P_OURS)]), ALL_SAME, [])
prep_case("merge-005-modify-modify", "both sides rewrote the same prompt differently: conflict", FULL,
          mvar([(TPL, P_OURS)]), mvar([(TPL, P_THEIRS)]),
          [a for a in ALL_SAME if a[0] != "extract.prompt"], [("extract.prompt", "modify/modify")])
prep_case("merge-006-modify-delete", "ours modified a dimension theirs deleted", FULL,
          mvar([(("route", "content", "rules"), [])]), mvar([(("route",), DEL)]),
          [a for a in ALL_SAME if a[0] != "route"], [("route", "modify/delete")])
prep_case("merge-007-delete-modify", "ours deleted a dimension theirs modified", FULL,
          mvar([(("route",), DEL)]), mvar([(("route", "content", "rules"), [])]),
          [a for a in ALL_SAME if a[0] != "route"], [("route", "delete/modify")])
prep_case("merge-008-add-add", "both sides added the same name with different content", FULL,
          mvar([(("verify.prompt",), dim("prompt", {"template": "Check {x}", "variables": ["x"]}))]),
          mvar([(("verify.prompt",), dim("prompt", {"template": "Verify {x} twice", "variables": ["x"]}))]),
          ALL_SAME, [("verify.prompt", "add/add")])
prep_case("merge-009-add-and-delete-mechanical", "theirs adds a dimension, ours deletes another: both mechanical",
          FULL, mvar([(("route",), DEL)]),
          mvar([(("verify.prompt",), dim("prompt", {"template": "Check {x}", "variables": ["x"]}))]),
          sorted(with_res(ALL_SAME, route="ours") + [("verify.prompt", "theirs")], key=lambda a: ref.ckey(a[0])), [])
prep_case("merge-010-kind-change-one-side", "one side changed a dimension's kind: mechanical", FULL,
          FULL, mvar([(("route",), dim("config", {"rules": []}))]), with_res(ALL_SAME, route="theirs"), [])

# evidence: ours is a run whose gated patch M0 -> M1 rewrote extract.prompt and raised f1
l = L().step(4, metric=0.4); P_EV = l.patch(M1); l.step(4, metric=0.8).end()
EV_BUNDLE = l.bundle()
THEIRS_EV = variant(FULL, [(TPL, P_THEIRS)])
prep_case("merge-011-evidence-from-run", "conflict evidence lists the run's patch that touched the dimension, its gate and blame delta",
          M0, M1, THEIRS_EV, [a for a in ALL_SAME if a[0] != "extract.prompt"], [("extract.prompt", "modify/modify")],
          extra_files={"ours-run.json": jtext(EV_BUNDLE)}, extra_argv=("--ours-run", "ours-run.json", "--metric", "f1"),
          bundles=(EV_BUNDLE, None), metrics=("f1",))
_ev = ref.merge_prepare(M0, M1, THEIRS_EV, EV_BUNDLE, None, metrics=("f1",))["conflicts"][0]["evidence"]["ours"]
assert [e["patch_id"] for e in _ev] == [P_EV] and round(_ev[0]["blame"]["f1"], 9) == 0.4 and _ev[0]["gate"]["passed"]

# commit
B5, O5, T5 = FULL, mvar([(TPL, P_OURS)]), mvar([(TPL, P_THEIRS)])
MID5 = ref.merge_prepare(B5, O5, T5)["merge_id"]


def resolution(mid, res, rationale="kept ours: it is the one that was gated"):
    return {"protocol": PROTOCOL, "type": "merge_resolution", "merge_id": mid, "resolutions": res,
            "rationale": rationale, "author": {"type": "agent", "id": "claude-code"}}


def commit_case(cid, desc, base, ours, theirs, res, code=None):
    exit_, out = ref.merge_commit(base, ours, theirs, res)
    got = out.get("error", {}).get("code")
    assert got == code, (cid, got)
    files = {"base.json": jtext(base), "ours.json": jtext(ours), "theirs.json": jtext(theirs), "res.json": jtext(res)}
    case(cid, "merge", desc, ["merge", "commit", "--base", "base.json", "--ours", "ours.json", "--theirs",
                              "theirs.json", "--resolution", "res.json"], files,
         {"exit": exit_, "json": out if code is None else {"ok": False, "error": {"code": code}}})


commit_case("merge-012-commit-take-ours", "resolve by taking ours; merged id and record are deterministic",
            B5, O5, T5, resolution(MID5, {"extract.prompt": {"take": "ours"}}))
commit_case("merge-013-commit-synthesis", "resolve with new content combining both sides",
            B5, O5, T5, resolution(MID5, {"extract.prompt": {"kind": "prompt", "content": {
                "template": "Find every {clause} clause.\nQuote it verbatim, including any cap amount, and cite its section.",
                "variables": ["clause"]}}}, "both fixes are independent; combined them"))
commit_case("merge-014-commit-unresolved", "a conflict left without a resolution", B5, O5, T5,
            resolution(MID5, {}), "E_MERGE_UNRESOLVED")
commit_case("merge-015-commit-extra", "a resolution for a dimension that did not conflict", B5, O5, T5,
            resolution(MID5, {"extract.prompt": {"take": "ours"}, "extract.model": {"take": "theirs"}}), "E_MERGE_EXTRA")
commit_case("merge-016-commit-stale", "resolution written for another merge", B5, O5, T5,
            resolution(B3("other merge"), {"extract.prompt": {"take": "ours"}}), "E_MERGE_STALE")
B6, O6, T6 = FULL, mvar([(("route",), DEL)]), mvar([(("route", "content", "rules"), [])])
MID6 = ref.merge_prepare(B6, O6, T6)["merge_id"]
commit_case("merge-017-commit-take-deleted-side", "take ours on a dimension ours deleted (use delete)",
            B6, O6, T6, resolution(MID6, {"route": {"take": "ours"}}), "E_MERGE_TAKE")
commit_case("merge-018-commit-delete", "resolve delete/modify by deleting", B6, O6, T6,
            resolution(MID6, {"route": {"take": "delete"}}))
commit_case("merge-019-commit-invalid-content", "synthesised content that is not a valid prompt", B5, O5, T5,
            resolution(MID5, {"extract.prompt": {"kind": "prompt", "content": {"variables": []}}}), "E_SCHEMA")


# ======================================================================= write
def main():
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case id"
    if CASES.exists():
        shutil.rmtree(CASES)
    for c in cases:
        d = CASES / c["id"]
        d.mkdir(parents=True)
        for name, text in c.pop("files").items():
            (d / name).write_text(text, encoding="utf-8")
        (d / "case.json").write_text(jtext(c), encoding="utf-8")
    by = {}
    for c in cases:
        by[c["group"]] = by.get(c["group"], 0) + 1
    print(json.dumps({"cases": len(cases), "by_group": by}))


if __name__ == "__main__":
    sys.exit(main())
