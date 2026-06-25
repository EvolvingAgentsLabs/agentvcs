"""Tests for the corporate/legal layer: the digital statute (mandate) versioned in
agent.json, the reserved-matter policy gate, signed human authorizations, and the
Soul-signed Libro de Actas Digital produced by `audit`."""
import json

import pytest

from agentvcs import _ed25519 as ed
from agentvcs import corporate, soul
from agentvcs.objects import canonical
from agentvcs.repository import Repository
from agentvcs.cli import main


# --------------------------------------------------------------- opt-in (default off)
def test_default_repo_is_not_corporate(tmp_path):
    repo = Repository.init(tmp_path)
    assert corporate.config(repo.read_manifest()) is None
    assert corporate.is_corporate(repo.read_manifest()) is False
    report = corporate.audit(repo)
    assert report["corporate"] is False


def test_default_block_from_profile():
    block = corporate.default_block("AR_SAS_Auto")
    assert block["entity_type"] == "SAS Automatizada"
    assert block["jurisdiction"] == "AR"
    # deep-copied: mutating one block never leaks into the profile template
    block["liability_limits"]["max_inference_usd"] = 1
    assert corporate.PROFILES["AR_SAS_Auto"]["liability_limits"]["max_inference_usd"] is None


def test_unknown_profile_is_treated_as_jurisdiction_hint():
    block = corporate.default_block("EU_AI_Act")
    assert block["jurisdiction"] == "EU_AI_Act"


# --------------------------------------------------------------- helpers
def _corp_repo(tmp_path, *, reserved=None, ceiling=None, reps=None,
               goal="operate the refunds desk"):
    repo = Repository.init(tmp_path, with_soul=True)
    m = repo.read_manifest()
    m["goal"] = goal
    block = corporate.default_block("AR_SAS_Auto")
    if reserved is not None:
        block["liability_limits"]["requires_human_for"] = reserved
    if ceiling is not None:
        block["liability_limits"]["max_inference_usd"] = ceiling
    if reps is not None:
        block["legal_representatives"] = reps
    m["corporate"] = block
    (tmp_path / "agent.json").write_text(json.dumps(m))
    return repo, block


def _write_trace_tool_call(tmp_path, name, inp):
    msg = {"role": "assistant",
           "content": [{"type": "tool_use", "name": name, "input": inp}]}
    (tmp_path / "traces").mkdir(exist_ok=True)
    (tmp_path / "traces" / "run.jsonl").write_text(json.dumps(msg) + "\n")


# --------------------------------------------------------------- reserved-matter gate
def test_reserved_action_without_approval_is_a_breach(tmp_path):
    repo, block = _corp_repo(tmp_path, reserved=["transfer"])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 5000})
    oid = repo.commit("paid a supplier")
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["reserved_actions"] and rec["reserved_actions"][0]["action"] == "wire_transfer"
    assert rec["within_mandate"] is False
    assert any(b["kind"] == "unauthorized_action" for b in rec["breaches"])


def test_non_reserved_action_is_within_mandate(tmp_path):
    repo, block = _corp_repo(tmp_path, reserved=["transfer", "delete_account"])
    _write_trace_tool_call(tmp_path, "read_file", {"path": "ledger.csv"})
    oid = repo.commit("read the ledger")
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["reserved_actions"] == []
    assert rec["within_mandate"] is True


def test_signed_authorization_by_listed_rep_clears_the_acta(tmp_path):
    seed = bytes(range(7, 39))
    pub = ed.publickey(seed).hex()
    repo, block = _corp_repo(tmp_path, reserved=["transfer"],
                             reps=[{"name": "Ana", "soul": pub}])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 5000})
    oid = repo.commit("paid a supplier")

    # before approval: breach
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["within_mandate"] is False

    # the representative signs an authorization with their own Ed25519 seed
    approval = corporate.record_approval(repo, oid, name="Ana", seed_hex=seed.hex(),
                                         note="board resolution 2026-07")
    assert approval["representative"] == pub
    assert corporate.approval_is_valid(approval, block) is True

    rec2 = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec2["authorized"] is True
    assert rec2["within_mandate"] is True


def test_approval_by_non_listed_rep_does_not_clear(tmp_path):
    listed = ed.publickey(bytes(range(7, 39))).hex()
    repo, block = _corp_repo(tmp_path, reserved=["transfer"],
                             reps=[{"name": "Ana", "soul": listed}])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 5000})
    oid = repo.commit("paid a supplier")
    impostor_seed = bytes(range(40, 72))
    approval = corporate.record_approval(repo, oid, seed_hex=impostor_seed.hex())
    assert corporate.approval_is_valid(approval, block) is False
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["within_mandate"] is False


