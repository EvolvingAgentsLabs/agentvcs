import pytest

import agentvcs as avcs
from conftest import manifest


def kinds(run):
    return [e["kind"] for e in run.log()]


def test_run_context_manager_writes_start_and_end(store):
    with avcs.run(manifest(), store=store, run_id="r1") as run:
        assert avcs.current_run() is run
        assert run.manifest["x.model"]["id"] == "m-1"
        assert run.manifest.kind("x.prompt") == "prompt"
    assert kinds(run) == ["run_start", "run_end"]
    assert run.log()[-1]["body"]["status"] == "completed"
    assert avcs.current_run_or_none() is None
    assert avcs.cli("verify", "r1", store=store)["valid"] is True


@pytest.mark.parametrize("exc, status", [(ValueError, "failed"), (KeyboardInterrupt, "aborted")])
def test_exception_ends_the_run_with_status_and_propagates(store, exc, status):
    with pytest.raises(exc):
        with avcs.run(manifest(), store=store, run_id="r") as run:
            raise exc()
    assert run.log()[-1]["body"]["status"] == status


def test_manifest_from_file_id_or_mapping_is_the_same_id(store, tmp_path):
    import json

    p = tmp_path / "m.json"
    p.write_text(json.dumps(manifest()))
    a = avcs.run(manifest(), store=store).start()
    b = avcs.run(p, store=store).start()
    c = avcs.run(a.manifest.id, store=store).start()
    assert a.manifest.id == b.manifest.id == c.manifest.id
    assert a.run_id != b.run_id


def test_unknown_manifest_id_raises_with_code(store):
    with pytest.raises(avcs.AgentvcsError) as ei:
        avcs.run("b3:" + "0" * 64, store=store).start()
    assert avcs.error_code(ei.value) == "E_NOT_FOUND"


def test_invalid_manifest_is_refused_by_the_core(store):
    bad = manifest()
    bad["dimensions"]["x.model"]["kind"] = "weights"
    with pytest.raises(avcs.AgentvcsError) as ei:
        avcs.run(bad, store=store).start()
    assert ei.value.code == "E_UNKNOWN_KIND"


def test_hash_json_matches_the_cli(store, tmp_path):
    import json

    v = {"b": [1, 2.0, "é"], "a": None}
    p = tmp_path / "v.json"
    p.write_text(json.dumps(v))
    assert avcs.hash_json(v) == avcs.cli("hash", str(p), "--canonical", store=store)["hash"]


def test_python_m_agentvcs_is_the_cli(store):
    from conftest import agentvcs_cli

    code, out = agentvcs_cli(store, "init")
    assert code == 0 and out == {"ok": True, "store": ".agentvcs"}
    code, out = agentvcs_cli(store, "verify", "nope")
    assert code == 4 and out["error"]["code"] == "E_NOT_FOUND"
