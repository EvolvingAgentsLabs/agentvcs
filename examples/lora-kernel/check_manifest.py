#!/usr/bin/env python3
"""STATIC gate for a lora-kernel edge/Mac manifest: no model is loaded or run.

    AGENTVCS_MANIFEST_FILE=merged.json python check_manifest.py      # as `gate run` / `merge commit --suite` call it
    python check_manifest.py manifest.json

Prints {"metrics": {...}, "failures": [...]}; each check is 1 (holds) or 0:

  wellformed           the 12B lane's dimensions exist with their kinds (serve.model, spec.drafter, spec.sampling)
  adapters_hashed      every adapter dimension carries adapter_id, sha256 (64 hex), source, and
                       weights_hash == hash({"sha256": sha256}) (import_lk.py's definition)
  drafter_consistent   a drafter adapter names the drafter it was trained on (== spec.drafter.id), is aligned to
                       the expert serve.adapter serves, and is switched with it; the expert was trained on the
                       family serve.model serves; a `switch_with` names a dimension that exists
  k_in_measured_range  spec.sampling.draft_tokens is an integer inside the range measured for this configuration
  greedy               temperature 0 (every speed number imported here was measured greedy)

The measured ranges (lora-kernel results, read when this gate was written):
  expert active + aligned drafter adapter: k = 1 only. DRAFT0 projects k = 1; its chained drafts read the
      drafter's own post_projection, which DRAFT0 did not train (DRAFT0 BRIEF, "What it does not answer").
  expert active, stock drafter: k = 1..3 (MLXK0 swept draft_block_size 2,3,4 with the LoRA on).
  expert inactive or absent: k = 1..3 (MLXK0 on the base; HOTL0 k = 1,2).
"""

from __future__ import annotations

import json
import os
import re
import sys

MEASURED_K = {"aligned": {1}, "expert": {1, 2, 3}, "base": {1, 2, 3}}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
B3 = re.compile(r"^b3:[0-9a-f]{64}$")


def family(model_id: str):
    m = re.search(r"gemma-4-([0-9a-z]+?)-it", model_id or "", re.I)
    return m.group(1).upper() if m else None


def weights_hash_of(sha: str):
    try:
        import agentvcs
    except ImportError:
        return None
    return agentvcs.hash_json({"sha256": sha})


def check(m: dict) -> dict:
    d = m.get("dimensions", {})
    content = lambda name: (d.get(name) or {}).get("content") or {}  # noqa: E731
    fails: list[str] = []

    def need(ok: bool, why: str) -> int:
        if not ok:
            fails.append(why)
        return int(ok)

    wellformed = min([need(d.get(n, {}).get("kind") == k, f"{n} missing or not kind {k}")
                      for n, k in (("serve.model", "model"), ("spec.drafter", "model"), ("spec.sampling", "sampling"))])

    hashed = 1
    for name, dim in sorted(d.items()):
        if dim.get("kind") != "adapter":
            continue
        c = dim.get("content") or {}
        ok = (bool(c.get("adapter_id")) and bool(c.get("source")) and HEX64.match(str(c.get("sha256", "")))
              and B3.match(str(c.get("weights_hash", ""))))
        if ok:
            expect = weights_hash_of(c["sha256"])
            ok = expect is not None and c["weights_hash"] == expect
        hashed = min(hashed, need(bool(ok), f"{name}: adapter_id, source, sha256 and weights_hash = "
                                            f"hash({{sha256}}) required"))

    expert = d.get("serve.adapter")
    ex = content("serve.adapter")
    da = d.get("spec.drafter_adapter")
    dc = content("spec.drafter_adapter")
    consistent = 1
    if expert:
        consistent = min(consistent, need(family(ex.get("trained_on")) == family(content("serve.model").get("id")),
                                          "serve.adapter was trained on another model family than serve.model"))
        if "switch_with" in ex:
            consistent = min(consistent, need(ex["switch_with"] in d,
                                              f"serve.adapter switches with {ex['switch_with']}, which is absent"))
    if da:
        consistent = min(consistent, need(dc.get("base") == content("spec.drafter").get("id"),
                                          "spec.drafter_adapter was trained on another drafter than spec.drafter"))
        consistent = min(consistent, need(bool(expert) and dc.get("aligned_to") == ex.get("adapter_id"),
                                          "spec.drafter_adapter is aligned to an expert serve.adapter does not serve"))
        consistent = min(consistent, need(dc.get("active_with") == "serve.adapter",
                                          "spec.drafter_adapter must be switched with serve.adapter"))

    expert_active = bool(expert) and ex.get("active", True) is not False
    config = "aligned" if (expert_active and da) else ("expert" if expert_active else "base")
    k = content("spec.sampling").get("draft_tokens")
    in_range = need(isinstance(k, int) and not isinstance(k, bool) and k in MEASURED_K[config],
                    f"draft_tokens={k!r} outside the range measured for '{config}': {sorted(MEASURED_K[config])}")
    greedy = need(content("spec.sampling").get("temperature") == 0, "temperature must be 0")

    metrics = {"wellformed": wellformed, "adapters_hashed": hashed, "drafter_consistent": consistent,
               "k_in_measured_range": in_range, "greedy": greedy}
    metrics["checks_failed"] = sum(1 for v in metrics.values() if v == 0)
    return {"metrics": metrics, "failures": fails,
            "configuration": {"expert_active": expert_active, "drafter_adapter": bool(da), "draft_tokens": k,
                              "measured_k": sorted(MEASURED_K[config])}}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else os.environ.get("AGENTVCS_MANIFEST_FILE")
    if not path:
        print("usage: check_manifest.py <manifest.json> (or set AGENTVCS_MANIFEST_FILE)", file=sys.stderr)
        return 2
    with open(path) as fh:
        print(json.dumps(check(json.load(fh))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
