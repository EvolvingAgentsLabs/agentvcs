"""Evolutionary diagnostics over the commit graph: Price decomposition, the Eigen
error-catastrophe verdict, critical slowing down, and Muller's-ratchet load."""
import json

import pytest

from agentvcs import Repository, RepoError
from agentvcs import dynamics
from agentvcs.cli import main


def _init(tmp_path, **manifest):
    m = {"goal": "g", "models": [], "trace": None, "state": "fluid", **manifest}
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps(m))
    return repo


def _commit(repo, tmp_path, tag, ts, score=None):
    """Make a distinct commit (mutating a file) and optionally record its eval."""
    (tmp_path / "f.txt").write_text(tag)
    oid = repo.commit(tag, timestamp=ts)
    if score is not None:
        repo.write_eval(oid, {"commit": oid, "score": score, "ok": score >= 0.5,
                              "passed": 1, "total": 1, "ts": ts})
    return oid


def _two_branch_points(tmp_path, scores):
    """A→{B,C}, B→D, C→E with the given (A,B,C,D,E) eval scores. Three parents that
    have scored children (A, B, C)."""
    repo = _init(tmp_path)
    sA, sB, sC, sD, sE = scores
    a = _commit(repo, tmp_path, "A", 1, sA)
    repo.branch("b1")                        # b1 -> A
    b = _commit(repo, tmp_path, "B", 2, sB)  # main advances to B (child of A)
    repo.checkout("b1")                      # HEAD -> b1 @ A
    c = _commit(repo, tmp_path, "C", 3, sC)  # b1 advances to C (child of A)
    repo.checkout("main")                    # HEAD -> main @ B
    _commit(repo, tmp_path, "D", 4, sD)      # child of B
    repo.checkout("b1")                      # HEAD -> b1 @ C
    _commit(repo, tmp_path, "E", 5, sE)      # child of C
    return repo, a, b, c


# --------------------------------------------------------------------- price
def test_price_degrading_crosses_threshold(tmp_path):
    repo, *_ = _two_branch_points(tmp_path, (0.9, 0.8, 0.7, 0.6, 0.5))
    r = dynamics.price(repo)
    assert r["insufficient"] is False and r["n_parents"] == 3
    assert r["transmission"] < 0                    # editing degrades within lineage
    assert r["threshold"]["degrading"] is True
    assert r["threshold"]["crossed"] is True        # |transmission| > |selection|
    assert r["threshold"]["code"] == "ERROR_CATASTROPHE"


def test_price_improving_is_healthy(tmp_path):
    repo, *_ = _two_branch_points(tmp_path, (0.5, 0.6, 0.7, 0.8, 0.9))
    r = dynamics.price(repo)
    assert r["transmission"] > 0
    assert r["threshold"]["degrading"] is False
    assert r["threshold"]["crossed"] is False
    assert r["delta_zbar"] > 0


def test_price_insufficient_without_branch_points(tmp_path):
    repo = _init(tmp_path)
    _commit(repo, tmp_path, "solo", 1, 0.8)
    r = dynamics.price(repo)
    assert r["insufficient"] is True and r["n_parents"] < 2


def test_price_bad_trait_raises(tmp_path):
    repo = _init(tmp_path)
    _commit(repo, tmp_path, "x", 1, 0.5)
    with pytest.raises(RepoError) as e:
        dynamics.price(repo, trait="bogus")
    assert e.value.code == "BAD_TRAIT"


def test_price_editable_surface_reported(tmp_path):
    repo = _init(tmp_path, editable=["keep/"])
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.txt").write_text("a")
    (tmp_path / "keep" / "b.txt").write_text("b")
    (tmp_path / "other.txt").write_text("o")
    repo.commit("seed", timestamp=1)
    r = dynamics.price(repo, trait="size")
    # even when insufficient for a decomposition, the L_effective context is computed
    assert r["l_effective"] == 2        # only files under the editable surface count
    assert r["l_total"] > r["l_effective"]   # other.txt + init's agent.json/AGENTS.md


# ------------------------------------------------------------------- slowing
def test_slowing_needs_a_series(tmp_path):
    repo = _init(tmp_path)
    _commit(repo, tmp_path, "a", 1, 0.5)
    _commit(repo, tmp_path, "b", 2, 0.6)
    assert dynamics.slowing(repo)["insufficient"] is True


