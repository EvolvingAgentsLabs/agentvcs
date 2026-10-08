#!/usr/bin/env python3
"""Build the HarnessManifest of lora-kernel's edge/Mac stack from a lora-kernel checkout.

    python import_lk.py --lk ~/evolvingagents/lora-kernel -o manifest.json [--facts facts.json]

The checkout is only read (lkread.Reader): code is parsed with `ast`, never imported
or run, and no model is loaded. The manifest describes the configuration as of the
fork point of this demo (2026-10-06): the 12B lane on MLX (base + expert LoRA + MTP
drafter, as `examples/mac/mlx_spec_lora.py` runs it) and the library endpoint on
llama.cpp (`examples/library/serve.py` behind `training/harness/openai_proxy.py`).

Dimensions (spec/PROTOCOL.md §2.1 kinds), each value with its source in `facts`:

  serve.model      model    the 12B base MLX serves
  spec.drafter     model    Gemma 4's MTP drafter
  serve.adapter    adapter  the expert LoRA (wiki12b-walks-s0, B3)
  spec.sampling    sampling greedy, temperature 0, max_tokens, draft length k (null = the drafter's default)
  library.model    model    the E4B llama-server serves (docs/SERVING.md)
  library.adapter  adapter  the library member (real-none-s0, REAL4)
  library.config   config   serve.py's served defaults: cite gate, page top, page budget, guard
  route.router     router   the proxy's router and the tracker member it routes to
  member.prompt    prompt   the members' system prompt, by reference: source + sha256, never its text
  member.sampling  sampling the proxy's per-member cap and thinking switch

`weights_hash` (required by the adapter kind, `b3:`): agentvcs never sees the weights,
so it is `hash({"sha256": <hex>})` — BLAKE3 over the JCS of the sha256 lora-kernel
recorded for the adapter's files (`adapter_sha256` in the results file that trained
it). Where no sha256 was recorded (the DRAFT0 drafter adapter), <hex> is the sha256 of
the bytes of the results file that records the adapter, and `sha256_of` says so.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lkread import Reader  # noqa: E402

PROTOCOL = "agentvcs/0.1"

MLX_RUNNER = "examples/mac/mlx_spec_lora.py"
LLAMACPP_RUNNER = "examples/mac/llamacpp_spec_lora.py"
SERVE = "examples/library/serve.py"
PROXY = "training/harness/openai_proxy.py"
PROMPT = "memory/prompt.py"
SERVING = "docs/SERVING.md"
R = "results/"
B3_TRAIN = R + "B3-gemma4-large-member-20260926/train_12b.json"
REAL4_TRAIN = R + "REAL4-refusal-20260930/train_none_s0.json"
ROUTE1_TRAIN = R + "ROUTE1-tracker-abstain-20261003/train_tr_out.json"
H3_TRAIN = R + "H3-tracker-corpus-v2-20260929/train_tr_s1.json"
DRAFT0 = R + "DRAFT0-aligned-drafter-20261006/"
MLXK0_BRIEF = R + "MLXK0-mac-mlx-mtp-ceiling-20261005/BRIEF.md"
SPECK0_BRIEF = R + "SPECK0-mac-mtp-k-20261005/BRIEF.md"


def hash_json(v) -> str:
    import agentvcs  # the SDK: BLAKE3 over JCS, as the protocol defines hash()
    return agentvcs.hash_json(v)


def weights_hash(sha_hex: str) -> str:
    return hash_json({"sha256": sha_hex})


def base_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def extract(lk) -> dict:
    """Every value the manifests need, each as {"value": v, "source": "path#locator"}."""
    r = lk if isinstance(lk, Reader) else Reader(lk)
    f: dict = {}

    def put(name, vs):
        v, src = vs
        f[name] = {"value": v, "source": src}

    # the 12B lane, as the MLX runner serves it
    put("mlx.base", r.const(MLX_RUNNER, "BASE"))
    put("mlx.drafter", r.const(MLX_RUNNER, "DRAFTER"))
    put("mlx.max_tokens", r.argdefault(MLX_RUNNER, "--max-tokens"))
    put("mlx.block_sizes", r.argdefault(MLX_RUNNER, "--block-sizes"))
    put("mlx.engine", r.regex(MLXK0_BRIEF, r"(mlx-vlm \d+\.\d+\.\d+)"))
    put("mlx.prompt", r.regex(MLX_RUNNER, r"prompt\.(SYSTEM_\w+)"))
    put("mlx.temperature", r.regex(MLX_RUNNER, r'"temperature": (\d+\.\d+)'))
    # ... and as llama.cpp ran it before SPECK0 moved speculation to MLX
    files, src = r.const(LLAMACPP_RUNNER, "FILES")
    f["llamacpp.target"] = {"value": files["target"], "source": src + '["target"]'}
    f["llamacpp.mtp"] = {"value": files["mtp"], "source": src + '["mtp"]'}
    put("llamacpp.k_default", r.regex(SPECK0_BRIEF, r"default `--spec-draft-n-max` is (\d+)"))
    # the expert (B3) and the drafter's adapter (DRAFT0)
    put("expert.adapter", r.json(B3_TRAIN, "members", "withlib-s0", "adapter"))
    put("expert.sha256", r.json(B3_TRAIN, "members", "withlib-s0", "adapter_sha256"))
    put("expert.trained_on", r.json(B3_TRAIN, "base"))
    put("drafter_adapter.adapter", r.regex(DRAFT0 + "BRIEF.md", r"\(`(adapters/drafter-[a-z0-9-]+)`"))
    put("drafter_adapter.record_sha256", r.sha256_file(DRAFT0 + "draft0.json"))
    put("drafter_adapter.drafter", r.json(DRAFT0 + "draft0.json", "drafter"))
    put("drafter_adapter.target_lora", r.json(DRAFT0 + "draft0.json", "target_lora"))
    put("drafter_adapter.r", r.json(DRAFT0 + "draft0.json", "train", "r"))
    put("drafter_adapter.targets", r.json(DRAFT0 + "draft0.json", "train", "targets"))
    # the library endpoint on llama.cpp
    line, src = r.regex(SERVING, r"llama-server -m \S+ --lora lora-real-none-s0\S* .*?-c \d+", 0)
    m = re.match(r"llama-server -m (\S+) --lora (\S+) .*?-c (\d+)", line)
    f["library.gguf"] = {"value": m.group(1), "source": src}
    f["library.lora_gguf"] = {"value": m.group(2), "source": src}
    f["library.context"] = {"value": int(m.group(3)), "source": src}
    put("library.tokenizer", r.argdefault(SERVE, "--tokenizer"))
    put("library.prompt", r.regex(SERVE, r"prompt\.(SYSTEM_\w+)"))
    put("library.adapter", r.json(REAL4_TRAIN, "members", "withlib-s0", "adapter"))
    put("library.sha256", r.json(REAL4_TRAIN, "members", "withlib-s0", "adapter_sha256"))
    put("library.trained_on", r.json(REAL4_TRAIN, "base"))
    for flag in ("--cite-gate", "--page-top", "--guard", "--page-budget"):
        put("library." + flag[2:].replace("-", "_"), r.argdefault(SERVE, flag))
    # the proxy: router, tracker member, per-member sampling
    put("route.router", r.argdefault(PROXY, "--router"))
    put("route.role_policy", r.argdefault(PROXY, "--role-policy"))
    put("route.tracker_adapter", r.json(ROUTE1_TRAIN, "member", "adapter"))
    put("route.tracker_sha256", r.json(ROUTE1_TRAIN, "member", "adapter_sha256"))
    put("route.tracker_prev_adapter", r.json(H3_TRAIN, "member", "adapter"))
    put("route.tracker_prev_sha256", r.json(H3_TRAIN, "member", "adapter_sha256"))
    put("member.max_tokens", r.const(PROXY, "MEMBER_MAX_TOKENS"))
    put("member.thinking", r.regex(PROXY, r'setdefault\("enable_thinking", (False|True)\)'))
    # the prompt, by reference
    if f["mlx.prompt"]["value"] != f["library.prompt"]["value"]:
        raise SystemExit("the MLX runner and the library endpoint use different prompts; one member.prompt cannot hold both")
    sha, n, src = r.sha256_const(PROMPT, f["mlx.prompt"]["value"])
    f["prompt.sha256"] = {"value": sha, "source": f"sha256(utf-8 of {src})"}
    f["prompt.chars"] = {"value": n, "source": f"len({src})"}
    f["prompt.ref"] = {"value": src, "source": f"{MLX_RUNNER} and {SERVE} pass prompt.{f['mlx.prompt']['value']}"}
    return f


def v(f, name):
    return f[name]["value"]


def adapter(adapter_id, sha, sha_of, source, **extra) -> dict:
    return {"adapter_id": adapter_id, "weights_hash": weights_hash(sha), "sha256": sha,
            "sha256_of": sha_of, "source": source, **extra}


def dims_at_fork(f: dict) -> dict:
    """The fork-point configuration (the demo's common base)."""
    k = None if v(f, "mlx.block_sizes") == "" else v(f, "mlx.block_sizes")
    return {
        "serve.model": {"kind": "model", "content": {
            "provider": "mlx-vlm", "id": v(f, "mlx.base"), "quantization": "4bit",
            "engine": v(f, "mlx.engine"), "source": f["mlx.base"]["source"]}},
        "spec.drafter": {"kind": "model", "content": {
            "provider": "mlx-vlm", "id": v(f, "mlx.drafter"), "method": "mtp",
            "source": f["mlx.drafter"]["source"]}},
        "serve.adapter": {"kind": "adapter", "content": adapter(
            base_name(v(f, "expert.adapter")), v(f, "expert.sha256"), "adapter files (recorded at training)",
            f["expert.sha256"]["source"], trained_on=v(f, "expert.trained_on"), active=True)},
        "spec.sampling": {"kind": "sampling", "content": {
            "temperature": float(v(f, "mlx.temperature")), "greedy": True, "max_tokens": v(f, "mlx.max_tokens"),
            # k = draft_block_size - 1; null = the drafter's default block size (the runner's --block-sizes "")
            "draft_tokens": k}},
        "library.model": {"kind": "model", "content": {
            "provider": "llama.cpp", "id": v(f, "library.tokenizer"), "file": v(f, "library.gguf"),
            "quantization": "Q8_0", "context": v(f, "library.context"), "source": f["library.gguf"]["source"]}},
        "library.adapter": {"kind": "adapter", "content": adapter(
            base_name(v(f, "library.adapter")), v(f, "library.sha256"), "adapter files (recorded at training)",
            f["library.sha256"]["source"], trained_on=v(f, "library.trained_on"), file=v(f, "library.lora_gguf"))},
        "library.config": {"kind": "config", "content": {
            "cite_gate": v(f, "library.cite_gate"), "page_top": v(f, "library.page_top"),
            "page_budget": v(f, "library.page_budget"), "guard": v(f, "library.guard"),
            "strip_openclaw_envelope": True, "source": "examples/library/serve.py argparse defaults"}},
        "route.router": {"kind": "router", "content": {
            "router": v(f, "route.router"), "role_policy": v(f, "route.role_policy"),
            "tracker_member": {"adapter_id": base_name(v(f, "route.tracker_adapter")),
                               "sha256": v(f, "route.tracker_sha256"),
                               "source": f["route.tracker_sha256"]["source"]},
            "source": "training/harness/openai_proxy.py argparse defaults"}},
        "member.prompt": {"kind": "prompt", "content": {
            # a reference, never a copy (role.toml's convention): the text stays in lora-kernel
            "template": "@ref " + v(f, "prompt.ref"), "variables": [],
            "sha256": v(f, "prompt.sha256"), "chars": v(f, "prompt.chars")}},
        "member.sampling": {"kind": "sampling", "content": {
            "max_tokens": v(f, "member.max_tokens"), "enable_thinking": v(f, "member.thinking") == "True",
            "source": f["member.max_tokens"]["source"]}},
    }


def manifest(dims: dict, name: str) -> dict:
    return {"protocol": PROTOCOL, "type": "harness_manifest", "name": name, "dimensions": dims}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lk", required=True, help="path to a lora-kernel checkout (read only)")
    ap.add_argument("-o", "--out", default="-")
    ap.add_argument("--facts", default=None, help="also write every extracted value with its source")
    a = ap.parse_args(argv)
    f = extract(a.lk)
    m = manifest(dims_at_fork(f), "lora-kernel edge/Mac @ fork 2026-10-06")
    text = json.dumps(m, indent=2, ensure_ascii=False) + "\n"
    if a.out == "-":
        sys.stdout.write(text)
    else:
        with open(a.out, "w") as fh:
            fh.write(text)
    if a.facts:
        with open(a.facts, "w") as fh:
            json.dump(f, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
