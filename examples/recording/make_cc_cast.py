#!/usr/bin/env python3
"""Generate an asciinema cast of the Claude Code trace provider — zero deps.

Builds a throwaway toy project, seeds a realistic Claude Code session transcript
where the provider actually looks for it, then records a typing-animated cast of
the real `cat agent.json` / `trace` / `commit` / `show --trace` flow (output
captured through a pty, so the CLI's real colors are preserved).

    python3 examples/recording/make_cc_cast.py     # writes cc-trace.cast
    agg --theme dracula --font-size 16 examples/recording/cc-trace.cast \
        examples/recording/cc-trace.gif            # -> GIF (brew install agg)
"""
import json
import os
import pty
import select
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
HOME = Path.home()
DEMO = HOME / ".agentvcs-cc-demo"
PROJECTS = HOME / ".claude" / "projects"
COLS, ROWS = 118, 34

PROMPT = "\x1b[38;5;208m➜\x1b[0m \x1b[36mtriage-bot\x1b[0m $ "
APP_SNIPPET = "def handle(msg):\n    return classify(msg)  # -> {queue, urgent}\n"
APP_FULL = (
    "def handle(msg):\n    t = msg.lower()\n"
    "    return {\"queue\": \"billing\" if \"refund\" in t else \"general\",\n"
    "            \"urgent\": \"urgent\" in t}\n")


def env():
    e = dict(os.environ)
    e.update(PYTHONPATH=str(SRC), TERM="xterm-256color",
             COLUMNS=str(COLS), LINES=str(ROWS))
    return e


def run_pty(args) -> str:
    """Run a command attached to a pty (so isatty() is true and the CLI colors
    its output) and return everything it printed."""
    master, slave = pty.openpty()
    p = subprocess.Popen(args, cwd=str(DEMO), stdin=slave, stdout=slave,
                         stderr=slave, env=env())
    os.close(slave)
    out = b""
    while True:
        r, _, _ = select.select([master], [], [], 0.2)
        if master in r:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        elif p.poll() is not None:
            break
    os.close(master)
    p.wait()
    return out.decode("utf-8", "replace")


def avcs(*a):
    return run_pty([sys.executable, "-m", "agentvcs.cli", *a])


# ------------------------------------------------------------------ scaffolding
def setup() -> str:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    enc = str(DEMO.resolve()).replace("/", "-")
    proj = PROJECTS / enc
    proj.mkdir(parents=True, exist_ok=True)
    transcript = [
        {"type": "user", "cwd": str(DEMO), "uuid": "u1", "timestamp": "2026-06-07T20:00:00Z",
         "message": {"role": "user",
                     "content": "Create a support-triage queue in app.py: classify a message and flag urgent ones."}},
        {"type": "assistant", "cwd": str(DEMO), "uuid": "a1", "timestamp": "2026-06-07T20:00:04Z",
         "message": {"role": "assistant", "model": "claude-opus-4-8", "content": [
             {"type": "thinking", "thinking": "Keep it minimal: a keyword classifier with an urgent flag, one handle()."},
             {"type": "text", "text": "I'll add a small triage function."},
             {"type": "tool_use", "name": "Write", "input": {"file_path": "app.py", "content": APP_SNIPPET}}]}},
        {"type": "user", "cwd": str(DEMO), "uuid": "u2", "timestamp": "2026-06-07T20:00:06Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "content": "File written: app.py"}]}},
        {"type": "assistant", "cwd": str(DEMO), "uuid": "a2", "timestamp": "2026-06-07T20:00:08Z",
         "message": {"role": "assistant", "model": "claude-opus-4-8", "content": [
             {"type": "text", "text": "Done — app.py routes refunds to billing and flags urgent messages."}]}},
    ]
    (proj / "session.jsonl").write_text(
        "\n".join(json.dumps(l) for l in transcript) + "\n")
    (DEMO / "app.py").write_text(APP_FULL)
    avcs("init", "--claude-code")
    m = json.loads((DEMO / "agent.json").read_text())
    m["goal"] = "Build a support-triage queue"
    (DEMO / "agent.json").write_text(json.dumps(m, indent=2) + "\n")
    return enc


def cleanup(enc):
    shutil.rmtree(DEMO, ignore_errors=True)
    shutil.rmtree(PROJECTS / enc, ignore_errors=True)


# ----------------------------------------------------------------- cast builder
class Cast:
    def __init__(self):
        self.events = []
        self.t = 0.0

    def emit(self, data, pre=0.0):
        self.t = round(self.t + pre, 3)
        self.events.append([self.t, "o", data])

    def cmd(self, text, pre):
        self.emit(PROMPT, pre)
        for ch in text:
            self.emit(ch, 0.045)
        self.emit("\r\n", 0.3)

    def out(self, text):
        text = text.replace(str(HOME), "~")
        for line in text.splitlines():
            self.emit(line + "\r\n", 0.06)


def main():
    enc = setup()
    try:
        agent_json = (DEMO / "agent.json").read_text()
        trace_out = avcs("trace")
        commit_out = avcs("commit", "-m", "v1: triage queue")
        show_out = avcs("show", "--trace")
    finally:
        cleanup(enc)

    c = Cast()
    c.cmd("cat agent.json", 0.6);                       c.out(agent_json)
    c.cmd("agentvcs trace", 3.0);                       c.out(trace_out)
    c.cmd("agentvcs commit -m 'v1: triage queue'", 3.0); c.out(commit_out)
    c.cmd("clear", 2.6); c.emit("\x1b[H\x1b[2J\x1b[3J", 0.3)
    c.cmd("agentvcs show --trace", 0.6);                c.out(show_out)
    c.emit(PROMPT, 6.0)  # hold on the payoff, then a final prompt

    header = {"version": 2, "width": COLS, "height": ROWS, "timestamp": 0,
              "title": "agentvcs — Claude Code trace capture",
              "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"}}
    out = HERE / "cc-trace.cast"
    with out.open("w") as f:
        f.write(json.dumps(header) + "\n")
        for e in c.events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"Wrote {out} ({len(c.events)} frames, {c.events[-1][0]:.1f}s)")
    print("Next: agg --theme dracula --font-size 16 "
          f"{out} {HERE / 'cc-trace.gif'}")


if __name__ == "__main__":
    main()
