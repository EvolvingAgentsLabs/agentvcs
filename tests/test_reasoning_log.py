"""Tests for agentvcs log --reasoning (Feature B)."""
import json
import time

import pytest

from agentvcs import Repository
from agentvcs.cli import build_parser


# ------------------------------------------------------------------ helpers

def setup_repo(tmp_path, goal="initial goal"):
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": goal,
        "models": [{"provider": "anthropic", "model": "claude-opus-4-8",
                    "params": {"temperature": 1.0}}],
        "trace": None,
        "state": "fluid",
    }))
    return repo


def commit_with(repo, tmp_path, goal=None, file_content=None, message="commit",
                trace_msgs=None):
    manifest = json.loads((tmp_path / "agent.json").read_text())
    if goal is not None:
        manifest["goal"] = goal
    if trace_msgs is not None:
        trace_path = tmp_path / "traces" / "run.jsonl"
        trace_path.parent.mkdir(exist_ok=True)
        trace_path.write_text(
            "\n".join(json.dumps(m) for m in trace_msgs) + "\n")
        manifest["trace"] = "traces/run.jsonl"
    (tmp_path / "agent.json").write_text(json.dumps(manifest))
    if file_content is not None:
        (tmp_path / "main.py").write_text(file_content)
    return repo.commit(message)


# ------------------------------------------------------------------ rollback ledger

def test_rollback_appends_to_ledger(tmp_path):
    """rollback() appends one entry to .agentvcs/rollbacks.jsonl."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, goal="goal A", message="A")
    b = commit_with(repo, tmp_path, goal="goal B", file_content="v2\n", message="B")

    repo.rollback()

    ledger_path = tmp_path / ".agentvcs" / "rollbacks.jsonl"
    assert ledger_path.exists()
    lines = [l for l in ledger_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["from"] == b
    assert entry["to"] == a
    assert "timestamp" in entry
    assert "reason" in entry


def test_two_rollbacks_both_in_ledger(tmp_path):
    """Two successive rollbacks both appear in rollbacks.jsonl."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, goal="goal A", message="A")
    b = commit_with(repo, tmp_path, goal="goal B", file_content="v2\n", message="B")
    c = commit_with(repo, tmp_path, goal="goal C", file_content="v3\n", message="C")

    repo.rollback()  # C -> B
    repo.rollback()  # B -> A

    entries = repo.read_rollbacks()
    assert len(entries) == 2
    assert entries[0]["from"] == c
    assert entries[0]["to"] == b
    assert entries[1]["from"] == b
    assert entries[1]["to"] == a


def test_read_rollbacks_empty(tmp_path):
    """read_rollbacks() returns [] when no rollbacks have occurred."""
    repo = setup_repo(tmp_path)
    commit_with(repo, tmp_path, message="A")
    assert repo.read_rollbacks() == []


# ------------------------------------------------------------------ log --reasoning JSON

def _run_log_reasoning(tmp_path, extra_args=None):
    """Run log --reasoning --json via the CLI and return the parsed ledger."""
    import io, sys
    from agentvcs.cli import main

    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(tmp_path)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        argv = ["log", "--reasoning", "--json"] + (extra_args or [])
        main(argv)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
        __import__("os").chdir(old_cwd)
    return json.loads(output)


def test_log_reasoning_goal_transitions(tmp_path):
    """Goal transitions appear in the reasoning ledger."""
    repo = setup_repo(tmp_path, goal="goal A")
    commit_with(repo, tmp_path, goal="goal A", message="first")
    commit_with(repo, tmp_path, goal="goal B", file_content="v2\n", message="second")

    result = _run_log_reasoning(tmp_path)
    assert result["ok"] is True
    ledger = result["ledger"]
    # Most recent commit first
    assert ledger[0]["goal"] == "goal B"
    assert ledger[1]["goal"] == "goal A"
    # Goal delta on the second commit (most recent)
    assert ledger[0]["goal_delta"] == "goal B"


def test_log_reasoning_eval_verdicts(tmp_path):
    """Eval verdicts appear in the reasoning ledger."""
    repo = setup_repo(tmp_path)
    oid = commit_with(repo, tmp_path, message="with eval")

    # Write a fake eval result
    repo.write_eval(oid, {
        "ok": True, "passed": 5, "total": 5, "score": 1.0,
        "command": "pytest -q", "results": []
    })

    result = _run_log_reasoning(tmp_path)
    ledger = result["ledger"]
    entry = next(e for e in ledger if e.get("commit") == oid)
    assert entry["eval"] is not None
    assert entry["eval"]["ok"] is True
    assert entry["eval"]["score"] == 1.0


def test_log_reasoning_rollbacks_interleaved(tmp_path):
    """Rollback events appear in the ledger interleaved with commits."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, goal="goal A", message="A")
    b = commit_with(repo, tmp_path, goal="goal B", file_content="v2\n", message="B")

    repo.rollback()  # B -> A

    result = _run_log_reasoning(tmp_path)
    ledger = result["ledger"]

    rollback_entries = [e for e in ledger if e.get("type") == "rollback"]
    assert len(rollback_entries) == 1
    rb = rollback_entries[0]
    assert rb["from"] == b
    assert rb["to"] == a


def test_log_reasoning_two_rollbacks_in_json(tmp_path):
    """Two successive rollbacks both appear in log --reasoning --json."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, goal="goal A", message="A")
    b = commit_with(repo, tmp_path, goal="goal B", file_content="v2\n", message="B")
    c = commit_with(repo, tmp_path, goal="goal C", file_content="v3\n", message="C")

    repo.rollback()  # C -> B
    repo.rollback()  # B -> A

    result = _run_log_reasoning(tmp_path)
    ledger = result["ledger"]

    rollback_entries = [e for e in ledger if e.get("type") == "rollback"]
    assert len(rollback_entries) == 2


def test_log_reasoning_crystallized_flag(tmp_path):
    """Crystallized commits are flagged in the ledger."""
    from agentvcs.crystallize import crystallize

    repo = setup_repo(tmp_path)
    commit_with(repo, tmp_path, message="fluid")
    crystallize(repo)

    result = _run_log_reasoning(tmp_path)
    ledger = result["ledger"]
    commit_entries = [e for e in ledger if e.get("type") != "rollback"]
    crystallized = [e for e in commit_entries if e.get("crystallized")]
    assert len(crystallized) >= 1
