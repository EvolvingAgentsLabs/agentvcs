#!/usr/bin/env python3
"""Reduce a REAL Claude Code transcript to a frame-only fixture for the demo.

The runtime-trust demo's headline is `agentvcs runtime` reconstructing the
operational frame. To keep that honest, the fixture it reads must come from a
*real* session — not invented numbers. But a raw transcript is huge and contains
the entire conversation. So this reducer keeps ONLY the fields the runtime frame
is computed from and throws away every byte of natural-language content:

  * per-assistant `message.model` + `message.usage` (the four token counts),
  * `tool_use` blocks reduced to `{type, name}` (no inputs),
  * compaction/summary markers (so `compactions` is real),

and drops all `text` / `thinking` / tool inputs / tool results / user prose. The
result is real token/cost/context/routing/tool numbers with zero readable content.

Usage:
    python3 examples/recording/make_runtime_fixture.py \
        ~/.claude/projects/<encoded-cwd>/<session>.jsonl \
        examples/recording/fixtures/runtime-session.jsonl

The committed fixture is what the tape replays; this script records its provenance
and lets anyone regenerate it from their own session.
"""
from __future__ import annotations

import json
import pathlib
import sys

DEMO_CWD = "/home/agent/projects/add-fn"  # neutral placeholder; provider keys by dir, not this


def reduce_line(o: dict):
    t = o.get("type")
    # keep compaction/summary markers (frame counts these) — but stripped
    if o.get("isCompactSummary") or t == "summary":
        return {"type": "summary", "isCompactSummary": True}
    if t != "assistant":
        return None  # user/tool_result lines aren't needed for the frame
    msg = o.get("message") or {}
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    tools = [
        {"type": "tool_use", "name": b.get("name") or "?"}
        for b in (msg.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    return {
        "type": "assistant",
        "cwd": DEMO_CWD,
        "timestamp": o.get("timestamp"),
        "message": {
            "role": "assistant",
            "model": msg.get("model"),
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            },
            "content": tools,  # names only, no inputs/text/thinking
        },
    }


def main():
    src = pathlib.Path(sys.argv[1]).expanduser()
    dst = pathlib.Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for line in src.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        r = reduce_line(o)
        if r is not None:
            out.append(r)
    dst.write_text("\n".join(json.dumps(r) for r in out) + "\n")
    print(f"reduced {src.name}: {len(out)} frame-relevant lines -> {dst}")


if __name__ == "__main__":
    main()
