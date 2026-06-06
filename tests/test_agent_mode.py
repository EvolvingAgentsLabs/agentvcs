import json

import pytest

from agentvcs import Repository, RepoError
from agentvcs.cli import main
from agentvcs.mcp_server import handle


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out.strip()


# ------------------------------------------------------------- CLI --json
def test_json_success_shape(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "init", "--json")
    obj = json.loads(out)
    assert code == 0 and obj["ok"] is True and obj["command"] == "init"

    (tmp_path / "f.txt").write_text("a")
    code, out = run(capsys, "commit", "-m", "c1", "--json")
    obj = json.loads(out)
    assert obj["ok"] and obj["state"] == "fluid" and len(obj["commit"]) == 64


def test_json_error_has_stable_code(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "log", "--json")  # not a repo
    obj = json.loads(out)
    assert code == 1 and obj["ok"] is False and obj["error"]["code"] == "NOT_A_REPO"


def test_env_var_enables_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTVCS_JSON", "1")
    _, out = run(capsys, "init")  # no --json flag, env turns it on
    assert json.loads(out)["ok"] is True


def test_init_scaffolds_agents_md(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run(capsys, "init", "--json")
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "agent.json").exists()


def test_new_scaffolds_prewired_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    code, out = run(capsys, "new", str(proj), "--json")
    obj = json.loads(out)
    assert code == 0 and obj["ok"] and len(obj["commit"]) == 64
    # the project is already "using agentvcs" — the condition adoption needs
    assert (proj / ".agentvcs").is_dir()
    assert (proj / "agent.json").exists()
    assert (proj / "AGENTS.md").exists()
    assert (proj / ".mcp.json").exists()
    assert (proj / ".claude" / "skills" / "agentvcs" / "SKILL.md").exists()
    # first commit captured the real goal (not the placeholder)
    code, out = run(capsys, "log", "-C", str(proj), "--json")
    commits = json.loads(out)["commits"]
    assert len(commits) == 1 and "Triage" in commits[0]["goal"]


def test_new_refuses_existing_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    run(capsys, "new", str(proj), "--json")
    code, out = run(capsys, "new", str(proj), "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "ALREADY_REPO"


def test_dash_C_targets_repo_from_anywhere(tmp_path, monkeypatch, capsys):
    # an agent whose shell cwd is elsewhere can still drive a specific repo
    proj = tmp_path / "proj"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    # init creates the target dir; flag works both before and after the subcommand
    code, out = run(capsys, "-C", str(proj), "init", "--json")
    assert code == 0 and json.loads(out)["ok"] and (proj / ".agentvcs").is_dir()

    (proj / "f.txt").write_text("x")
    code, out = run(capsys, "commit", "-m", "c1", "-C", str(proj), "--json")
    assert code == 0 and json.loads(out)["ok"]
    # cwd is unchanged from the test's perspective is irrelevant; the repo got it
    code, out = run(capsys, "log", "-C", str(proj), "--json")
    assert len(json.loads(out)["commits"]) == 1


def test_dash_C_missing_dir_errors_for_non_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "status", "-C", str(tmp_path / "nope"), "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "BAD_DIR"


# ------------------------------------------------------------- rollback
def test_rollback_restores_and_is_reversible(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    a = repo.commit("a")
    (tmp_path / "f.txt").write_text("b")
    b = repo.commit("b")

    res = repo.rollback()
    assert res["restored_to"] == a and res["previous_head"] == b
    assert (tmp_path / "f.txt").read_text() == "a"
    assert (tmp_path / ".agentvcs" / "ROLLBACK_HEAD").read_text().strip() == b

    repo.checkout(b)  # the undo is reversible
    assert (tmp_path / "f.txt").read_text() == "b"


def test_rollback_without_parent_errors(tmp_path):
    repo = Repository.init(tmp_path)
    repo.commit("only")
    with pytest.raises(RepoError) as e:
        repo.rollback()
    assert e.value.code == "NO_PARENT"


# ------------------------------------------------------- ref resolution
def test_short_prefix_resolution(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    a = repo.commit("a")
    assert repo._resolve(a[:8], expect="commit") == a
    with pytest.raises(RepoError) as e:
        repo._resolve("zzzz", expect="commit")
    assert e.value.code == "BAD_REF"


# ------------------------------------------------------------- MCP server
def test_mcp_initialize_list_and_notification():
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["serverInfo"]["name"] == "agentvcs"
    assert r["result"]["capabilities"]["tools"] == {}

    r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"avcs_commit", "avcs_rollback", "avcs_freeze"} <= names
    # tool defs must not leak the private _fn
    assert all("_fn" not in t for t in r["result"]["tools"])

    # notifications get no reply
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    # unknown method -> JSON-RPC error
    assert handle({"jsonrpc": "2.0", "id": 9, "method": "bogus"})["error"]["code"] == -32601


def test_mcp_tool_call_success_and_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")

    r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "avcs_commit", "arguments": {"message": "m"}}})
    assert r["result"]["isError"] is False
    assert json.loads(r["result"]["content"][0]["text"])["ok"] is True

    r = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "avcs_show", "arguments": {"commit": "nope"}}})
    assert r["result"]["isError"] is True
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "BAD_REF"
