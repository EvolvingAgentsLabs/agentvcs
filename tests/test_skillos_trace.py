import json
import os

from agentvcs import Repository, crystallize
from agentvcs.traces import skillos


# --- a realistic SkillOS agent-runtime session (the cognitive pipeline phases)
def _session():
    return "\n".join(json.dumps(o) for o in [
        {"phase": "ingress", "role": "intent-compiler", "agent": "ingress",
         "content": "Goal: build a top-keywords agent.", "model": "gemini-2.0-flash",
         "provider": "google", "ts": "t1"},
        {"phase": "planning", "role": "planner", "agent": "hwm-macro-planner",
         "content": "Subgoals: tokenize, count, return top-N.",
         "model": "gemini-2.0-flash", "provider": "google", "ts": "t2"},
        {"phase": "execution", "role": "tool", "agent": "sandbox-runner",
         "text": "ran tool.py -> ['error','crash']  api_key=sk-SECRET-123",
         "model": "gemini-2.0-flash", "ts": "t3"},
        {"note": "housekeeping with no content field, must be skipped"},
        {"phase": "egress", "role": "renderer", "agent": "egress",
         "message": "Done.", "model": "gemini-2.0-flash", "ts": "t4"},
    ]) + "\n"


def _write_session(d, name="20260613T181000.jsonl"):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(_session())
    return p


def write_manifest(path, trace, models=None):
    (path / "agent.json").write_text(json.dumps({
        "goal": "g", "models": models or [], "trace": trace, "state": "fluid"}))


# ------------------------------------------------------------------- provider
def test_pull_normalizes_phases_and_content_keys(tmp_path):
    sess = _write_session(tmp_path / ".skillos" / "sessions")
    msgs = skillos.pull({"provider": "skillos", "path": str(sess)}, tmp_path)
    # the no-content housekeeping line is dropped; content/text/message all read
    assert [m["phase"] for m in msgs] == ["ingress", "planning", "execution", "egress"]
    assert msgs[2]["content"].startswith("ran tool.py")     # read from "text"
    assert msgs[3]["content"] == "Done."                    # read from "message"
    assert msgs[1]["agent"] == "hwm-macro-planner"


def test_pull_redacts_secrets_by_default(tmp_path):
    sess = _write_session(tmp_path / ".skillos" / "sessions")
    msgs = skillos.pull(
        {"provider": "skillos", "path": str(sess),
         "redact": ["sk-[A-Za-z0-9-]+"]}, tmp_path)
    blob = json.dumps(msgs)
    assert "sk-SECRET-123" not in blob and "[REDACTED]" in blob


def test_autodiscovery_picks_newest_under_default_dirs(tmp_path):
    d = tmp_path / ".skillos" / "sessions"
    old = _write_session(d, "old.jsonl")
    new = _write_session(d, "new.jsonl")
    os.utime(old, (10**9, 10**9))
    os.utime(new, (10**9 + 100, 10**9 + 100))
    path = skillos._resolve_session({"provider": "skillos"}, tmp_path)
    assert path == new


def test_pin_a_session_by_stem(tmp_path):
    d = tmp_path / "runs"
    _write_session(d, "alpha.jsonl")
    _write_session(d, "beta.jsonl")
    path = skillos._resolve_session(
        {"provider": "skillos", "dir": "runs", "session": "beta"}, tmp_path)
    assert path is not None and path.stem == "beta"


def test_missing_session_returns_empty(tmp_path):
    assert skillos.pull({"provider": "skillos"}, tmp_path) == []


# ----------------------------------------------------------------- describe
def test_describe_reports_model_and_count(tmp_path):
    sess = _write_session(tmp_path / "sessions")
    d = skillos.describe({"provider": "skillos", "dir": "sessions"}, tmp_path)
    assert d["exists"] and d["messages"] == 4
    assert d["model"] == "gemini-2.0-flash"


# --------------------------------------------------------- end-to-end commit
def test_commit_captures_skillos_trace_and_autodetects_gemma_model(tmp_path):
    repo = Repository.init(tmp_path)
    # a Gemma (Ollama-local fallback) run this time — the pin must reflect it
    sess_dir = tmp_path / ".skillos" / "sessions"
    sess_dir.mkdir(parents=True)
    (sess_dir / "s.jsonl").write_text(
        json.dumps({"phase": "planning", "role": "planner",
                    "content": "plan", "model": "gemma4"}) + "\n")
    write_manifest(tmp_path,
                   trace={"provider": "skillos", "auto": True},
                   models=[{"provider": "ollama", "auto": True}])

    oid = repo.commit("fluid run on Gemma")
    commit = repo.objects.read_obj(oid)
    assert len(repo.objects.read_obj(commit["trace"])["messages"]) == 1
    pin = repo.objects.read_obj(commit["models"][0])
    assert pin["provider"] == "ollama" and pin["model"] == "gemma4"


# ----------------------------------------------------------------- cli surface
def test_cli_init_skillos_writes_provider_manifest(tmp_path, capsys):
    from agentvcs.cli import main
    main(["-C", str(tmp_path), "init", "--skillos", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["trace_provider"] == "skillos"
    manifest = json.loads((tmp_path / "agent.json").read_text())
    assert manifest["trace"] == {"provider": "skillos", "auto": True}
    # Gemini first, local Gemma/Ollama as the documented fallback
    assert manifest["models"][0]["provider"] == "google"
    assert manifest["models"][1]["model"] == "gemma4"


def test_cli_init_rejects_both_providers(tmp_path, capsys):
    from agentvcs.cli import main
    rc = main(["-C", str(tmp_path), "init", "--skillos", "--claude-code", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["ok"] is False and out["error"]["code"] == "BAD_USAGE"


def test_freeze_crystallizes_skillos_trace(tmp_path):
    repo = Repository.init(tmp_path)
    _write_session(tmp_path / ".skillos" / "sessions")
    write_manifest(tmp_path, trace={"provider": "skillos", "auto": True},
                   models=[{"provider": "google", "auto": True}])
    repo.commit("fluid")
    new_oid, artifact = crystallize(repo)
    new = repo.objects.read_obj(new_oid)
    assert new["state"] == "crystallized"
    recipe = repo.objects.read_obj(new["crystal"])
    assert len(recipe["steps"]) == 4
    assert recipe["models"][0]["params"]["temperature"] == 0
    assert artifact.exists()
