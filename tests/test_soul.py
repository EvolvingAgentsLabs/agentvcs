"""Tests for the DeSoc identity layer: Soul keypairs, signed-commit provenance,
Soulbound Tokens minted on verified freeze, and tamper detection."""
import json
import sys

import pytest

from agentvcs import _ed25519 as ed
from agentvcs.repository import Repository
from agentvcs.crystallize import crystallize
from agentvcs.eval import run_eval
from agentvcs import sbt, soul


# --------------------------------------------------------------- ed25519 core
def test_ed25519_matches_rfc8032_vector():
    # seed 000102..1f → the canonical RFC 8032 / NaCl public key
    seed = bytes(range(32))
    assert ed.publickey(seed).hex() == \
        "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"


def test_ed25519_sign_verify_and_tamper():
    seed = bytes(range(1, 33))
    pk = ed.publickey(seed)
    msg = b"the trace is the line of a life"
    sig = ed.sign(msg, seed, pk)
    assert ed.verify(sig, msg, pk)
    assert not ed.verify(sig, msg + b"!", pk)          # message tamper
    bad = bytearray(sig); bad[10] ^= 1
    assert not ed.verify(bytes(bad), msg, pk)          # signature tamper
    assert not ed.verify(b"too short", msg, pk)        # garbage


# --------------------------------------------------------------- soul birth
def test_init_births_a_soul(tmp_path):
    repo = Repository.init(tmp_path, with_soul=True)
    sid = repo.soul_id()
    assert sid and len(sid) == 64                      # 32-byte hex pubkey
    # the secret seed exists but lives outside the versioned tree
    assert (repo.dir / "soul" / "seed.secret").exists()
    assert (repo.dir / "soul" / "soul.pub").read_text().strip() == sid


def test_two_repos_get_distinct_souls(tmp_path):
    a = Repository.init(tmp_path / "a", with_soul=True)
    b = Repository.init(tmp_path / "b", with_soul=True)
    assert a.soul_id() != b.soul_id()


# ------------------------------------------------------ crypto is opt-in (default off)
def test_default_init_has_no_soul(tmp_path):
    repo = Repository.init(tmp_path)
    assert repo.soul_id() is None
    assert not (repo.dir / "soul").exists()


