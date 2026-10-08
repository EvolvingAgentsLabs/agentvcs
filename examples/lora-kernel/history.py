#!/usr/bin/env python3
"""Turn nine measured configuration changes of lora-kernel's edge/Mac stack into
agentvcs run ledgers.

    python history.py --lk ~/evolvingagents/lora-kernel --store WORKDIR
    python history.py gate-metrics <CHANGE> --lk ...     # the suite command each imported gate runs

These are IMPORTED measurements, not live runs: no model is loaded or called. Each
change is a patch (manifest before -> after) whose gate reads its numbers from
lora-kernel's committed results files at gate time; the steps around it carry the
before/after values so `blame` has segments. Every step's agent_id and every patch's
author is `imported:<results dir>`.

Three runs:
  lk-trunk   six changes lora-kernel made and serves today (2026-10-02 .. 10-05);
             ends on the fork manifest (import_lk.py).
  lk-domain  from the fork: keep the expert LoRA on and align the drafter to it
             (MLXK0 k = 1, DRAFT0 drafter adapter switched with the expert).
  lk-speed   from the fork: keep the expert resident but inactive and draft k = 2
             (HOTL0: the base with MTP is the fastest measured configuration).
The two branches are constructed for this demo from measured numbers; neither is a
serving decision lora-kernel has made.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import import_lk as ilk  # noqa: E402
from lkread import Reader, fraction  # noqa: E402

R = "results/"
ABSENT = object()  # a content key (or a whole dimension) that does not exist


# --------------------------------------------------------------------------- reads
# Each metric read returns (value, source). Numbers come from the results files; the
# one that lives only in a BRIEF.md is parsed from it and its source says so.

def jfrac(rel, *keys):
    def read(r):
        s, src = r.json(rel, *keys)
        return fraction(s), f"{src} ({s})"
    return read


def jval(rel, *keys):
    return lambda r: r.json(rel, *keys)


def ratio(rel_a, rel_b):
    """right / n of a live.json."""
    def read(r):
        a, src = r.json(rel_a, "right")
        n, _ = r.json(rel_b, "n")
        return a / n, f"{src} / n ({a}/{n})"
    return read


def brief_int(rel, pattern, group):
    def read(r):
        s, src = r.regex(rel, pattern, group)
        return int(s), f"{src} [parsed from BRIEF.md: the number is not in a results JSON]"
    return read


LIVE1 = R + "LIVE-library-20261001/live.json"
LIVE2 = R + "LIVE-library2-20261002/"
GATE0 = R + "GATE0-cite-gate-20261002/"
PAGE0 = R + "PAGE0-page-top-20261002/"
ROUTE0 = R + "ROUTE0-factored-router-20261002/"
ROUTE1 = R + "ROUTE1-tracker-abstain-20261003/"
SPECK0 = R + "SPECK0-mac-mtp-k-20261005/"
MAC = R + "MAC-mlx-12b-lora-mtp-20260927/mac.json"
MLXK0 = R + "MLXK0-mac-mlx-mtp-ceiling-20261005/"
DRAFT0 = R + "DRAFT0-aligned-drafter-20261006/"
HOTL0 = R + "HOTL0-mac-hotlora-cost-20261006/"
OVERFLOWS = r"llama-server logged (\d+) context overflows \((\d+) before\)"
FOREIGN_SETS = ("E3", "E4", "I3", "C3", "D3")  # ROUTE0 BRIEF: "foreign — E3, E4, I3, C3, D3 (600)"


def page0_margin(r):
    s, src = r.json(PAGE0 + "verdict.json", "paired")
    w, l = (int(x) for x in s.split(":"))
    return w - l, f"{src} ({s}: wins - losses)"


def foreign_abstained(r):
    ab = n = 0
    for s in FOREIGN_SETS:
        ab += r.json(ROUTE0 + "verdict.json", "per_set", "factored", s, "abstained")[0]
        n += r.json(ROUTE0 + "verdict.json", "per_set", "factored", s, "n")[0]
    return ab / n, f"{ROUTE0}verdict.json#/per_set/factored/{{{','.join(FOREIGN_SETS)}}}/abstained ({ab}/{n})"


def llamacpp_best(r):
    vals = [r.json(SPECK0 + "speck0.json", "summary", f"{c}/base/general", "speedup")[0]
            for c in ("mtp_k1", "mtp_k2", "mtp")]
    return max(vals), f"{SPECK0}speck0.json#/summary/{{mtp_k1,mtp_k2,mtp}}~1base~1general/speedup (max of {vals})"


def wrapper_cost(r):
    s0 = r.json(HOTL0 + "h0_bare.json", "summary", "base/general/mtp_b3", "speedup")[0]
    s1 = r.json(HOTL0 + "h1_wrapped.json", "summary", "base/general/mtp_b3", "speedup")[0]
    return round(abs(s0 - s1), 6), f"|h0_bare - h1_wrapped| base/general/mtp_b3 speedup (|{s0} - {s1}|)"


# --------------------------------------------------------------------------- changes
# edits: (dimension, key, before, after); key None = the whole dimension.
# Config values (not metrics) cite where lora-kernel states them in `config_sources`.

def changes(f: dict) -> list[dict]:
    v = lambda k: f[k]["value"]  # noqa: E731
    tracker_now = {"adapter_id": ilk.base_name(v("route.tracker_adapter")), "sha256": v("route.tracker_sha256"),
                   "source": f["route.tracker_sha256"]["source"]}
    tracker_before = {"adapter_id": ilk.base_name(v("route.tracker_prev_adapter")),
                      "sha256": v("route.tracker_prev_sha256"), "source": f["route.tracker_prev_sha256"]["source"]}
    serve_model_now = ilk.dims_at_fork(f)["serve.model"]["content"]
    drafter_now = ilk.dims_at_fork(f)["spec.drafter"]["content"]
    drafter_adapter = {"kind": "adapter", "content": ilk.adapter(
        ilk.base_name(v("drafter_adapter.adapter")), v("drafter_adapter.record_sha256"),
        f"bytes of {DRAFT0}draft0.json (DRAFT0 recorded no adapter_sha256)",
        f["drafter_adapter.record_sha256"]["source"],
        base=v("drafter_adapter.drafter"), aligned_to=ilk.base_name(v("drafter_adapter.target_lora")),
        r=v("drafter_adapter.r"), targets=v("drafter_adapter.targets"), active_with="serve.adapter")}
    return [
        {"id": "LIVE-library2", "dir": "LIVE-library2-20261002", "run": "trunk", "date": "2026-10-02T07:02:53Z",
         "what": "library endpoint: a long page opens within a 2,500-token budget; OpenClaw's envelope stripped",
         "quote": (LIVE2 + "BRIEF.md", "both edge losses gone, the score did not follow"),
         "config_sources": [("examples/library/serve.py", "0: whole, as REAL4")],
         "edits": [("library.config", "page_budget", 0, v("library.page_budget")),
                   ("library.config", "strip_openclaw_envelope", False, True)],
         "metrics": {"library.live_right": (ratio(LIVE1, LIVE1), ratio(LIVE2 + "live.json", LIVE2 + "live.json")),
                     "library.context_overflows": (brief_int(LIVE2 + "BRIEF.md", OVERFLOWS, 2),
                                                   brief_int(LIVE2 + "BRIEF.md", OVERFLOWS, 1))},
         "extras": {},
         "thresholds": {"library.context_overflows": {"op": "<=", "value": 0}}},
        {"id": "GATE0", "dir": "GATE0-cite-gate-20261002", "run": "trunk", "date": "2026-10-02T12:00:00Z",
         "what": "library endpoint: an answer whose citation fails is not delivered (--cite-gate)",
         "quote": (GATE0 + "BRIEF.md", "an answer the referee cannot verify is not delivered"),
         "config_sources": [(GATE0 + "BRIEF.md", "the gate ships off by default")],
         "edits": [("library.config", "cite_gate", False, v("library.cite_gate"))],
         "metrics": {"library.delivered_precision": (jval(GATE0 + "gate0.json", "precision_before"),
                                                     jval(GATE0 + "gate0.json", "precision_after"))},
         "extras": {"library.right_blocked_pct": jval(GATE0 + "gate0.json", "right_blocked_pct"),
                    "library.not_right_blocked_pct": jval(GATE0 + "gate0.json", "not_right_blocked_pct")},
         "thresholds": {"library.right_blocked_pct": {"op": "<=", "value": 1},
                        "library.not_right_blocked_pct": {"op": ">=", "value": 15}}},
        {"id": "PAGE0", "dir": "PAGE0-page-top-20261002", "run": "trunk", "date": "2026-10-02T18:00:00Z",
         "what": "library endpoint: a page opens with the question's best 8 statements (--page-top 8)",
         "quote": (PAGE0 + "BRIEF.md", "a page opens with the question's best statements"),
         "config_sources": [("examples/library/serve.py", "(0: whole)")],
         "edits": [("library.config", "page_top", 0, v("library.page_top"))],
         "metrics": {"library.page_answerable": (jfrac(PAGE0 + "verdict.json", "answerable", "withlib-s0+page"),
                                                 jfrac(PAGE0 + "verdict.json", "answerable", "withlib-s0+page+top8"))},
         "extras": {"library.page_paired_margin": page0_margin},
         "thresholds": {"library.page_paired_margin": {"op": ">", "value": 0}}},
        {"id": "ROUTE0", "dir": "ROUTE0-factored-router-20261002", "run": "trunk", "date": "2026-10-02T21:00:00Z",
         "what": "proxy: route by task and content (factored) instead of the keyword dictionary",
         "quote": (ROUTE0 + "BRIEF.md", "the router's question is the task"),
         "config_sources": [("training/harness/openai_proxy.py", "keyword `dictionary` it replaced")],
         "edits": [("route.router", "router", "dictionary", v("route.router"))],
         "metrics": {"route.foreign_served_locally": (jfrac(ROUTE0 + "verdict.json", "dictionary_foreign_misrouted"),
                                                      jfrac(ROUTE0 + "verdict.json", "foreign_misrouted"))},
         "extras": {"route.foreign_abstained": foreign_abstained},
         "thresholds": {"route.foreign_abstained": {"op": ">=", "value": 0.95}}},
        {"id": "ROUTE1", "dir": "ROUTE1-tracker-abstain-20261003", "run": "trunk", "date": "2026-10-04T12:09:35Z",
         "what": "proxy: serve the tracker member trained to abstain (tracker-out-s0) in place of tr-s1",
         "quote": (ROUTE1 + "BRIEF.md", "Serving `tr-out-s0` in place of `tr-s1` is the change it asks for"),
         "config_sources": [(ROUTE1 + "BRIEF.md", "`tr-s1` (served, baseline)")],
         "edits": [("route.router", "tracker_member", tracker_before, tracker_now)],
         "metrics": {"route.tracker_abstained_out": (
             jfrac(ROUTE1 + "route1.json", "reading", "arms", "s1-harness", "abstained_out"),
             jfrac(ROUTE1 + "route1.json", "reading", "arms", "out-harness", "abstained_out"))},
         "extras": {"route.dependent_lost": jval(ROUTE1 + "route1.json", "reading", "dependent_lost")},
         "thresholds": {"route.tracker_abstained_out": {"op": ">=", "value": 0.9},
                        "route.dependent_lost": {"op": "<=", "value": 3}}},
        {"id": "SPECK0", "dir": "SPECK0-mac-mtp-k-20261005", "run": "trunk", "date": "2026-10-05T21:16:08Z",
         "what": "12B lane: speculative decoding moves from llama.cpp to MLX (llama.cpp's round costs too much)",
         "quote": (SPECK0 + "BRIEF.md", "On a 16 GB Mac, speculative decoding is an MLX question"),
         "config_sources": [(SPECK0 + "BRIEF.md", "default `--spec-draft-n-max` is **3**")],
         "edits": [("serve.model", None,
                    {"kind": "model", "content": {"provider": "llama.cpp", "id": v("llamacpp.target"),
                                                  "quantization": "Q4_0", "source": f["llamacpp.target"]["source"]}},
                    {"kind": "model", "content": serve_model_now}),
                   ("spec.drafter", None,
                    {"kind": "model", "content": {"provider": "llama.cpp", "id": v("llamacpp.mtp"), "method": "mtp",
                                                  "source": f["llamacpp.mtp"]["source"]}},
                    {"kind": "model", "content": drafter_now}),
                   ("spec.sampling", "draft_tokens", int(v("llamacpp.k_default")), None)],
         "metrics": {"mac.spec_speedup_base_general": (
             jval(SPECK0 + "speck0.json", "summary", "mtp/base/general", "speedup"),
             jval(MAC, "summary", "base/general", "speedup"))},
         "extras": {"mac.llamacpp_best_base_general": llamacpp_best},
         "thresholds": {"mac.llamacpp_best_base_general": {"op": "<", "value": 1.0},
                        "mac.spec_speedup_base_general.gain": {"op": ">", "value": 0}}},
        # ---- branch domain (ours): the expert stays on, the drafter is aligned to it
        {"id": "MLXK0", "dir": "MLXK0-mac-mlx-mtp-ceiling-20261005", "run": "domain", "date": "2026-10-05T12:00:00Z",
         "what": "[branch domain] draft one token per round (k = 1) with the expert on",
         "quote": (MLXK0 + "BRIEF.md", "The best $k$ is 1 everywhere."),
         "config_sources": [],
         "edits": [("spec.sampling", "draft_tokens", None, 1)],
         "metrics": {"mlx.speedup_lora_domain": (jval(MAC, "summary", "wiki12b/domain", "speedup"),
                                                 jval(MLXK0 + "mlxk0.json", "summary", "wiki12b/domain/mtp_b2", "speedup"))},
         "extras": {"mlx.speedup_lora_domain_k2": jval(MLXK0 + "mlxk0.json", "summary", "wiki12b/domain/mtp_b3", "speedup"),
                    "mlx.speedup_lora_domain_k3": jval(MLXK0 + "mlxk0.json", "summary", "wiki12b/domain/mtp_b4", "speedup")},
         "thresholds": {"mlx.speedup_lora_domain.gain": {"op": ">", "value": 0}},
         "caveat": "before = MAC (2026-09-27, drafter default), after = MLXK0 (k = 1): two sittings; "
                   "HOTL0 later found MLXK0's sitting slow, so the absolute numbers are low"},
        {"id": "DRAFT0", "dir": "DRAFT0-aligned-drafter-20261006", "run": "domain", "date": "2026-10-06T11:32:03Z",
         "what": "[branch domain] a LoRA on the MTP drafter aligned to the expert, switched together with it",
         "quote": (DRAFT0 + "BRIEF.md",
                   "The expert's and the drafter's adapters can be switched together, as the user designed."),
         "config_sources": [],
         "edits": [("spec.drafter_adapter", None, ABSENT, drafter_adapter),
                   ("serve.adapter", "switch_with", ABSENT, "spec.drafter_adapter")],
         "metrics": {"spec.alpha_domain": (jval(DRAFT0 + "draft0.json", "alpha", "stock", "domain"),
                                           jval(DRAFT0 + "draft0.json", "alpha", "aligned", "domain")),
                     "mlx.speedup_projected_k1_domain": (
                         jval(DRAFT0 + "draft0.json", "projected_speedup_k1", "domain", "stock"),
                         jval(DRAFT0 + "draft0.json", "projected_speedup_k1", "domain", "aligned"))},
         "extras": {"spec.alpha_general_aligned": jval(DRAFT0 + "draft0.json", "alpha", "aligned", "general")},
         "thresholds": {"spec.alpha_domain": {"op": ">=", "value": 0.85},
                        "spec.alpha_domain.gain": {"op": ">=", "value": 0.15}},
         "caveat": "alpha is measured offline on Colab; the speed-up is PROJECTED, (1+alpha)/C(1) with HOTL0's C(1), "
                   "never measured on the Mac"},
        # ---- branch speed (theirs): the expert stays resident but inactive, k = 2
        {"id": "HOTL0", "dir": "HOTL0-mac-hotlora-cost-20261006", "run": "speed", "date": "2026-10-06T07:54:05Z",
         "what": "[branch speed] expert LoRA resident but inactive while MTP drafts k = 2",
         "quote": (HOTL0 + "BRIEF.md", "The active LoRA itself costs ~3.5 % of plain decoding and its speculation 1.23×"),
         "config_sources": [],
         "edits": [("serve.adapter", "active", True, False), ("spec.sampling", "draft_tokens", None, 2)],
         "metrics": {"mlx.speedup_general": (
             jval(HOTL0 + "h1_wrapped.json", "summary", "wiki12b/general/mtp_b2", "speedup"),
             jval(HOTL0 + "h1_wrapped.json", "summary", "base/general/mtp_b3", "speedup"))},
         "extras": {"mlx.speedup_general_bare": jval(HOTL0 + "h0_bare.json", "summary", "base/general/mtp_b3", "speedup"),
                    "mlx.wrapper_cost": wrapper_cost},
         "thresholds": {"mlx.speedup_general.gain": {"op": ">", "value": 0},
                        "mlx.wrapper_cost": {"op": "<", "value": 0.08}},
         "caveat": "before = the expert active at its best measured k (k = 1; HOTL0 did not run the drafter's default "
                   "block size); after = 328 wrappers attached and inactive at k = 2, same sitting. With no adapter "
                   "attached at all the base reaches 1.47x (mlx.speedup_general_bare). The expert's domain quality "
                   "is not part of this number: with the expert inactive the 12B answers as the base"},
    ]


# --------------------------------------------------------------------------- manifests

def apply(dims: dict, edits, forward: bool = True) -> dict:
    d = copy.deepcopy(dims)
    for dim, key, before, after in (edits if forward else reversed(edits)):
        new = after if forward else before
        if key is None:
            if new is ABSENT:
                d.pop(dim, None)
            else:
                d[dim] = copy.deepcopy(new)
        else:
            if new is ABSENT:
                d[dim]["content"].pop(key, None)
            else:
                d[dim]["content"][key] = copy.deepcopy(new)
    return d


def manifests(f: dict) -> dict:
    """{"m0", "fork", "domain", "speed", per-change "after:<id>"} as dimension maps."""
    fork = ilk.dims_at_fork(f)
    cs = changes(f)
    trunk = [c for c in cs if c["run"] == "trunk"]
    m = fork
    for c in reversed(trunk):
        m = apply(m, c["edits"], forward=False)
    out = {"m0": m}
    for c in trunk:
        m = apply(m, c["edits"])
        out["after:" + c["id"]] = m
    assert m == fork, "replaying the trunk does not reproduce the imported fork manifest"
    out["fork"] = fork
    for run in ("domain", "speed"):
        m = fork
        for c in cs:
            if c["run"] == run:
                m = apply(m, c["edits"])
                out["after:" + c["id"]] = m
        out[run] = m
    return out


# --------------------------------------------------------------------------- gate metrics

def read_change(r: Reader, c: dict) -> dict:
    """{"metrics": {...}, "sources": {...}} for one change, read now from the checkout."""
    metrics, sources = {}, {}
    for name, (rb, ra) in c["metrics"].items():
        b, bs = rb(r)
        a, as_ = ra(r)
        metrics[name + ".before"], metrics[name], metrics[name + ".gain"] = b, a, round(a - b, 6)
        sources[name + ".before"], sources[name] = bs, as_
    for name, rd in c["extras"].items():
        metrics[name], sources[name] = rd(r)
    for rel, words in [c["quote"], *c["config_sources"]]:
        r.quote(rel, words)
    return {"metrics": metrics, "sources": sources}


# --------------------------------------------------------------------------- the ledger

class Cli:
    def __init__(self, store: str):
        cmd = os.environ.get("AGENTVCS_CLI", "")
        self.cmd = shlex.split(cmd) if cmd else [sys.executable, "-m", "agentvcs"]
        self.store = store

    def __call__(self, *args: str, stdin: str | None = None, ok: bool = True) -> dict:
        p = subprocess.run([*self.cmd, "-C", self.store, "--json", *args], input=stdin,
                           capture_output=True, text=True)
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise SystemExit(f"agentvcs {args[0]} printed no JSON: {p.stdout!r} {p.stderr!r}")
        if ok and not out.get("ok"):
            raise SystemExit(f"agentvcs {' '.join(args[:2])} failed: {out}")
        return out


def write_manifest(store: str, label: str, dims: dict) -> str:
    path = os.path.join(store, "manifests.in", label.replace(":", "_") + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(ilk.manifest(dims, f"lora-kernel edge/Mac {label}"), fh, indent=2, ensure_ascii=False)
    return path


def build(lk: str, store: str, verbose: bool = True) -> dict:
    r = Reader(lk)
    f = ilk.extract(r)
    ms = manifests(f)
    cs = changes(f)
    cli = Cli(store)
    cli("init")
    ids = {k: cli("snapshot", write_manifest(store, k, d))["manifest_id"] for k, d in ms.items()}
    starts = {"trunk": "m0", "domain": "fork", "speed": "fork"}
    table = []
    for run, start in starts.items():
        run_id = f"lk-{run}"
        cli("run", "start", "--manifest", ids[start], "--run-id", run_id)
        active = ids[start]
        step = 0
        for c in (c for c in cs if c["run"] == run):
            got = read_change(r, c)
            agent = f"imported:{c['dir']}"
            names = list(c["metrics"])

            def record(metrics, manifest_id):
                nonlocal step
                body = {"step_index": step, "manifest_id": manifest_id, "agent_id": agent, "inputs": [], "outputs": [],
                        "started_at": c["date"], "ended_at": c["date"], "tokens": {"in": 0, "out": 0},
                        "latency_ms": 0, "metrics": metrics, "checkpoint_ref": None}
                cli("step", "record", run_id, stdin=json.dumps(body))
                step += 1
                return step - 1

            before_step = record({n: got["metrics"][n + ".before"] for n in names}, active)
            quote_rel, quote = c["quote"]
            rationale = f"{c['what']} -- {c['id']} [ran, imported]: \"{quote}\" ({quote_rel})"
            if c.get("caveat"):
                rationale += f". Caveat: {c['caveat']}"
            to_file = os.path.join(store, "manifests.in", f"after_{c['id']}.json")
            pid = cli("patch", "propose", run_id, "--from", active, "--to", to_file, "--rationale", rationale,
                      "--evidence", str(before_step), "--author", f"agent:{agent}")["patch_id"]
            suite = os.path.join(store, "suites", f"{c['id']}.yaml")
            os.makedirs(os.path.dirname(suite), exist_ok=True)
            gate_cmd = shlex.join([sys.executable, os.path.abspath(__file__), "gate-metrics", c["id"],
                                   "--lk", os.path.abspath(lk)])
            with open(suite, "w") as fh:
                fh.write(f"name: imported:{c['id']}\ncommand: {json.dumps(gate_cmd)}\nthresholds:\n")
                for k, t in c["thresholds"].items():
                    fh.write(f"  {json.dumps(k)}: {{op: {json.dumps(t['op'])}, value: {t['value']}}}\n")
            g = cli("gate", "run", pid, "--suite", suite)["gate_result"]
            if not g["passed"]:
                raise SystemExit(f"imported gate {c['id']} did not pass: {g}")
            active = cli("patch", "apply", pid)["active_manifest"]
            assert active == ids["after:" + c["id"]], c["id"]
            record({n: got["metrics"][n] for n in names}, active)
            for n in names:
                table.append({"change": c["id"], "run": run_id, "dimensions": sorted({e[0] for e in c["edits"]}),
                              "metric": n, "before": got["metrics"][n + ".before"], "after": got["metrics"][n],
                              "source_before": got["sources"][n + ".before"], "source_after": got["sources"][n],
                              "patch_id": pid})
            if verbose:
                for n in names:
                    print(f"[history] {run_id:9} {c['id']:13} {n:34} {got['metrics'][n + '.before']:.4g} -> "
                          f"{got['metrics'][n]:.4g}  gate passed", flush=True)
        cli("run", "end", run_id, "--status", "completed")
        cli("export", "audit", run_id, "-o", os.path.join(store, f"{run_id}.audit.json"))
    summary = {"manifests": ids, "runs": [f"lk-{r_}" for r_ in starts], "table": table,
               "ours": ids["domain"], "theirs": ids["speed"], "base": ids["fork"]}
    with open(os.path.join(store, "history.json"), "w") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    return summary


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "gate-metrics":
        ap = argparse.ArgumentParser(prog="history.py gate-metrics")
        ap.add_argument("change")
        ap.add_argument("--lk", required=True)
        a = ap.parse_args(argv[1:])
        r = Reader(a.lk)
        f = ilk.extract(r)
        (c,) = [c for c in changes(f) if c["id"] == a.change]
        print(json.dumps(read_change(r, c)))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lk", required=True, help="path to a lora-kernel checkout (read only)")
    ap.add_argument("--store", required=True, help="agentvcs project directory (created)")
    a = ap.parse_args(argv)
    os.makedirs(a.store, exist_ok=True)
    s = build(a.lk, a.store)
    print(json.dumps({"base": s["base"], "ours": s["ours"], "theirs": s["theirs"], "runs": s["runs"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