def test_slowing_computes_over_series(tmp_path):
    repo, *_ = _two_branch_points(tmp_path, (0.9, 0.8, 0.7, 0.6, 0.5))
    sl = dynamics.slowing(repo)
    assert sl["insufficient"] is False and sl["n"] == 5
    assert -1.0 <= sl["lag1_autocorr"] <= 1.0
    assert sl["variance_trend"] in ("rising", "falling", "flat")
    assert sl["warning"] in ("stable", "watch", "approaching_instability")


# ------------------------------------------------------------------- ratchet
def _long_branch(tmp_path):
    repo = _init(tmp_path)
    _commit(repo, tmp_path, "m0", 1, 0.8)     # trunk (main) tip
    repo.branch("feature")
    repo.checkout("feature")
    for i, s in enumerate([0.7, 0.6, 0.7, 0.5, 0.4, 0.3], start=2):
        _commit(repo, tmp_path, f"f{i}", i, s)
    repo.checkout("main")                      # back to m0
    repo.branch("tiny")                        # short branch straight off the trunk
    repo.checkout("tiny")
    _commit(repo, tmp_path, "t", 9, 0.9)       # distance 1 from main
    repo.checkout("main")
    return repo


def test_ratchet_flags_long_unmerged_lineage(tmp_path):
    repo = _long_branch(tmp_path)
    rt = dynamics.ratchet(repo)
    assert rt["trunk"] == "main"
    by = {e["branch"]: e for e in rt["branches"]}
    assert by["feature"]["distance"] == 6
    assert by["feature"]["deleterious_steps"] >= 1
    assert by["feature"]["risk"] == "high"
    assert any("feature" in w for w in rt["warnings"])
    # the one-commit branch is not a ratchet risk
    assert by["tiny"]["risk"] == "none"


def test_ratchet_empty_without_branches(tmp_path):
    repo = _init(tmp_path)
    _commit(repo, tmp_path, "only", 1, 0.5)
    assert dynamics.ratchet(repo)["branches"] == []


# -------------------------------------------------------------------- health
def test_health_rollup_flags_catastrophe(tmp_path):
    repo, *_ = _two_branch_points(tmp_path, (0.9, 0.8, 0.7, 0.6, 0.5))
    h = dynamics.health(repo)
    assert h["healthy"] is False
    assert any("ERROR_CATASTROPHE" in w for w in h["warnings"])
    assert "price" in h and "slowing" in h and "ratchet" in h


# ---------------------------------------------------------------- cli surface
def test_cli_price_json(tmp_path, capsys):
    _two_branch_points(tmp_path, (0.9, 0.8, 0.7, 0.6, 0.5))
    main(["-C", str(tmp_path), "price", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["command"] == "price"
    assert out["threshold"]["code"] == "ERROR_CATASTROPHE"


def test_cli_health_json(tmp_path, capsys):
    _two_branch_points(tmp_path, (0.5, 0.6, 0.7, 0.8, 0.9))
    main(["-C", str(tmp_path), "health", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and "healthy" in out and "warnings" in out


def test_cli_branch_reports_ratchet(tmp_path, capsys):
    _long_branch(tmp_path)
    main(["-C", str(tmp_path), "branch", "--json"])
    out = json.loads(capsys.readouterr().out)
    risks = {b["name"]: b["ratchet"] for b in out["branches"]}
    assert risks["feature"] == "high"
    assert out["warnings"]


# ---------------------------------------------------------------- mcp surface
def test_mcp_price_and_health(tmp_path, monkeypatch):
    from agentvcs import mcp_server
    _two_branch_points(tmp_path, (0.9, 0.8, 0.7, 0.6, 0.5))
    monkeypatch.chdir(tmp_path)

    def _call(name, args=None):
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args or {}}})
        return json.loads(resp["result"]["content"][0]["text"])

    price = _call("avcs_price")
    assert price["ok"] is True and price["threshold"]["code"] == "ERROR_CATASTROPHE"
    health = _call("avcs_health")
    assert health["ok"] is True and health["healthy"] is False
