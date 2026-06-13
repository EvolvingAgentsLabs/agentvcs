#!/usr/bin/env python3
"""SkillOS × Gemma × agentvcs — the meta-agent.

One invocation runs ONE iteration of a SkillOS-style cognitive pipeline
(ingress → routing → planning → execution → memory → egress) that builds a small
*sub-agent* and evaluates it. It:

  * calls a model for the planning rationale — **Gemma 4 31b via Ollama**
    (``gemma4:31b``, the primary engine) if reachable, else **Gemini** if
    ``GEMINI_API_KEY`` is set (optional hosted alternative), else a deterministic
    offline backend so the demo always runs (and CI stays reproducible);
  * generates the sub-agent (`subagent/skill.md` + `subagent/tool.py`);
  * runs it in an isolated subprocess against eval cases;
  * writes the pipeline to a SkillOS session log at
    ``.skillos/sessions/<stage>.jsonl`` — which ``agentvcs commit`` vacuums via
    the ``skillos`` trace provider (no trace file maintained by hand).

Pure standard library: no third-party packages, matching agentvcs's zero-dep ethos.

Usage:
    python meta_agent.py --stage v1 --goal "Extract the top-3 keywords from text."
The driver (run.sh) calls this once per iteration and wraps each call in
``agentvcs commit``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

SESSION_DIR = Path(".skillos/sessions")
SUBAGENT_DIR = Path("subagent")

# Sample document + the keywords a correct top-3 extractor should return. "the",
# "a", "to" are stop-words, so the naive vs stop-word-aware builds differ here.
EVAL_TEXT = (
    "The billing error crashed the app. The billing team must refund the charge. "
    "A refund a day keeps the angry billing tickets away."
)
EVAL_CASES = [
    # (stdin, expected_stdout) for the two acceptance targets of EVAL_TEXT:
    (EVAL_TEXT, "the,billing,refund"),     # naive goal (v1): top-3 raw words, "the" included
    (EVAL_TEXT, "billing,refund,error"),   # stop-word-aware goal (v2/v4): "the" dropped, real keywords
]


# --------------------------------------------------------------------- backends
class Backend:
    """A minimal chat backend. ``model_id`` is what gets recorded as the model
    pin, so agentvcs versions *the model that actually ran*."""
    name = "base"
    model_id = "base"

    def complete(self, system: str, prompt: str, temperature: float = 0.9) -> str:
        raise NotImplementedError


class GeminiBackend(Backend):
    """Google Gemini via its REST API (stdlib urllib; no SDK needed)."""
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_id = model

    def complete(self, system, prompt, temperature=0.9):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model_id}:generateContent?key={self.api_key}")
        body = {
            "contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 512},
        }
        data = _post_json(url, body)
        return (data["candidates"][0]["content"]["parts"][0]["text"]).strip()


class OllamaBackend(Backend):
    """Local Gemma 4 31b via Ollama's OpenAI-compatible endpoint."""
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model_id = model

    def complete(self, system, prompt, temperature=0.9):
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": False,
        }
        data = _post_json(url, body, bearer=os.environ.get("OLLAMA_API_KEY", "ollama"))
        return data["choices"][0]["message"]["content"].strip()


class MockBackend(Backend):
    """Deterministic offline backend — no network. Produces a stage-aware
    planning rationale so the demo (and CI) run end-to-end with no credentials."""
    name = "mock"
    model_id = "mock-deterministic-v0"

    def complete(self, system, prompt, temperature=0.0):
        # Echo the subgoals back as a terse rationale; the interesting artifact is
        # the *generated code* + the *captured trace*, both produced regardless.
        head = prompt.strip().splitlines()[0] if prompt.strip() else "plan"
        return f"[offline reasoning] proceeding on: {head}"


