"""Tests for the Anthropic Managed Agents trace provider: normalizing the managed
session event stream, redaction, runtime-frame reconstruction from model_usage,
the exported-file format variants, live auto_fetch (mocked), and E2E commit."""
import json


from agentvcs import Repository
from agentvcs.traces import anthropic_managed as am
from agentvcs.traces import pull_trace


def _events():
    return [
        {"type": "user.message", "id": "e1", "processed_at": "t1",
         "content": [{"type": "text", "text": "pay supplier ACME for invoice 42"}]},
        {"type": "agent.thinking", "id": "e2",
         "content": [{"type": "thinking", "thinking": "verify KYC before paying"}]},
        {"type": "agent.message", "id": "e3", "model": "claude-opus-4-8",
         "content": [{"type": "text", "text": "Verifying KYC, then paying."}]},
        {"type": "agent.tool_use", "id": "e4",
         "content": [{"type": "tool_use", "id": "tu1", "name": "wire_transfer",
                      "input": {"amount": 900, "api_key": "sk-SECRET-xyz"}}]},
        {"type": "span.model_request_end",
         "model_usage": {"model": "claude-opus-4-8", "input_tokens": 1200,
                         "output_tokens": 300, "cache_read_input_tokens": 100}},
        {"type": "agent.tool_result", "id": "e5",
         "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok, paid"}]},
        {"type": "agent.thread_message_sent", "data": {"thread": "researcher"}},
    ]


def _write_events(workdir, events, name="events.jsonl"):
    d = workdir / ".anthropic" / "agentvcs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


# ------------------------------------------------------------------- normalize
def test_pull_normalizes_managed_event_stream(tmp_path):
    path = _write_events(tmp_path, _events())
    msgs = am.pull({"provider": "anthropic-managed", "path": str(path)}, tmp_path)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    # user turn collapses to a string
    assert msgs[0]["content"] == "pay supplier ACME for invoice 42"
    # the thinking → message → tool_use events collapse into ONE assistant turn
    blocks = msgs[1]["content"]
    assert [b["type"] for b in blocks] == ["thinking", "text", "tool_use"]
    assert blocks[2]["name"] == "wire_transfer"
    assert msgs[1]["model"] == "claude-opus-4-8"
    # the tool return is its own user(tool_result) turn
    assert msgs[2]["content"][0]["type"] == "tool_result"


def test_pull_redacts_secrets(tmp_path):
    path = _write_events(tmp_path, _events())
    msgs = am.pull({"provider": "anthropic-managed", "path": str(path),
                    "redact": ["sk-[A-Za-z0-9-]+"]}, tmp_path)
    blob = json.dumps(msgs)
    assert "sk-SECRET-xyz" not in blob
    assert "[REDACTED]" in blob


def test_discovery_without_explicit_path(tmp_path):
    _write_events(tmp_path, _events())  # canonical .anthropic/agentvcs/events.jsonl
    msgs = am.pull({"provider": "anthropic-managed", "auto": True}, tmp_path)
    assert len(msgs) == 3


def test_describe_reports_source_and_model(tmp_path):
    path = _write_events(tmp_path, _events())
    info = am.describe({"provider": "anthropic-managed", "path": str(path),
                        "session": "ses_abc"}, tmp_path)
    assert info["exists"] is True
    assert info["messages"] == 3
    assert info["model"] == "claude-opus-4-8"
    assert info["session"] == "ses_abc"


# ------------------------------------------------------------------- runtime
def test_runtime_reconstructs_budget_and_subagents(tmp_path):
    path = _write_events(tmp_path, _events())
    frame = am.runtime({"provider": "anthropic-managed", "path": str(path)}, tmp_path,
                       budget={"ceiling_usd": None})
    b = frame["budget"]
    assert b["tokens_out"] == 300
    assert b["tokens_in"] >= 1200
    assert b["tokens_total"] >= 1500
    assert any(s["type"] == "researcher" for s in frame["subagents"])


# ------------------------------------------------------------------- file formats
def test_reads_data_envelope(tmp_path):
    d = tmp_path / ".anthropic" / "agentvcs"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(json.dumps({"data": _events()}))
    msgs = am.pull({"provider": "anthropic-managed", "auto": True}, tmp_path)
    assert len(msgs) == 3


def test_reads_bare_json_array(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(json.dumps(_events()))
    msgs = am.pull({"provider": "anthropic-managed", "path": str(path)}, tmp_path)
    assert len(msgs) == 3


def test_no_events_returns_empty(tmp_path):
    # nothing on disk, no auto_fetch → [] (a brand-new agent, not an error)
    assert am.pull({"provider": "anthropic-managed", "session": "ses_x"}, tmp_path) == []


# ------------------------------------------------------------------- live fetch
def test_auto_fetch_uses_api_when_no_file(tmp_path, monkeypatch):
    captured = {}

    def fake_fetch(decl):
        captured["decl"] = decl
        return _events()

    monkeypatch.setattr(am, "_fetch_events", fake_fetch)
    msgs = am.pull({"provider": "anthropic-managed", "auto_fetch": True,
                    "session": "ses_live"}, tmp_path)
    assert len(msgs) == 3
    assert captured["decl"]["session"] == "ses_live"


def test_no_auto_fetch_does_not_hit_api(tmp_path, monkeypatch):
    def boom(decl):
        raise AssertionError("must not fetch when auto_fetch is off")

    monkeypatch.setattr(am, "_fetch_events", boom)
    assert am.pull({"provider": "anthropic-managed", "session": "ses_x"}, tmp_path) == []


# ------------------------------------------------------------------- E2E commit
def test_commit_captures_managed_trace_and_autodetects_model(tmp_path):
    repo = Repository.init(tmp_path)
    path = _write_events(tmp_path, _events())
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "run the supplier-payments desk",
        "models": [{"provider": "anthropic", "auto": True}],
        "trace": {"provider": "anthropic-managed", "path": str(path)},
        "state": "fluid"}))
    oid = repo.commit("from a managed session")
    commit = repo.objects.read_obj(oid)
    assert commit["trace"] is not None
    trace_obj = repo.objects.read_obj(commit["trace"])
    assert len(trace_obj["messages"]) == 3
    # the model pin was auto-detected from what actually ran
    model_pin = repo.objects.read_obj(commit["models"][0])
    assert model_pin["model"] == "claude-opus-4-8"


def test_registered_in_provider_registry(tmp_path):
    path = _write_events(tmp_path, _events())
    # dispatches through the public registry, not just the module
    msgs = pull_trace({"provider": "anthropic-managed", "path": str(path)}, tmp_path)
    assert len(msgs) == 3
