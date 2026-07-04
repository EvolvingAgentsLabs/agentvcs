"""Tests for the odyssey trace provider (reads lovell-odyssey's missions.db)."""
import json
import sqlite3

from agentvcs.traces import odyssey, pull_trace, describe_trace

_MISSIONS_SCHEMA = """
CREATE TABLE missions (
    id TEXT PRIMARY KEY, name TEXT, status TEXT, run_json TEXT,
    created_at TEXT, started_at TEXT, completed_at TEXT, overall_grade REAL
);
"""


def _run_json(mission_id="m1", grade=1.0, success=1.0):
    return {
        "id": mission_id,
        "status": "COMPLETED",
        "overall_grade": grade,
        "created_at": "2026-07-04T16:00:00+00:00",
        "completed_at": "2026-07-04T16:05:00+00:00",
        "spec": {
            "objective": "Patrol the facility and report each checkpoint clear.",
            "robot": {"agents": [{"role": "PILOT", "model": {"base": "gemma-4-26b-a4b-it"}}]},
        },
        "tasks": [
            {"spec": {"kind": "training", "name": "warmup"}, "status": "COMPLETED",
             "result_summary": {"_mock": True}},
            {"spec": {"kind": "evaluation", "name": "patrol-eval"}, "status": "COMPLETED",
             "result_summary": {"success_rate": success, "passed": success >= 0.5}},
        ],
    }


def _make_db(path, *runs):
    con = sqlite3.connect(str(path))
    con.executescript(_MISSIONS_SCHEMA)
    for r in runs:
        con.execute(
            "INSERT INTO missions (id, name, status, run_json, created_at, completed_at, overall_grade)"
            " VALUES (?,?,?,?,?,?,?)",
            (r["id"], "patrol-2d", r["status"], json.dumps(r), r["created_at"],
             r["completed_at"], r["overall_grade"]),
        )
    con.commit()
    con.close()


def test_pull_normalizes_latest_mission(tmp_path):
    db = tmp_path / "missions.db"
    _make_db(db, _run_json("m1", grade=0.5, success=0.5), _run_json("m2", grade=1.0, success=1.0))

    msgs = odyssey.pull({"provider": "odyssey", "db": str(db)}, tmp_path)

    # user objective + 2 tasks + closing status
    assert len(msgs) == 4
    assert msgs[0]["role"] == "user"
    assert "Patrol the facility" in msgs[0]["content"]
    # latest mission (m2, ordered by created_at is equal here, but LIMIT 1 picks one)
    assert any("patrol-eval" in m["content"] for m in msgs)
    assert msgs[-1]["role"] == "assistant"
    assert "overall_grade=" in msgs[-1]["content"]
    # pilot model is pinned from the loadout
    assert msgs[1]["model"] == "gemma-4-26b-a4b-it"


def test_pull_by_mission_id(tmp_path):
    db = tmp_path / "missions.db"
    _make_db(db, _run_json("m1", grade=0.5, success=0.5), _run_json("m2", grade=1.0, success=1.0))

    msgs = odyssey.pull({"provider": "odyssey", "db": str(db), "mission": "m1"}, tmp_path)
    eval_msg = next(m for m in msgs if "patrol-eval" in m["content"])
    assert '"success_rate": 0.5' in eval_msg["content"]


def test_pull_via_registry_and_relative_db(tmp_path):
    _make_db(tmp_path / "missions.db", _run_json("m1"))
    # relative db resolves against the workdir
    msgs = pull_trace({"provider": "odyssey", "db": "missions.db"}, tmp_path)
    assert msgs and msgs[0]["role"] == "user"


def test_missing_db_returns_empty(tmp_path):
    assert odyssey.pull({"provider": "odyssey", "db": str(tmp_path / "nope.db")}, tmp_path) == []


def test_describe(tmp_path):
    db = tmp_path / "missions.db"
    _make_db(db, _run_json("m1"))
    info = describe_trace({"provider": "odyssey", "db": str(db)}, tmp_path)
    assert info["provider"] == "odyssey"
    assert info["exists"] is True
    assert info["messages"] == 4
    assert info["model"] == "gemma-4-26b-a4b-it"
