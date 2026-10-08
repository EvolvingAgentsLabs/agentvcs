"""LK0 against the fixture (tests/fixture/lk, built by make_fixture.py): the importer,
the imported ledgers, the intended conflict, `merge resolve` with the fake claude, and
the static gate. No model, no real lora-kernel checkout, no real `claude`."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

import agentvcs

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(HERE))
FIXTURE = os.path.join(HERE, "tests", "fixture", "lk")
FAKE_CLAUDE = os.path.join(REPO, "crates", "agentvcs-cli", "tests", "fake_claude", "claude")
SUITE = os.path.join(HERE, "suite.yaml")
ENV = {**os.environ, "PYTHON": sys.executable, "LK_EXAMPLE": HERE}
sys.path.insert(0, HERE)

import check_manifest  # noqa: E402
import import_lk  # noqa: E402

METRICS = ["--metric", "mlx.speedup_general", "--metric", "spec.alpha_domain"]


def cli(store, *args, env=None):
    p = subprocess.run([sys.executable, "-m", "agentvcs", "-C", str(store), "--json", *args],
                       capture_output=True, text=True, env=env or ENV)
    return p.returncode, json.loads(p.stdout)


def fixture_json(rel, *keys):
    with open(os.path.join(FIXTURE, rel)) as f:
        v = json.load(f)
    for k in keys:
        v = v[k]
    return v


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    s = tmp_path_factory.mktemp("lk0")
    p = subprocess.run([sys.executable, os.path.join(HERE, "history.py"), "--lk", FIXTURE, "--store", str(s)],
                       capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, p.stdout + p.stderr
    with open(s / "history.json") as f:
        return s, json.load(f)


def test_importer_builds_typed_dimensions_with_sources(tmp_path):
    facts = import_lk.extract(FIXTURE)
    m = import_lk.manifest(import_lk.dims_at_fork(facts), "t")
    kinds = {n: d["kind"] for n, d in m["dimensions"].items()}
    assert kinds == {
        "serve.model": "model", "spec.drafter": "model", "serve.adapter": "adapter", "spec.sampling": "sampling",
        "library.model": "model", "library.adapter": "adapter", "library.config": "config",
        "route.router": "router", "member.prompt": "prompt", "member.sampling": "sampling"}
    d = m["dimensions"]
    assert d["serve.model"]["content"]["id"] == "mlx-community/gemma-4-12B-it-4bit"
    assert d["spec.drafter"]["content"]["id"] == "google/gemma-4-12B-it-assistant"
    sha = fixture_json("results/B3-gemma4-large-member-20260926/train_12b.json", "members", "withlib-s0",
                       "adapter_sha256")
    assert d["serve.adapter"]["content"]["sha256"] == sha
    assert d["serve.adapter"]["content"]["weights_hash"] == agentvcs.hash_json({"sha256": sha})
    assert d["library.config"]["content"]["cite_gate"] is True and d["library.config"]["content"]["page_top"] == 8
    assert d["route.router"]["content"]["router"] == "factored"
    # the prompt is a reference: its sha256 over the text the checkout holds, never the text
    from make_fixture import PLACEHOLDER
    assert d["member.prompt"]["content"]["template"] == "@ref memory/prompt.py:SYSTEM_WIKI"
    assert d["member.prompt"]["content"]["sha256"] == hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
    assert PLACEHOLDER not in json.dumps(m)
    # every value cites a file of the checkout
    files = [os.path.relpath(os.path.join(d, f), FIXTURE) for d, _, fs in os.walk(FIXTURE) for f in fs]
    for name, fact in facts.items():
        assert any(rel in fact["source"] for rel in files), (name, fact["source"])
    (tmp_path / "m.json").write_text(json.dumps(m))
    assert cli(tmp_path, "init")[0] == 0
    code, out = cli(tmp_path, "snapshot", str(tmp_path / "m.json"))
    assert code == 0 and out["ok"], out


def test_imported_ledgers_verify_and_blame_has_segments(store):
    s, h = store
    for run in h["runs"]:
        code, out = cli(s, "verify", run)
        assert code == 0 and out["valid"], (run, out)
    # nine changes, eleven metrics, each value as the results file has it
    assert len({row["change"] for row in h["table"]}) == 9
    assert len(h["table"]) == 11
    row = {(r["change"], r["metric"]): r for r in h["table"]}
    hot = row[("HOTL0", "mlx.speedup_general")]
    assert hot["before"] == fixture_json("results/HOTL0-mac-hotlora-cost-20261006/h1_wrapped.json", "summary",
                                         "wiki12b/general/mtp_b2", "speedup")
    assert hot["after"] == fixture_json("results/HOTL0-mac-hotlora-cost-20261006/h1_wrapped.json", "summary",
                                        "base/general/mtp_b3", "speedup")
    assert "parsed from BRIEF.md" in row[("LIVE-library2", "library.context_overflows")]["source_after"]
    code, b = cli(s, "blame", "lk-speed", "--metric", "mlx.speedup_general")
    assert code == 0
    first, second = b["segments"]
    assert (first["mean"], second["mean"]) == (hot["before"], hot["after"])
    (attr,) = b["attributions"]
    assert attr["patches"] == [hot["patch_id"]]
    # every imported entry is labelled as such, and every patch passed its imported gate
    _, log = cli(s, "log", "lk-trunk")
    for e in log["entries"]:
        if e["kind"] == "step":
            assert e["body"]["agent_id"].startswith("imported:")
        if e["kind"] == "patch":
            assert e["body"]["author"]["id"].startswith("imported:")
            assert e["body"]["gate_result"]["passed"] is True


def test_branches_conflict_on_the_intended_dimensions(store):
    s, h = store
    code, p = cli(s, "merge", "prepare", "--base", h["base"], "--ours", h["ours"], "--theirs", h["theirs"],
                  "--ours-run", "lk-domain", "--theirs-run", "lk-speed", *METRICS)
    assert code == 0, p
    assert [(c["dimension"], c["type"]) for c in p["conflicts"]] == [
        ("serve.adapter", "modify/modify"), ("spec.sampling", "modify/modify")]
    assert {"dimension": "spec.drafter_adapter", "resolution": "ours"} in p["auto"]
    adapter = p["conflicts"][0]
    assert [e["author"]["id"] for e in adapter["evidence"]["ours"]] == ["imported:DRAFT0-aligned-drafter-20261006"]
    assert [e["author"]["id"] for e in adapter["evidence"]["theirs"]] == ["imported:HOTL0-mac-hotlora-cost-20261006"]
    assert adapter["evidence"]["theirs"][0]["blame"]["mlx.speedup_general"] == pytest.approx(0.2)
    sampling = p["conflicts"][1]
    assert sampling["ours"]["content"]["draft_tokens"] == 1 and sampling["theirs"]["content"]["draft_tokens"] == 2


def test_merge_resolve_end_to_end_with_the_fake_claude(store, tmp_path):
    s, h = store
    log = tmp_path / "fake.json"
    env = {**ENV, "FAKE_CLAUDE_MODE": "resolve", "FAKE_CLAUDE_LOG": str(log)}
    code, out = cli(s, "merge", "resolve", "--base", h["base"], "--ours", h["ours"], "--theirs", h["theirs"],
                    "--ours-run", "lk-domain", "--theirs-run", "lk-speed", *METRICS, "--suite", SUITE,
                    "--claude", FAKE_CLAUDE, env=env)
    assert code == 0 and out["ok"], out
    assert out["gate"]["passed"] is True and out["gate"]["metrics"]["checks_failed"] == 0
    assert out["resolver"]["agent"] == "claude-code"
    assert out["merged"] == h["ours"]  # the fake takes ours for every conflict
    seen = json.loads(log.read_text())
    assert "DRAFT0" in seen["branches"] and "HOTL0" in seen["branches"]  # BRANCHES.md carries the rationales


@pytest.mark.parametrize("adapter,sampling,passed", [
    ("ours", "ours", True),       # expert on + aligned drafter, k = 1
    ("theirs", "theirs", True),   # expert resident but inactive, k = 2
    ("theirs", "ours", True),     # expert inactive, k = 1
    ("ours", "theirs", False),    # expert on + aligned drafter at k = 2: never measured
])
def test_static_gate_passes_and_fails_as_designed(store, tmp_path, adapter, sampling, passed):
    s, h = store
    _, p = cli(s, "merge", "prepare", "--base", h["base"], "--ours", h["ours"], "--theirs", h["theirs"])
    res = {"protocol": "agentvcs/0.1", "type": "merge_resolution", "merge_id": p["merge_id"],
           "resolutions": {"serve.adapter": {"take": adapter}, "spec.sampling": {"take": sampling}},
           "rationale": "test", "author": {"type": "human", "id": "test"}}
    (tmp_path / "res.json").write_text(json.dumps(res))
    code, out = cli(s, "merge", "commit", "--base", h["base"], "--ours", h["ours"], "--theirs", h["theirs"],
                    "--resolution", str(tmp_path / "res.json"), "--suite", SUITE)
    assert out["ok"] and out["gate"]["passed"] is passed and code == (0 if passed else 1), out
    if not passed:
        assert out["gate"]["metrics"]["k_in_measured_range"] == 0
        assert out["gate"]["metrics"]["drafter_consistent"] == 1


def test_static_gate_refuses_unhashed_and_misaligned_adapters():
    dims = import_lk.dims_at_fork(import_lk.extract(FIXTURE))
    dims["spec.sampling"]["content"]["draft_tokens"] = 1
    ok = check_manifest.check({"dimensions": dims})
    assert ok["metrics"]["checks_failed"] == 0, ok
    bad = json.loads(json.dumps(dims))
    del bad["library.adapter"]["content"]["sha256"]
    assert check_manifest.check({"dimensions": bad})["metrics"]["adapters_hashed"] == 0
    bad = json.loads(json.dumps(dims))
    bad["spec.drafter_adapter"] = {"kind": "adapter", "content": {
        **dims["serve.adapter"]["content"], "base": "google/gemma-4-12B-it-assistant",
        "aligned_to": "some-other-expert", "active_with": "serve.adapter"}}
    assert check_manifest.check({"dimensions": bad})["metrics"]["drafter_consistent"] == 0
    bad["spec.drafter_adapter"]["content"]["aligned_to"] = dims["serve.adapter"]["content"]["adapter_id"]
    assert check_manifest.check({"dimensions": bad})["metrics"]["k_in_measured_range"] == 1
    bad["spec.sampling"]["content"]["draft_tokens"] = None  # the drafter's default: not a measured k
    assert check_manifest.check({"dimensions": bad})["metrics"]["k_in_measured_range"] == 0


def test_demo_dry_run_stops_before_resolve(tmp_path):
    p = subprocess.run(["bash", os.path.join(HERE, "demo.sh"), "--dry-run", "--lk", FIXTURE,
                        "--work", str(tmp_path / "w")], capture_output=True, text=True, env=ENV, timeout=300)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    assert "CONFLICT serve.adapter modify/modify" in p.stdout
    assert "CONFLICT spec.sampling modify/modify" in p.stdout
    assert "NOTE: --dry-run; not invoking Claude Code." in p.stdout
    assert "merged" not in p.stdout.split("== 5.")[1].split("== 6.")[0]
