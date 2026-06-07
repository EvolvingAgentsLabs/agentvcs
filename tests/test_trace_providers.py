import json

import pytest

from agentvcs import Repository, RepoError
from agentvcs.traces import claude_code, pull_trace


# --- a couple of realistic Claude Code transcript lines (envelope + housekeeping)
def _transcript(cwd):
    return "\n".join(json.dumps(o) for o in [
        {"type": "mode", "mode": "default", "sessionId": "s"},                 # housekeeping
        {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "t1",
         "message": {"role": "user", "content": "build a refunds queue"}},
        {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "t2",
         "message": {"role": "assistant", "model": "claude-opus-4-8",
                     "content": [{"type": "text", "text": "on it"},
                                 {"type": "tool_use", "name": "Edit",
                                  "input": {"api_key": "sk-SECRET-123"}}]}},
        {"type": "ai-title", "aiTitle": "Refunds", "sessionId": "s"},          # housekeeping
    ]) + "\n"


def _make_projects(root, cwd, name="session.jsonl"):
    proj = root / cwd.replace("/", "-")
    proj.mkdir(parents=True)
    (proj / name).write_text(_transcript(cwd))
    return proj / name


def write_manifest(path, trace, models=None):
    (path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": models or [], "trace": trace, "state": "fluid"}))


# ------------------------------------------------------------------- provider
def test_pull_normalizes_and_drops_housekeeping(tmp_path):
    transcript = _make_projects(tmp_path / "projects", "/work/proj")
    msgs = claude_code.pull({"provider": "claude-code", "path": str(transcript)}, tmp_path)
    # only the user + assistant turns survive; mode/ai-title are dropped
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["model"] == "claude-opus-4-8"
    assert msgs[0]["uuid"] == "u1"


def test_pull_redacts_secrets(tmp_path):
    transcript = _make_projects(tmp_path / "projects", "/work/proj")
    msgs = claude_code.pull(
        {"provider": "claude-code", "path": str(transcript),
         "redact": ["sk-[A-Za-z0-9-]+"]}, tmp_path)
    blob = json.dumps(msgs)
    assert "sk-SECRET-123" not in blob
    assert "[REDACTED]" in blob


def test_discovery_by_encoded_dir_picks_newest(tmp_path):
    root = tmp_path / "projects"
    workdir = tmp_path / "work" / "proj"
    workdir.mkdir(parents=True)
    proj = root / str(workdir).replace("/", "-")
    proj.mkdir(parents=True)
    old = proj / "old.jsonl"; old.write_text(_transcript(str(workdir)))
    new = proj / "new.jsonl"; new.write_text(_transcript(str(workdir)))
    import os; os.utime(new, (10**9 + 100, 10**9 + 100)); os.utime(old, (10**9, 10**9))
    path = claude_code._resolve_transcript(
        {"provider": "claude-code", "projects_dir": str(root)}, workdir)
    assert path == new


def test_discovery_scans_by_cwd_when_encoding_misses(tmp_path):
    # transcript filed under a non-matching dir name, but its cwd points at workdir
    root = tmp_path / "projects"
    workdir = tmp_path / "work" / "proj"
    workdir.mkdir(parents=True)
    weird = root / "totally-different-name"
    weird.mkdir(parents=True)
    (weird / "s.jsonl").write_text(_transcript(str(workdir)))
    path = claude_code._resolve_transcript(
        {"provider": "claude-code", "projects_dir": str(root)}, workdir)
    assert path == weird / "s.jsonl"


def test_unknown_provider_raises_stable_code(tmp_path):
    with pytest.raises(RepoError) as e:
        pull_trace({"provider": "nope"}, tmp_path)
    assert e.value.code == "UNKNOWN_TRACE_PROVIDER"


# --------------------------------------------------------- end-to-end commit
def test_commit_captures_provider_trace_and_autodetects_model(tmp_path):
    repo = Repository.init(tmp_path)
    transcript = _make_projects(tmp_path / "projects", str(tmp_path))
    write_manifest(
        tmp_path,
        trace={"provider": "claude-code", "path": str(transcript)},
        models=[{"provider": "anthropic", "auto": True}])

    oid = repo.commit("from live session")
    commit = repo.objects.read_obj(oid)
    # trace captured straight from the transcript (no .jsonl maintained by hand)
    assert len(repo.objects.read_obj(commit["trace"])["messages"]) == 2
    # model pin auto-filled from the model that actually ran
    pin = repo.objects.read_obj(commit["models"][0])
    assert pin["model"] == "claude-opus-4-8"


def test_classic_string_trace_still_works(tmp_path):
    repo = Repository.init(tmp_path)
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "run.jsonl").write_text(
        '{"role":"planner","content":"plan"}\n')
    write_manifest(tmp_path, trace="traces/run.jsonl")
    oid = repo.commit("classic")
    commit = repo.objects.read_obj(oid)
    assert len(repo.objects.read_obj(commit["trace"])["messages"]) == 1


