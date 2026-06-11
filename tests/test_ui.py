"""Tests for the local dashboard — the pure JSON API, the static asset, and one
end-to-end pass through a real socket. Standard library only, like the rest."""
import http.client
import json
import threading
from importlib.resources import files

import pytest

from agentvcs import Repository
from agentvcs.ui import api
from agentvcs.ui.server import build_server


def write_manifest(path, goal, models, trace=None, state="fluid"):
    (path / "agent.json").write_text(json.dumps({
        "goal": goal, "models": models, "trace": trace, "state": state,
    }))


@pytest.fixture
def repo(tmp_path):
    """A two-commit repo: a code+trace commit, then a goal-only change."""
    r = Repository.init(tmp_path)
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "run.jsonl").write_text(
        '{"role":"user","content":"scrape this"}\n'
        '{"role":"assistant","content":[{"type":"thinking","thinking":"the price is in .pdp"},'
        '{"type":"tool_use","name":"Bash","input":{"cmd":"curl"}}],"model":"claude-opus-4-8"}\n')
    write_manifest(tmp_path, "Build a scraper",
                   [{"provider": "anthropic", "model": "claude-opus-4-8",
                     "params": {"temperature": 1.0}}], trace="traces/run.jsonl")
    first = r.commit("first")
    write_manifest(tmp_path, "Build a scraper that also gets reviews",
                   [{"provider": "anthropic", "model": "claude-opus-4-8",
                     "params": {"temperature": 1.0}}], trace="traces/run.jsonl")
    second = r.commit("second")
    return r, first, second


# ------------------------------------------------------------------ API (pure)
def test_log_endpoint_newest_first(repo):
    r, first, second = repo
    status, body = api.handle(r, ["log"], {})
    assert status == 200 and body["ok"]
    ids = [c["commit"] for c in body["commits"]]
    assert ids == [second, first]
    assert body["commits"][0]["message"] == "second"
    assert set(body["commits"][0]) >= {"commit", "state", "timestamp", "message", "goal", "parents"}


def test_commit_endpoint_matches_show_shape(repo):
    r, first, second = repo
    status, body = api.handle(r, ["commit", second], {})
    assert status == 200
    c = body["commit"]
    assert c["goal"] == "Build a scraper that also gets reviews"
    assert c["models"][0]["model"] == "claude-opus-4-8"
    assert c["trace_messages"] == 2
    assert "trace" not in c  # summary endpoint stays light


def test_trace_endpoint_returns_blocks(repo):
    r, first, second = repo
    status, body = api.handle(r, ["commit", first, "trace"], {})
    assert status == 200
    trace = body["trace"]
    assert len(trace) == 2
    assert trace[0]["role"] == "user"
    block_types = [b["type"] for b in trace[1]["content"]]
    assert block_types == ["thinking", "tool_use"]


def test_diff_endpoint_isolates_goal_dimension(repo):
    r, first, second = repo
    status, body = api.handle(r, ["diff"], {"b": second})
    assert status == 200
    d = body["diff"]
    assert d["goal"]["to"] == "Build a scraper that also gets reviews"
    # only agent.json moves (it carries the goal); no source/model/trace change
    assert d["code"]["added"] == [] and d["code"]["modified"] == ["agent.json"]
    assert d["models"] is None and d["trace"] is None


def test_short_prefix_resolves(repo):
    r, first, second = repo
    status, body = api.handle(r, ["commit", second[:8]], {})
    assert status == 200 and body["commit"]["commit"] == second


def test_repo_endpoint(repo):
    r, first, second = repo
    status, body = api.handle(r, ["repo"], {})
    assert status == 200
    assert body["head"] == second
    assert body["current"] == "main"
    assert any(b["name"] == "main" for b in body["branches"])


def test_bad_ref_is_404(repo):
    r, _, _ = repo
    status, body = api.handle(r, ["commit", "deadbeef"], {})
    assert status == 404
    assert body["ok"] is False and body["error"]["code"] == "BAD_REF"


def test_unknown_route_is_400(repo):
    r, _, _ = repo
    status, body = api.handle(r, ["nope"], {})
    assert status == 400 and body["error"]["code"] == "BAD_ROUTE"


# ------------------------------------------------------------------ packaging
def test_index_html_is_packaged():
    html = (files("agentvcs.ui") / "index.html").read_text()
    assert "<!DOCTYPE html>" in html
    assert 'api("/log")' in html  # the SPA actually talks to the API


# ------------------------------------------------------------------ socket smoke
def test_server_serves_html_and_json(repo):
    r, first, second = repo
    httpd = build_server(r, "127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        assert b"<!DOCTYPE html>" in resp.read()

        conn.request("GET", "/api/log")
        resp = conn.getresponse()
        assert resp.status == 200
        payload = json.loads(resp.read())
        assert payload["ok"] and len(payload["commits"]) == 2
    finally:
        httpd.shutdown()
        httpd.server_close()
