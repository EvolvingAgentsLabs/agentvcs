"""Vercel eve provider — third runtime, same on-disk format.

Proves agentvcs versions a filesystem-first eve agent: the bundled hook dumps
eve's stream events to JSONL, this provider normalizes them to the exact same
``{role, content, ...}`` shape the Claude Code and qwen-code providers emit, and
the rest of agentvcs never learns it came from eve.
"""
import json

from agentvcs import Repository, crystallize
from agentvcs.traces import vercel_eve, pull_trace


def _trace_lines(include_failure=True):
    evs = [
        {"ts": 1, "type": "session.started",
         "data": {"input": {"message": "Add a refund handler tool."}}},
        {"ts": 2, "type": "message.completed",
         "data": {"model": "claude-opus-4-8", "reasoning": "base case first",
                  "message": "Creating the refund tool.",
                  "toolCalls": [{"name": "write_file",
                                 "input": {"path": "agent/tools/refund.ts"}}],
                  "usage": {"inputTokens": 1820, "outputTokens": 240,
                            "cacheReadTokens": 16000}}},
        {"ts": 3, "type": "action.result",
         "data": {"name": "write_file", "result": {"ok": True}}},
        {"ts": 4, "type": "message.completed",
         "data": {"model": "claude-opus-4-8", "message": "Done, build is green.",
                  "usage": {"inputTokens": 2100, "outputTokens": 90}}},
    ]
    if include_failure:
        evs += [
            {"ts": 5, "type": "message.completed",
             "data": {"model": "claude-opus-4-8",
                      "message": "Using Vercel's dedupe API.",
                      "toolCalls": [{"name": "write_file",
                                     "input": {"path": "agent/tools/refund.ts"}}],
                      "usage": {"inputTokens": 2600, "outputTokens": 310}}},
            {"ts": 6, "type": "action.result",
             "data": {"name": "build", "isError": True,
                      "error": "Cannot find module '@vercel/magic-dedupe'"}},
            {"ts": 7, "type": "turn.failed",
             "data": {"model": "claude-opus-4-8",
                      "error": "build failed: unresolved import"}},
        ]
    return "\n".join(json.dumps(e) for e in evs) + "\n"


def _write_log(workdir, **kw):
    log = workdir / ".eve" / "agentvcs" / "trace.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_trace_lines(**kw))
    return log


def _decl(**kw):
    return {"provider": "vercel-eve", "auto": True, "model": "claude-opus-4-8", **kw}


# ----------------------------------------------------------------- normalizing
def test_pull_normalizes_eve_events(tmp_path):
    _write_log(tmp_path, include_failure=False)
    msgs = vercel_eve.pull(_decl(), tmp_path)

    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # inbound user turn from session.started
    assert msgs[0]["content"] == "Add a refund handler tool."
    # model turn: thinking + text + tool_use, in order
    blocks = msgs[1]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "base case first"}
    assert blocks[1] == {"type": "text", "text": "Creating the refund tool."}
    assert blocks[2]["type"] == "tool_use" and blocks[2]["name"] == "write_file"
    assert blocks[2]["input"] == {"path": "agent/tools/refund.ts"}
    # action.result -> tool_result turn (role user, same as Anthropic interleave)
    assert msgs[2]["content"][0]["type"] == "tool_result"
    # a lone-text model turn collapses to a string, like a file trace
    assert msgs[3]["content"] == "Done, build is green."
    assert msgs[1]["model"] == "claude-opus-4-8"


def test_failure_is_visible_in_trace(tmp_path):
    """turn.failed must surface as a turn — it's the step a dev rolls back to."""
    _write_log(tmp_path, include_failure=True)
    msgs = vercel_eve.pull(_decl(), tmp_path)
    text = json.dumps(msgs)
    assert "magic-dedupe" in text          # the hallucinated import is captured
    assert any("turn.failed" in json.dumps(m.get("content")) for m in msgs)
    # the erroring tool return is flagged
    assert any(
        isinstance(m["content"], list) and m["content"][0].get("is_error")
        for m in msgs if isinstance(m["content"], list)
        and m["content"][0].get("type") == "tool_result"
    )


def test_registry_resolves_eve(tmp_path):
    _write_log(tmp_path)
    assert len(pull_trace(_decl(), tmp_path)) == 7


def test_explicit_path_and_session_pin(tmp_path):
    log = tmp_path / "custom.jsonl"
    log.write_text(_trace_lines(include_failure=False))
    assert len(vercel_eve.pull(_decl(path=str(log)), tmp_path)) == 4


def test_missing_log_is_empty_not_error(tmp_path):
    assert vercel_eve.pull(_decl(), tmp_path) == []
    info = vercel_eve.describe(_decl(), tmp_path)
    assert info["exists"] is False and info["messages"] == 0


def test_discovery_scans_eve_dir(tmp_path):
    # hook pointed somewhere non-canonical under .eve/ — fallback scan finds it
    log = tmp_path / ".eve" / "runs" / "agentvcs.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(_trace_lines(include_failure=False))
    assert len(vercel_eve.pull(_decl(), tmp_path)) == 4


def test_redaction_scrubs_secrets(tmp_path):
    log = tmp_path / ".eve" / "agentvcs" / "trace.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({
        "ts": 1, "type": "message.completed",
        "data": {"model": "claude-opus-4-8",
                 "message": "key is sk-ant-abcdef0123456789ABCDEF"}}) + "\n")
    msgs = vercel_eve.pull(_decl(), tmp_path)
    assert "sk-ant-" not in json.dumps(msgs)
    assert "[REDACTED]" in json.dumps(msgs)


# ----------------------------------------------------------------- runtime frame
def test_runtime_frame_from_eve(tmp_path):
    _write_log(tmp_path, include_failure=False)
    frame = vercel_eve.runtime(_decl(), tmp_path, budget={"ceiling_usd": 5.0})

    assert frame["budget"]["tokens_in"] == 1820 + 2100
    assert frame["budget"]["tokens_out"] == 240 + 90
    assert frame["turns"] == 2
    assert [t["name"] for t in frame["tools"]] == ["write_file"]
    routed = {m["model"]: m for m in frame["models"]}
    assert routed["claude-opus-4-8"]["turns"] == 2


# ----------------------------------------------------------------- end to end
def test_commit_and_crystallize_eve_agent(tmp_path):
    """The whole pipeline runs on an eve trace with zero eve-specific code."""
    (tmp_path / "agent" / "tools").mkdir(parents=True)
    (tmp_path / "agent" / "tools" / "refund.ts").write_text("// refund tool\n")
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": "maintain a refund queue",
        "models": [{"provider": "anthropic", "model": "claude-opus-4-8"}],
        "trace": _decl(),
        "state": "fluid",
    }))
    (tmp_path / ".agentvcsignore").write_text(".eve\n")
    _write_log(tmp_path, include_failure=False)

    repo = Repository.init(tmp_path)
    oid = repo.commit("turn 1: add refund tool")
    commit = repo.objects.read_obj(oid)
    msgs = repo.objects.read_obj(commit["trace"])["messages"]
    assert len(msgs) == 4
    # .eve must be ignored by the code dimension (captured as trace instead)
    tree = repo.objects.read_obj(commit["tree"])["entries"]
    assert not any(k.startswith(".eve") for k in tree)
    assert "agent/tools/refund.ts" in tree