# ---------------------------------------------------------- default redaction
def test_default_redactions_scrub_known_secrets(tmp_path):
    secret = "sk-ant-" + "A1b2C3d4E5f6G7h8I9"   # looks like a real Anthropic key
    line = json.dumps({"type": "assistant", "cwd": "/w", "uuid": "x",
                       "message": {"role": "assistant",
                                   "content": "key is " + secret}})
    t = tmp_path / "s.jsonl"; t.write_text(line + "\n")
    # no explicit redact declared -> built-ins still apply
    msgs = claude_code.pull({"provider": "claude-code", "path": str(t)}, tmp_path)
    assert secret not in json.dumps(msgs)
    assert "[REDACTED]" in json.dumps(msgs)
    # redact:false opts out entirely
    raw = claude_code.pull({"provider": "claude-code", "path": str(t),
                            "redact": False}, tmp_path)
    assert secret in json.dumps(raw)


# ----------------------------------------------------------------- describe
def test_describe_and_trace_info(tmp_path):
    transcript = _make_projects(tmp_path / "projects", "/work/proj")
    decl = {"provider": "claude-code", "path": str(transcript)}
    d = claude_code.describe(decl, tmp_path)
    assert d["transcript"] == str(transcript)
    assert d["messages"] == 2 and d["model"] == "claude-opus-4-8"

    repo = Repository.init(tmp_path)
    write_manifest(tmp_path, trace=decl)
    info = repo.trace_info()
    assert info["kind"] == "provider" and info["messages"] == 2


# ------------------------------------------------------- freeze from provider
def test_freeze_crystallizes_provider_trace(tmp_path):
    from agentvcs import crystallize
    repo = Repository.init(tmp_path)
    transcript = _make_projects(tmp_path / "projects", str(tmp_path))
    write_manifest(tmp_path, trace={"provider": "claude-code", "path": str(transcript)},
                   models=[{"provider": "anthropic", "auto": True}])
    repo.commit("fluid from session")
    new_oid, artifact = crystallize(repo)
    new = repo.objects.read_obj(new_oid)
    assert new["state"] == "crystallized"
    recipe = repo.objects.read_obj(new["crystal"])
    assert len(recipe["steps"]) == 2                      # the real captured turns
    assert recipe["models"][0]["params"]["temperature"] == 0
    assert artifact.exists()


# --------------------------------------------------------------- cli surface
def test_cli_init_claude_code_writes_provider_manifest(tmp_path, capsys):
    from agentvcs.cli import main
    main(["-C", str(tmp_path), "init", "--claude-code", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["trace_provider"] == "claude-code"
    manifest = json.loads((tmp_path / "agent.json").read_text())
    assert manifest["trace"] == {"provider": "claude-code", "auto": True}


def test_cli_show_trace_renders_messages(tmp_path, capsys):
    from agentvcs.cli import main
    repo = Repository.init(tmp_path)
    transcript = _make_projects(tmp_path / "projects", str(tmp_path))
    write_manifest(tmp_path, trace={"provider": "claude-code", "path": str(transcript)})
    repo.commit("x")
    main(["-C", str(tmp_path), "show", "--trace", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["trace_messages"] == 2
    assert [m["role"] for m in out["trace"]] == ["user", "assistant"]
