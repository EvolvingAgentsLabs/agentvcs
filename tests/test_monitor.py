"""Live terminal feedback (watch/statusline) and the dashboard runtime endpoint."""
import json

from agentvcs import Repository, crystallize
from agentvcs import monitor
from agentvcs.ui import api


def _transcript(cwd, in_tok=1000, out_tok=200):
    return "\n".join(json.dumps(o) for o in [
        {"type": "user", "cwd": cwd, "uuid": "u1", "timestamp": "t1",
         "message": {"role": "user", "content": "build it"}},
        {"type": "assistant", "cwd": cwd, "uuid": "a1", "timestamp": "t2",
         "message": {"role": "assistant", "model": "claude-opus-4-8",
                     "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                     "content": [{"type": "text", "text": "done"},
                                 {"type": "tool_use", "name": "Bash", "input": {}}]}},
    ]) + "\n"


def _runtime_repo(tmp_path, ceiling=0.10, in_tok=1000, out_tok=200, goal="build a refunds queue"):
    repo = Repository.init(tmp_path)
    t = tmp_path / "s.jsonl"
    t.write_text(_transcript(str(tmp_path), in_tok, out_tok))
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": goal, "mode": "runtime",
        "models": [{"provider": "anthropic", "auto": True}],
        "trace": {"provider": "claude-code", "path": str(t)},
        "budget": {"ceiling_usd": ceiling}, "state": "fluid"}))
    return repo


def test_render_panel_shows_budget_context_recall(tmp_path):
    repo = _runtime_repo(tmp_path)
    panel = monitor.render_panel(repo, color=False)
    assert "budget" in panel and "tok" in panel
    assert "context" in panel
    assert "Bash" in panel                      # tool usage surfaced
    assert "recall" in panel                    # the reflex line is always shown
    assert "[" in panel and "]" in panel        # a bar was drawn (ceiling set)


def test_render_panel_warns_when_over_budget(tmp_path):
    # 200k output * $75/Mtok = $15 >> $0.01 ceiling
    repo = _runtime_repo(tmp_path, ceiling=0.01, in_tok=0, out_tok=200_000)
    panel = monitor.render_panel(repo, color=False)
    assert "OVER BUDGET" in panel


def test_statusline_is_one_compact_line(tmp_path):
    repo = _runtime_repo(tmp_path)
    line = monitor.statusline(repo, color=False)
    assert "\n" not in line
    assert "tok" in line and "⬡" in line


def test_statusline_flags_recall_hit(tmp_path):
    repo = _runtime_repo(tmp_path, goal="build a Stripe billing system")
    repo.commit("v1")
    crystallize(repo)                            # freeze a recipe for this goal
    line = monitor.statusline(repo, color=False)
    assert "recall" in line                      # the frozen recipe is advertised


def test_color_adds_ansi_only_when_requested(tmp_path):
    repo = _runtime_repo(tmp_path)
    assert "\033[" in monitor.render_panel(repo, color=True)
    assert "\033[" not in monitor.render_panel(repo, color=False)


# ----------------------------------------------------- dashboard runtime endpoint
def test_api_runtime_endpoint(tmp_path):
    repo = _runtime_repo(tmp_path)
    status, body = api.handle(repo, ["runtime"], {})
    assert status == 200 and body["ok"]
    assert body["runtime"]["budget"]["tokens_total"] == 1200
    assert body["runtime"]["context"]["window"] == 200_000


def test_commit_view_includes_runtime(tmp_path):
    from agentvcs import views
    repo = _runtime_repo(tmp_path)
    oid = repo.commit("v1")
    view = views.commit_view(repo, oid)
    assert view["runtime"] is not None
    assert view["runtime"]["budget"]["tokens_total"] == 1200
