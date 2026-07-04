#!/usr/bin/env python3
"""Version a robotics mission run with agentvcs via the `odyssey` trace provider.

lovell-odyssey (https://github.com/lovellai-dev/odyssey) persists every mission run to a
SQLite store (``~/.odyssey/missions.db``). agentvcs's ``odyssey`` trace provider reads that
native store and normalizes a run — the objective, each task's ``result_summary``, and the
overall grade — into the trace dimension of a commit. So a commit versions not just the
agent's code + goal, but *what its mission actually produced* (success_rate, per-checkpoint
metrics).

This demo is self-contained: it fabricates a tiny odyssey-shaped ``missions.db`` (so you do
not need odyssey installed), points an agent.json at it, commits, and prints the captured
trace. Run it from anywhere:

    python demo.py
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from agentvcs import Repository

# --- 1. Fabricate an odyssey-shaped missions.db --------------------------------
# (In a real setup this is written by `odyssey run <mission.yaml>`.)

_MISSIONS_SCHEMA = """
CREATE TABLE missions (
    id TEXT PRIMARY KEY, name TEXT, status TEXT, run_json TEXT,
    created_at TEXT, started_at TEXT, completed_at TEXT, overall_grade REAL
);
"""

_RUN = {
    "id": "mission-001",
    "status": "COMPLETED",
    "overall_grade": 1.0,
    "created_at": "2026-07-04T16:00:00+00:00",
    "completed_at": "2026-07-04T16:05:00+00:00",
    "spec": {
        "objective": "Patrol the facility: visit every checkpoint and report it clear.",
        "robot": {"agents": [{"role": "PILOT", "model": {"base": "gemma-4-26b-a4b-it"}}]},
    },
    "tasks": [
        {"spec": {"kind": "training", "name": "warmup"}, "status": "COMPLETED",
         "result_summary": {"_mock": True}},
        {"spec": {"kind": "evaluation", "name": "patrol-eval"}, "status": "COMPLETED",
         "result_summary": {"success_rate": 1.0, "performance_score": 1.0,
                            "letter_grade": "A", "passed": True}},
    ],
}


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="odyssey-demo-"))

    db = work / "missions.db"
    con = sqlite3.connect(str(db))
    con.executescript(_MISSIONS_SCHEMA)
    con.execute(
        "INSERT INTO missions (id, name, status, run_json, created_at, completed_at, overall_grade)"
        " VALUES (?,?,?,?,?,?,?)",
        (_RUN["id"], "patrol-2d", _RUN["status"], json.dumps(_RUN),
         _RUN["created_at"], _RUN["completed_at"], _RUN["overall_grade"]),
    )
    con.commit()
    con.close()

    # --- 2. An agent.json whose trace is the odyssey provider ------------------
    manifest = {
        "goal": "Patrol the facility: visit every checkpoint and report it clear.",
        "models": [{"provider": "google", "model": "gemma-4-26b-a4b-it"}],
        "trace": {"provider": "odyssey", "db": "missions.db"},  # relative to the repo workdir
    }
    repo = Repository.init(work, manifest=json.dumps(manifest, indent=2))

    # --- 3. Commit — the odyssey run is captured as the trace dimension --------
    oid = repo.commit("baseline: patrol skill set")
    commit = repo.objects.read_obj(oid)
    trace = repo.objects.read_obj(commit["trace"])

    print(f"committed {oid[:12]} with an odyssey trace of {len(trace['messages'])} messages:\n")
    for m in trace["messages"]:
        print(f"  [{m['role']:>9}] {str(m['content']).splitlines()[0][:66]}")

    print(f"\nrepo: {work}")
    print("The commit now versions code + goal + the mission's real result_summary.")


if __name__ == "__main__":
    main()