def test_default_commit_is_unsigned(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n")
    oid = repo.commit("work")
    c = repo.objects.read_obj(oid)
    assert not soul.is_signed(c)
    assert "soul" not in c and "signature" not in c
    # an unsigned commit is "unsigned", never "FORGED"
    assert soul.verify_commit(c) is False


def test_default_freeze_mints_no_sbt(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n")
    (tmp_path / "test_x.py").write_text("def test(): assert 1 == 1\n")
    m = repo.read_manifest()
    m["goal"] = "ship a verified react widget"
    m["eval"] = {"command": sys.executable + " -m pytest -q"}
    (tmp_path / "agent.json").write_text(json.dumps(m))
    oid = repo.commit("work")
    run_eval(repo, oid)
    crystallize(repo)
    assert sbt.read_sbts(repo) == []


def test_default_init_agents_md_has_no_soul_section(tmp_path):
    Repository.init(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()
    assert "Soul" not in text and "Soulbound" not in text


def test_with_soul_init_agents_md_has_soul_section(tmp_path):
    Repository.init(tmp_path, with_soul=True)
    text = (tmp_path / "AGENTS.md").read_text()
    assert "Your Soul" in text and "Soulbound Tokens" in text


# --------------------------------------------------------------- signed commits
def _commit(tmp_path, goal="solve a hard backend migration", with_eval=False):
    repo = Repository.init(tmp_path, with_soul=True)
    (tmp_path / "main.py").write_text("x = 1\n")
    m = repo.read_manifest()
    m["goal"] = goal
    if with_eval:
        (tmp_path / "test_x.py").write_text("def test(): assert 1 == 1\n")
        m["eval"] = {"command": sys.executable + " -m pytest -q"}
    (tmp_path / "agent.json").write_text(json.dumps(m))
    oid = repo.commit("work")
    return repo, oid


def test_commit_is_signed_and_verifies(tmp_path):
    repo, oid = _commit(tmp_path)
    c = repo.objects.read_obj(oid)
    assert soul.is_signed(c)
    assert c["soul"] == repo.soul_id()
    assert soul.verify_commit(c)


def test_forged_commit_is_rejected(tmp_path):
    repo, oid = _commit(tmp_path)
    c = repo.objects.read_obj(oid)
    c["message"] = "I did this important work (I did not)"
    assert not soul.verify_commit(c)                   # content no longer matches sig


def test_commit_signed_by_other_soul_is_rejected(tmp_path):
    repo, oid = _commit(tmp_path / "real")
    c = repo.objects.read_obj(oid)
    # an impostor copies the trace but stamps their own soul id over it
    impostor = Repository.init(tmp_path / "impostor", with_soul=True)
    c["soul"] = impostor.soul_id()
    assert not soul.verify_commit(c)                   # sig doesn't match the new id


# --------------------------------------------------------------- SBT issuance
def test_verified_freeze_mints_an_sbt(tmp_path):
    repo, oid = _commit(tmp_path, goal="ship a verified react widget", with_eval=True)
    run_eval(repo, oid)
    new_oid, _art = crystallize(repo)
    sbts = sbt.read_sbts(repo)
    assert len(sbts) == 1
    token = sbts[0]
    assert token["soul"] == repo.soul_id()
    assert token["commit"] == new_oid
    assert token["self_issued"] is True
    assert "react" in token["skill"]
    assert sbt.verify_sbt(token)


def test_unverified_force_freeze_mints_nothing(tmp_path):
    # no eval declared → recipe is unverified → no SBT
    repo, oid = _commit(tmp_path, goal="unproven thing")
    crystallize(repo, force=True)
    assert sbt.read_sbts(repo) == []


def test_forged_sbt_is_rejected(tmp_path):
    repo, oid = _commit(tmp_path, goal="legit accomplishment", with_eval=True)
    run_eval(repo, oid)
    crystallize(repo)
    token = sbt.read_sbts(repo)[0]
    token["score"] = 9.99                              # inflate the grade
    assert not sbt.verify_sbt(token)


def test_external_issuer_signs_sbt(tmp_path):
    repo, oid = _commit(tmp_path, goal="audited by an oracle", with_eval=True)
    run_eval(repo, oid)
    new_oid = repo.head_commit()
    issuer_seed = bytes(range(99, 131))[:32]
    token = sbt.issue_sbt(repo, new_oid, repo.read_eval(new_oid),
                          goal_text="audited by an oracle", issuer_seed=issuer_seed)
    assert token["self_issued"] is False
    assert token["issuer"] == ed.publickey(issuer_seed).hex()
    assert token["issuer"] != repo.soul_id()
    assert sbt.verify_sbt(token)


def test_skill_profile_aggregates_scores(tmp_path):
    repo, oid = _commit(tmp_path, goal="react frontend work", with_eval=True)
    run_eval(repo, oid)
    crystallize(repo)
    prof = sbt.skill_profile(repo)
    assert prof["react"] == pytest.approx(1.0)


# --------------------------------------------------------------- merge still signs
def test_merge_commit_is_signed(tmp_path):
    from agentvcs.merge import merge
    repo, _ = _commit(tmp_path, goal="base")
    repo.branch("feature")
    repo.checkout("feature")
    (tmp_path / "feat.py").write_text("y = 2\n")
    repo.commit("feature work")
    repo.checkout("main")
    (tmp_path / "main2.py").write_text("z = 3\n")
    repo.commit("main work")
    result = merge(repo, "feature", force=True)
    if result.get("commit"):
        c = repo.objects.read_obj(result["commit"])
        assert soul.is_signed(c) and soul.verify_commit(c)