def test_unsigned_attestation_is_advisory_only(tmp_path):
    repo, block = _corp_repo(tmp_path, reserved=["transfer"])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 5000})
    oid = repo.commit("paid a supplier")
    approval = corporate.record_approval(repo, oid, representative="someone", note="ok by phone")
    assert corporate.approval_is_valid(approval, block) is False
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["within_mandate"] is False


# --------------------------------------------------------------- spend ceiling gate
def test_over_inference_ceiling_is_a_breach(tmp_path):
    repo, block = _corp_repo(tmp_path, ceiling=0.01)
    tree = repo.objects.write_obj({"type": "tree", "entries": {}})
    goal = repo.objects.write_obj({"type": "goal", "text": "spend", "parent": None})
    rt = repo.objects.write_obj({"type": "runtime", "budget": {"cost_usd": 0.50}})
    oid = repo.write_commit({
        "type": "commit", "parents": [], "tree": tree, "goal": goal, "models": [],
        "trace": None, "state": "fluid", "metrics": {}, "message": "big spend",
        "author": "agent", "timestamp": 0, "runtime": rt})
    rec = corporate.check_commit(repo, oid, repo.objects.read_obj(oid), block)
    assert rec["inference_usd"] == 0.50
    assert any(b["kind"] == "over_inference_budget" for b in rec["breaches"])
    assert rec["within_mandate"] is False


# --------------------------------------------------------------- the Libro de Actas
def test_audit_is_signed_and_verifiable(tmp_path):
    repo, block = _corp_repo(tmp_path, reserved=["transfer"])
    _write_trace_tool_call(tmp_path, "read_file", {"path": "x"})
    repo.commit("benign acta")
    report = corporate.audit(repo)
    assert report["corporate"] is True
    assert report["entity"]["jurisdiction"] == "AR"
    assert report["summary"]["actas"] == 1
    assert report["summary"]["compliant"] is True
    # the report body is signed by the entity's Soul — a regulator can verify it
    assert soul.verify_bytes(repo.soul_id(), canonical(report["actas"]),
                             report["report_signature"])


def test_audit_flags_an_out_of_mandate_history(tmp_path):
    repo, block = _corp_repo(tmp_path, reserved=["transfer"])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 9000})
    repo.commit("unauthorized transfer")
    report = corporate.audit(repo)
    assert report["summary"]["compliant"] is False
    assert report["summary"]["breached"] == 1


def test_audit_judges_each_acta_against_the_statute_then_in_force(tmp_path):
    # statute starts with NO reserved matters; the transfer acta is fine...
    repo, block = _corp_repo(tmp_path, reserved=[])
    _write_trace_tool_call(tmp_path, "wire_transfer", {"amount": 100})
    repo.commit("transfer under the lax statute")
    # ...then the statute is tightened (and the desk moves on to benign work). The
    # earlier acta must still be judged against the rules that existed when it
    # happened — so it stays compliant despite the later, stricter statute.
    _write_trace_tool_call(tmp_path, "read_file", {"path": "ledger.csv"})
    m = repo.read_manifest()
    m["corporate"]["liability_limits"]["requires_human_for"] = ["transfer"]
    (tmp_path / "agent.json").write_text(json.dumps(m))
    repo.commit("tighten the statute")
    report = corporate.audit(repo)
    assert report["summary"]["compliant"] is True


# --------------------------------------------------------------- CLI init wiring
def test_cli_init_corporate_writes_statute_and_births_soul(tmp_path):
    d = tmp_path / "co"
    rc = main(["init", str(d), "--corporate", "--json"])
    assert rc == 0
    manifest = json.loads((d / "agent.json").read_text())
    assert manifest["corporate"]["entity_type"] == "SAS Automatizada"
    assert manifest["mode"] == "runtime"           # corporate implies runtime mode
    assert (d / "LEGAL.md").exists()               # the digital statute
    assert (d / ".agentvcs" / "soul").exists()     # corporate implies --with-soul
    legal = (d / "LEGAL.md").read_text()
    assert "Estatuto Digital" in legal and "Libro de Actas" in legal
    agents = (d / "AGENTS.md").read_text()
    assert "corporate layer" in agents


def test_cli_default_init_has_no_corporate(tmp_path):
    d = tmp_path / "plain"
    main(["init", str(d), "--json"])
    manifest = json.loads((d / "agent.json").read_text())
    assert "corporate" not in manifest
    assert not (d / "LEGAL.md").exists()
