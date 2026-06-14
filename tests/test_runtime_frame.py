"""The runtime-visibility layer: reconstruct what the closed runtime hides."""
import json

from agentvcs.runtime.frame import build_frame
from agentvcs.traces import claude_code


def _claude_transcript(cwd):
    return "\n".join(json.dumps(o) for o in [
        {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "t1",
         "message": {"role": "user", "content": "build a refunds queue"}},
        {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "t2",
         "message": {"role": "assistant", "model": "claude-opus-4-8",
                     "usage": {"input_tokens": 1000, "output_tokens": 200,
                               "cache_read_input_tokens": 5000},
                     "content": [{"type": "text", "text": "on it"},
                                 {"type": "tool_use", "name": "Bash", "input": {}},
                                 {"type": "tool_use", "name": "Task",
                                  "input": {"subagent_type": "Explore"}}]}},
        {"type": "assistant", "cwd": cwd, "uuid": "a2", "timestamp": "t3",
         "isSidechain": True,
         "message": {"role": "assistant", "model": "claude-haiku-4-5",
                     "usage": {"input_tokens": 300, "output_tokens": 50},
                     "content": [{"type": "text", "text": "exploring"}]}},
        {"type": "summary", "isCompactSummary": True, "summary": "compacted earlier turns"},
    ]) + "\n"


def test_build_frame_from_usages():
    msgs = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {}}]}]
    usages = [{"model": "claude-opus-4-8", "input": 1000, "output": 200, "cache_read": 5000},
              {"model": "claude-haiku-4-5", "input": 300, "output": 50}]
    frame = build_frame(msgs, usages=usages, compactions=1,
                        subagents=[{"type": "Explore", "count": 1}],
                        budget={"ceiling_usd": 0.10})

    assert frame["turns"] == 2
    assert frame["budget"]["tokens_in"] == 1300
    assert frame["budget"]["tokens_out"] == 250
    assert frame["budget"]["tokens_total"] == 1550
    # opus 1000/1e6*15 + 200/1e6*75 = 0.03 ; haiku 300/1e6*.8 + 50/1e6*4 = 0.00044
    assert abs(frame["budget"]["cost_usd"] - 0.03044) < 1e-9
    assert abs(frame["budget"]["remaining_usd"] - 0.06956) < 1e-9
    assert frame["budget"]["over_budget"] is False
    # context: window 200k, peak the model saw = 1000 + 5000 cache = 6000
    assert frame["context"]["window"] == 200_000
    assert frame["context"]["used"] == 6000
    assert frame["context"]["pct"] == 3.0
    assert frame["context"]["compactions"] == 1
    assert {m["model"] for m in frame["models"]} == {"claude-opus-4-8", "claude-haiku-4-5"}
    assert frame["subagents"] == [{"type": "Explore", "count": 1}]


def test_over_budget_flags():
    frame = build_frame([], usages=[{"model": "claude-opus-4-8", "input": 0, "output": 100000}],
                        budget={"ceiling_usd": 1.0})
    # 100k output * $75/Mtok = $7.50 > $1.00 ceiling
    assert frame["budget"]["over_budget"] is True
    assert frame["budget"]["remaining_usd"] < 0


def test_pricing_override():
    frame = build_frame([], usages=[{"model": "mystery-model", "input": 1_000_000, "output": 0}],
                        budget={"pricing": {"mystery": [2.0, 8.0]}})
    assert frame["budget"]["cost_usd"] == 2.0


def test_unknown_model_cost_is_none_but_tokens_count():
    frame = build_frame([], usages=[{"model": "totally-unknown", "input": 500, "output": 100}])
    assert frame["budget"]["tokens_total"] == 600
    assert frame["budget"]["cost_usd"] is None  # no price -> honest about not knowing


def test_claude_provider_reconstructs_frame(tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_text(_claude_transcript("/work/proj"))
    frame = claude_code.runtime({"provider": "claude-code", "path": str(t)}, tmp_path,
                                budget={"ceiling_usd": 0.10})

    assert frame["turns"] == 2
    assert frame["budget"]["tokens_total"] == 1550
    assert frame["context"]["compactions"] == 1
    # the Task tool call is surfaced as subagent fan-out the runtime never showed
    assert frame["subagents"] == [{"type": "Explore", "count": 1}]
    tool_names = {t["name"] for t in frame["tools"]}
    assert {"Bash", "Task"} <= tool_names
