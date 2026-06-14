"""qwen-code provider — the cross-runtime proof. Same on-disk format, second runtime."""
import hashlib
import json

from agentvcs import Repository, crystallize
from agentvcs.traces import qwen_code, pull_trace


def _checkpoint():
    return json.dumps([
        {"role": "user", "parts": [{"text": "build a refunds queue"}]},
        {"role": "model",
         "parts": [{"text": "on it"},
                   {"functionCall": {"name": "write_file", "args": {"path": "app.py"}}}],
         "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 300}},
        {"role": "user", "parts": [{"functionResponse": {"name": "write_file",
                                                         "response": {"ok": True}}}]},
    ])


def _decl(path, **kw):
    return {"provider": "qwen-code", "path": str(path), "model": "qwen3-coder-plus", **kw}


def test_pull_normalizes_gemini_content(tmp_path):
    cp = tmp_path / "checkpoint-default.json"
    cp.write_text(_checkpoint())
    msgs = qwen_code.pull(_decl(cp), tmp_path)

    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    # a lone text part collapses to a string (same shape as a file trace)
    assert msgs[0]["content"] == "build a refunds queue"
    # the model turn maps functionCall -> the same tool_use block Claude emits
    blocks = msgs[1]["content"]
    assert blocks[0] == {"type": "text", "text": "on it"}
    assert blocks[1]["type"] == "tool_use" and blocks[1]["name"] == "write_file"
    # functionResponse -> tool_result
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[1]["model"] == "qwen3-coder-plus"


def test_registry_resolves_qwen(tmp_path):
    cp = tmp_path / "checkpoint-default.json"
    cp.write_text(_checkpoint())
    msgs = pull_trace(_decl(cp), tmp_path)
    assert len(msgs) == 3


def test_runtime_frame_from_qwen(tmp_path):
    cp = tmp_path / "checkpoint-default.json"
    cp.write_text(_checkpoint())
    frame = qwen_code.runtime(_decl(cp), tmp_path, budget={"ceiling_usd": 1.0})

    assert frame["turns"] == 1
    assert frame["budget"]["tokens_in"] == 1200
    assert frame["budget"]["tokens_out"] == 300
    # qwen default price (0.40 / 1.20 per Mtok)
    assert abs(frame["budget"]["cost_usd"] - (1200 / 1e6 * 0.40 + 300 / 1e6 * 1.20)) < 1e-9
    assert frame["context"]["window"] == 262_144
    assert [t["name"] for t in frame["tools"]] == ["write_file"]
    assert frame["models"][0]["model"] == "qwen3-coder-plus"


def test_discovery_by_project_hash(tmp_path):
    workdir = tmp_path / "proj"
    workdir.mkdir()
    qdir = tmp_path / ".qwen"
    h = hashlib.sha256(str(workdir.resolve()).encode()).hexdigest()
    proj = qdir / "tmp" / h
    proj.mkdir(parents=True)
    (proj / "checkpoint-default.json").write_text(_checkpoint())

    path = qwen_code._resolve_checkpoint(
        {"provider": "qwen-code", "qwen_dir": str(qdir)}, workdir)
    assert path == proj / "checkpoint-default.json"


def test_discovery_falls_back_to_scan(tmp_path):
    # checkpoint filed under a hash that does NOT match the workdir (version drift)
    workdir = tmp_path / "proj"
    workdir.mkdir()
    qdir = tmp_path / ".qwen"
    weird = qdir / "tmp" / "some-other-hash"
    weird.mkdir(parents=True)
    (weird / "checkpoint-x.json").write_text(_checkpoint())

    path = qwen_code._resolve_checkpoint(
        {"provider": "qwen-code", "qwen_dir": str(qdir)}, workdir)
    assert path == weird / "checkpoint-x.json"


def test_logs_json_rows_also_parse(tmp_path):
    logs = tmp_path / "logs.json"
    logs.write_text(json.dumps([
        {"sessionId": "s", "messageId": 0, "type": "user",
         "message": "hello", "timestamp": "t"}]))
    msgs = qwen_code.pull(_decl(logs), tmp_path)
    assert msgs == [{"role": "user", "content": "hello", "model": None, "ts": "t"}]


# ---- cross-runtime parity: a qwen trace flows through the SAME downstream -----
def test_qwen_trace_commits_and_crystallizes(tmp_path):
    repo = Repository.init(tmp_path)
    cp = tmp_path / "checkpoint-default.json"
    cp.write_text(_checkpoint())
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "refunds", "models": [{"provider": "qwen", "model": "qwen3-coder-plus"}],
        "trace": _decl(cp), "state": "fluid"}))

    repo.commit("from qwen session")
    new_oid, _ = crystallize(repo)
    recipe = repo.objects.read_obj(repo.objects.read_obj(new_oid)["crystal"])
    # the qwen conversation crystallizes into a deterministic recipe, identically
    # to a Claude one — the core never knew which runtime produced it
    assert len(recipe["steps"]) == 3
    assert recipe["models"][0]["params"]["temperature"] == 0