def select_backend() -> Backend:
    """Gemma 4 31b via Ollama (primary engine) → Gemini (optional hosted
    alternative) → deterministic offline mock."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("GEMMA_MODEL", "gemma4:31b")
    try:
        b = OllamaBackend(base, model)
        b.complete("ping", "ping", 0.0)            # cheap reachability probe
        return b
    except Exception as e:                          # noqa: BLE001 — fall through
        _warn(f"Gemma 4 31b (Ollama) unavailable ({e}); trying Gemini.")
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        try:
            b = GeminiBackend(key, os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))
            b.complete("ping", "ping", 0.0)
            return b
        except Exception as e:                      # noqa: BLE001 — fall through
            _warn(f"Gemini unavailable ({e}); using offline deterministic backend.")
    else:
        _warn("no GEMINI_API_KEY set; using offline deterministic backend.")
    return MockBackend()


def _post_json(url: str, body: dict, bearer: str | None = None, timeout: float = 30.0):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {bearer}"} if bearer else {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ------------------------------------------------------- the generated sub-agent
# Per-stage code templates. The meta-agent "generates" these; later stages change
# only what the evolved goal requires — exactly what agentvcs's per-dimension diff
# is meant to surface.
_STOPWORDS = "{'the','a','an','to','of','and','must','keeps','away','day'}"

_TOOL_NAIVE = '''import sys, re
from collections import Counter

def top_keywords(text, n=3):
    words = re.findall(r"[a-z]+", text.lower())
    return [w for w, _ in Counter(words).most_common(n)]

if __name__ == "__main__":
    print(",".join(top_keywords(sys.stdin.read())))
'''

_TOOL_STOPWORDS = f'''import sys, re
from collections import Counter

STOP = {_STOPWORDS}

def top_keywords(text, n=3):
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP]
    return [w for w, _ in Counter(words).most_common(n)]

if __name__ == "__main__":
    print(",".join(top_keywords(sys.stdin.read())))
'''

_TOOL_REGRESSION = '''import sys, re
from collections import Counter

def top_keywords(text, n=3):
    # premature "optimization": only look at the first 5 words. Overfits and breaks.
    words = re.findall(r"[a-z]+", text.lower())[:5]
    return [w for w, _ in Counter(words).most_common(n)]

if __name__ == "__main__":
    print(",".join(top_keywords(sys.stdin.read())))
'''

# stage -> (goal, tool source, which EVAL_CASES index is the "expected" target)
STAGES = {
    "v1": ("Extract the top-3 keywords from a block of text.",
           _TOOL_NAIVE, 0),
    "v2": ("Extract the top-3 keywords from text, ignoring common stop-words.",
           _TOOL_STOPWORDS, 1),
    "v3": ("Extract the top-3 keywords from text, ignoring common stop-words.",
           _TOOL_REGRESSION, 1),     # same goal, regressed code
    "v4": ("Extract the top-3 keywords from text, ignoring common stop-words.",
           _TOOL_STOPWORDS, 1),      # the proper fix
}

_SKILL_MD = '''---
name: top-keywords-agent
type: agent
description: {goal}
tools: tool.py
---

# Top-Keywords Agent

Reads text on stdin, prints the top-3 keywords (comma-separated) on stdout.
Goal: {goal}
'''


# ----------------------------------------------------------------- the pipeline
class Session:
    """Append-only SkillOS session log. Each phase is one JSONL event; the
    agentvcs ``skillos`` trace provider reads exactly this."""

    def __init__(self, stage: str, model_id: str, provider: str):
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self.path = SESSION_DIR / f"{stage}.jsonl"
        self.path.write_text("")        # one log per iteration
        self.model_id = model_id
        self.provider = provider

    def event(self, phase: str, role: str, agent: str, content: str):
        rec = {"phase": phase, "role": role, "agent": agent, "content": content,
               "model": self.model_id, "provider": self.provider,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def generate_subagent(goal: str, tool_src: str):
    SUBAGENT_DIR.mkdir(parents=True, exist_ok=True)
    (SUBAGENT_DIR / "skill.md").write_text(_SKILL_MD.format(goal=goal))
    (SUBAGENT_DIR / "tool.py").write_text(tool_src)


def run_eval(target_idx: int) -> dict:
    """Execute subagent/tool.py in a fresh subprocess for each eval case."""
    detail = []
    passed = 0
    for i, (stdin, expected) in enumerate(EVAL_CASES):
        want = EVAL_CASES[target_idx][1] if i == target_idx else expected
        # Only the targeted case defines success for this stage; we still record
        # the tool's raw output so the trace shows what it actually produced.
        proc = subprocess.run(
            [sys.executable, str(SUBAGENT_DIR / "tool.py")],
            input=stdin, capture_output=True, text=True, timeout=15)
        got = proc.stdout.strip()
        ok = (got == want)
        if i == target_idx:
            passed = int(ok)
        detail.append({"case": i, "expected": want, "actual": got, "match": ok})
    target = detail[target_idx]
    return {"passed": bool(passed), "accuracy": float(passed),
            "target": target, "detail": detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=list(STAGES))
    ap.add_argument("--goal", default=None, help="override the stage's goal text")
    args = ap.parse_args()

    goal, tool_src, target_idx = STAGES[args.stage]
    goal = args.goal or goal

    backend = select_backend()
    sess = Session(args.stage, backend.model_id, _provider_of(backend))

    # 1. INGRESS — compile intent
    sess.event("ingress", "intent-compiler", "ingress",
               f"Build a sub-agent. Goal: {goal}")

    # 2. ROUTING — pick the skills (the markdown OS)
    sess.event("routing", "router", "routing",
               "Routed to skills: planning/hwm-planner, codegen/skill-writer, "
               "execution/sandbox-runner.")

    # 3. PLANNING — HWM: ask the model to decompose into subgoals
    plan_prompt = (f"GOAL: {goal}\nDecompose into 3–5 ordered subgoals for a code "
                   f"generator. Stage: {args.stage}.")
    plan = backend.complete(
        "You are hwm-planner, an L2 macro-planner. Output numbered subgoals only.",
        plan_prompt, temperature=0.9)
    sess.event("planning", "planner", "hwm-macro-planner", plan)

    # 4. EXECUTION — generate the sub-agent, run it, evaluate
    generate_subagent(goal, tool_src)
    sess.event("execution", "codegen", "skill-writer",
               f"Generated subagent/skill.md + subagent/tool.py ({len(tool_src)} bytes).")
    result = run_eval(target_idx)
    sess.event("execution", "tool", "sandbox-runner",
               f"Eval target: expected {result['target']['expected']!r}, "
               f"got {result['target']['actual']!r} → "
               f"{'PASS' if result['passed'] else 'FAIL'} "
               f"(accuracy {result['accuracy']:.2f}).")

    # 5. MEMORY — consolidate the outcome
    sess.event("memory", "consolidator", "smart-memory",
               f"Stage {args.stage}: passed={result['passed']}, goal={goal!r}.")

    # 6. EGRESS — human-readable summary
    verdict = "trusted (eval passes)" if result["passed"] else "NOT trusted (eval fails)"
    sess.event("egress", "renderer", "egress",
               f"Built top-keywords sub-agent — {verdict}.")

    # The driver branches on this JSON (passed → commit as good; failed → the
    # regression it will roll back).
    out = {"stage": args.stage, "goal": goal, "backend": backend.name,
           "model": backend.model_id, "passed": result["passed"],
           "accuracy": result["accuracy"], "session": str(sess.path),
           "target": result["target"]}
    print(json.dumps(out))
    return 0


def _provider_of(b: Backend) -> str:
    return {"gemini": "google", "ollama": "ollama", "mock": "offline"}.get(b.name, b.name)


def _warn(msg: str):
    print(f"  [meta-agent] {msg}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
