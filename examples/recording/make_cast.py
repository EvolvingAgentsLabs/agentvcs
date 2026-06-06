#!/usr/bin/env python3
"""Generate an asciinema v2 cast of the agent-loop demo — zero dependencies.

Runs the real demo and records its output into demo.cast with deterministic
timing, so you get a recording without installing any terminal recorder.

    python3 examples/recording/make_cast.py

Then either:
    agg demo.cast demo.gif        # GIF for the landing  (brew install agg)
    asciinema upload demo.cast    # hosted player to embed
    asciinema play  demo.cast     # local preview
"""
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEMO = ROOT / "examples" / "agent-loop-demo" / "run.sh"
HOME = os.path.expanduser("~")

proc = subprocess.run(["bash", str(DEMO)], capture_output=True, text=True)
if proc.returncode != 0:
    raise SystemExit(f"demo failed:\n{proc.stderr}")


def sanitize(s: str) -> str:
    return s.replace(HOME, "~")  # don't bake an absolute home path into the asset


events = []
t = 0.0
for ln in proc.stdout.splitlines():
    ln = sanitize(ln)
    if "==" in ln and "\033[1m" in ln:
        t += 0.7          # pause before each new section
    elif ln.lstrip().startswith("$ "):
        t += 0.35         # "typing" a command
    else:
        t += 0.12
    events.append([round(t, 3), "o", ln + "\r\n"])

header = {"version": 2, "width": 100, "height": 34, "timestamp": 0,
          "title": "agentvcs — an agent driving the loop",
          "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"}}

out = HERE / "demo.cast"
with out.open("w") as f:
    f.write(json.dumps(header) + "\n")
    for e in events:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")

print(f"Wrote {out} ({len(events)} frames, {events[-1][0]:.1f}s runtime)")
print("Next: agg demo.cast demo.gif   |   asciinema upload demo.cast")
