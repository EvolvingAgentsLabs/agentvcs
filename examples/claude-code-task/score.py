#!/usr/bin/env python3
"""Score whether an agent actually adopted the agentvcs loop in a sandbox.

Turns the qualitative "did the agent use it well?" question into a measurable
checklist, read straight from the agentvcs repo the agent produced.

    python3 score.py [sandbox_dir]      # default: ./sandbox
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sandbox = Path(sys.argv[1] if len(sys.argv) > 1 else "sandbox").resolve()


def avcs_log(cwd: Path):
    env = os.environ.copy()
    if shutil.which("avcs"):
        cmd = ["avcs", "log", "--json"]
    else:
        cmd = [sys.executable, "-m", "agentvcs.cli", "log", "--json"]
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "commits": []}


def line(ok: bool, label: str, detail: str = ""):
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {mark} {label}" + (f"  \033[2m{detail}\033[0m" if detail else ""))
    return ok


print(f"\n\033[1mScoring agentvcs adoption in:\033[0m {sandbox}\n")

adopted = (sandbox / ".agentvcs").is_dir()
if not adopted:
    line(False, "Adopted agentvcs", "no .agentvcs/ — agent never initialized a repo")
    print("\n\033[1mScore: 0/6\033[0m — the agent did not adopt agentvcs.\n")
    sys.exit(1)

log = avcs_log(sandbox)
commits = log.get("commits", [])
goals = [c.get("goal") for c in commits]
states = [c.get("state") for c in commits]
rolled_back = (sandbox / ".agentvcs" / "ROLLBACK_HEAD").exists()
crystallized = "crystallized" in states
froze_recipe = (sandbox / "crystal").is_dir() and any((sandbox / "crystal").glob("*.json"))

checks = [
    line(adopted, "Adopted agentvcs", "ran agentvcs init"),
    line(len(commits) >= 1, "Committed at least once", f"{len(commits)} commit(s)"),
    line(len(commits) >= 3, "Iterated (>=3 commits)", "one commit per feature"),
    line(len(set(g for g in goals if g)) > 1, "Evolved the goal dimension",
         f"{len(set(g for g in goals if g))} distinct goals"),
    line(rolled_back, "Used rollback to recover", "ROLLBACK_HEAD present"),
    line(crystallized or froze_recipe, "Crystallized the final solution",
         "a crystallized commit / recipe exists"),
]

score = sum(1 for c in checks if c)
print(f"\n\033[1mScore: {score}/6\033[0m")
if score >= 5:
    print("Strong signal: the agent drove the full agentvcs loop. 🎯\n")
elif score >= 3:
    print("Partial adoption: it versioned work but skipped part of the loop.\n")
else:
    print("Weak adoption: revisit the skill/AGENTS.md wording.\n")
sys.exit(0 if score >= 5 else 1)
