"""Trace provider for lovell-odyssey mission runs.

Reads odyssey's native SQLite store (``~/.odyssey/missions.db`` by default) and normalizes a
mission run into agentvcs's message list: the objective as the user turn, each task's
``result_summary`` as an assistant turn, and a closing status/overall_grade turn. This lets
agentvcs version *what the robot's mission actually produced* (success_rate, per-checkpoint
metrics) alongside the code + goal.

Declaration (in ``agent.json``)::

    "trace": {"provider": "odyssey", "db": "~/.odyssey/missions.db", "mission": "<id>"}

``db`` is optional (defaults to ``~/.odyssey/missions.db``; relative paths resolve against the
repo workdir). ``mission`` is optional (defaults to the most recent mission). Uses only the
stdlib (``sqlite3`` + ``json``), so agentvcs stays dependency-free and does not import odyssey.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_DEFAULT_DB = "~/.odyssey/missions.db"


def _db_path(decl: dict, workdir: Path) -> Path:
    p = Path(decl.get("db") or _DEFAULT_DB).expanduser()
    return p if p.is_absolute() else Path(workdir) / p


def _load_run(decl: dict, workdir: Path) -> dict | None:
    db = _db_path(decl, workdir)
    if not db.exists():
        return None
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        mission = decl.get("mission")
        if mission:
            row = con.execute(
                "SELECT run_json FROM missions WHERE id = ?", (mission,)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT run_json FROM missions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row:
        return None
    try:
        return json.loads(row["run_json"])
    except (ValueError, TypeError):
        return None


def _pilot_model(spec: dict) -> str:
    for agent in spec.get("robot", {}).get("agents", []):
        if agent.get("role") == "PILOT":
            return (agent.get("model") or {}).get("base", "") or ""
    return ""


def pull(decl: dict, workdir: Path) -> list:
    run = _load_run(decl, workdir)
    if not run:
        return []
    spec = run.get("spec", {})
    model = _pilot_model(spec)
    ts = run.get("completed_at") or run.get("created_at")

    messages: list[dict] = [
        {
            "role": "user",
            "content": (spec.get("objective") or "").strip() or "(no objective)",
            "model": "",
            "ts": run.get("created_at"),
        }
    ]
    for task in run.get("tasks", []):
        tspec = task.get("spec", {})
        summary = task.get("result_summary") or {}
        content = f"[{tspec.get('kind')}] {tspec.get('name')} -> {task.get('status')}"
        if summary:
            content += "\n" + json.dumps(summary, ensure_ascii=False)
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "model": model,
                "ts": task.get("completed_at") or ts,
            }
        )
    messages.append(
        {
            "role": "assistant",
            "content": f"mission {run.get('status')} overall_grade={run.get('overall_grade')}",
            "model": model,
            "ts": ts,
        }
    )
    return messages


def describe(decl: dict, workdir: Path) -> dict:
    db = _db_path(decl, workdir)
    run = _load_run(decl, workdir)
    return {
        "provider": "odyssey",
        "transcript": str(db),
        "exists": db.exists(),
        "messages": (len(run.get("tasks", [])) + 2) if run else 0,
        "model": _pilot_model(run.get("spec", {})) if run else "",
    }
