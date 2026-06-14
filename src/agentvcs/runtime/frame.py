"""The **runtime** dimension — visibility into what a closed agent runtime hides.

A traditional agent runtime (Claude Code, qwen-code, Cursor…) keeps a pile of
operational state that the model itself never gets to see and a human can never
audit after the fact:

  * how many **tokens** were burned, and what that **cost** in dollars,
  * how full the **context window** got, and when it was silently **compacted**,
  * which **model** actually handled each turn (routing/escalation),
  * which **tools** were used and how often,
  * how many **subagents** were fanned out underneath.

The crucial observation: *that state is already in the native session log* — the
runtime simply doesn't surface it. agentvcs reads the same log a trace provider
reads and reconstructs the operational frame, so an agent can ask "what's my
budget?" and a human can diff "did context pressure spike on this commit?".

``build_frame`` is a pure function: providers hand it a list of per-response
``usage`` records plus the normalized messages, and it returns the frame dict
that becomes a content-addressed ``runtime`` object. No I/O, fully testable.

Prices and window sizes are *defaults* — best-effort public list prices, keyed by
a substring of the model id. They are meant to be overridden per repo via
``agent.json`` → ``"budget": {"pricing": {...}, "windows": {...}, "ceiling_usd": N}``
so nobody has to trust our numbers.
"""
from __future__ import annotations

from collections import Counter

# USD per *million* tokens, (input, output). Substring-matched against the model
# id; most-specific key wins, and agent.json overrides beat these defaults.
DEFAULT_PRICING = {
    "claude-opus":   (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku":  (0.80, 4.0),
    "claude-fable":  (5.0, 25.0),
    "gpt-4o":        (2.5, 10.0),
    "o1":            (15.0, 60.0),
    "gemini":        (0.30, 2.5),
    "qwen":          (0.40, 1.20),
}

# Context-window size (tokens) by model-id substring. "[1m]" / "-1m" force 1M.
DEFAULT_WINDOWS = {
    "claude": 200_000,
    "gpt":    128_000,
    "o1":     200_000,
    "gemini": 1_000_000,
    "qwen":   262_144,
}


def _match(table: dict, model: str):
    """Return the value whose key is the *most specific* (longest) substring of the
    model id — so a precise key like ``claude-opus`` wins over a broad one like
    ``claude`` regardless of dict order. ``None`` if nothing matches."""
    if not model:
        return None
    m = model.lower()
    best, best_len = None, -1
    for key, val in table.items():
        if key.lower() in m and len(key) > best_len:
            best, best_len = val, len(key)
    return best


def _tiered(model: str, user: dict, default: dict):
    """User overrides win over built-in defaults: a value declared in ``user``
    always takes precedence, even when a broad default key would also match (e.g.
    overriding just ``opus`` must beat the default ``claude`` window)."""
    hit = _match(user or {}, model)
    return hit if hit is not None else _match(default, model)


def _window_for(model: str, user_windows: dict) -> int | None:
    if model and ("[1m]" in model.lower() or "-1m" in model.lower()):
        return 1_000_000
    return _tiered(model, user_windows, DEFAULT_WINDOWS)


def _cost(model: str, inp: int, out: int, user_pricing: dict) -> float | None:
    rate = _tiered(model, user_pricing, DEFAULT_PRICING)
    if rate is None:
        return None
    return round(inp / 1e6 * rate[0] + out / 1e6 * rate[1], 6)


def _count_tools(messages: list) -> Counter:
    """Count tool_use blocks across the normalized trace (provider-agnostic — the
    qwen provider maps Gemini functionCall parts to the same block shape)."""
    tools: Counter = Counter()
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tools[b.get("name") or "?"] += 1
    return tools


def build_frame(
    messages: list,
    *,
    usages: list | None = None,
    subagents: list | None = None,
    compactions: int = 0,
    budget: dict | None = None,
) -> dict:
    """Reconstruct the operational frame the runtime never showed.

    ``messages`` — the normalized trace (used for turn/tool/model fallback).
    ``usages``   — optional per-response records, the high-fidelity source::

        {"model": "claude-opus-4-8", "input": 1820, "output": 240,
         "cache_read": 16000, "cache_creation": 0}

    ``subagents`` — list of ``{"type": str, "count": int}`` (fleet fan-out).
    ``compactions`` — how many times the runtime silently truncated context.
    ``budget`` — manifest config: ``ceiling_usd``, ``pricing``, ``windows``.
    """
    budget = budget or {}
    # Keep user overrides separate from defaults so _tiered() can give them
    # precedence (a narrow override must beat a broad default — see _match/_tiered).
    user_pricing = budget.get("pricing") or {}
    user_windows = budget.get("windows") or {}
    usages = usages or []

    # ---- model routing + budget, from real usage when we have it -------------
    routing: dict[str, dict] = {}
    tok_in = tok_out = 0
    cost_total = 0.0
    cost_known = False
    used_ctx = 0  # peak tokens the model actually saw in any single response

    for u in usages:
        model = u.get("model") or ""
        inp = int(u.get("input") or 0)
        out = int(u.get("output") or 0)
        cache = int(u.get("cache_read") or 0) + int(u.get("cache_creation") or 0)
        r = routing.setdefault(
            model, {"turns": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
        r["turns"] += 1
        r["tokens_in"] += inp
        r["tokens_out"] += out
        tok_in += inp
        tok_out += out
        c = _cost(model, inp, out, user_pricing)
        if c is not None:
            r["cost_usd"] = round(r["cost_usd"] + c, 6)
            cost_total += c
            cost_known = True
        used_ctx = max(used_ctx, inp + cache)

    # fallback: no usage records (classic file trace) — at least surface routing
    # and turn counts from the messages the model produced.
    if not usages:
        for m in messages:
            if m.get("role") == "assistant" and m.get("model"):
                routing.setdefault(
                    m["model"], {"turns": 0, "tokens_in": 0, "tokens_out": 0,
                                 "cost_usd": 0.0})["turns"] += 1

    turns = sum(r["turns"] for r in routing.values()) or sum(
        1 for m in messages if m.get("role") in ("assistant", "model"))

    # ---- context-window pressure --------------------------------------------
    window = None
    for model in routing:
        w = _window_for(model, user_windows)
        if w is not None:
            window = max(window or 0, w)
    pct = round(used_ctx / window * 100, 1) if (window and used_ctx) else None

    # ---- budget envelope -----------------------------------------------------
    ceiling = budget.get("ceiling_usd")
    spent = round(cost_total, 6) if cost_known else None
    remaining = (round(ceiling - cost_total, 6)
                 if (ceiling is not None and cost_known) else None)

    tools = _count_tools(messages)

    return {
        "turns": turns,
        "budget": {
            "tokens_in": tok_in,
            "tokens_out": tok_out,
            "tokens_total": tok_in + tok_out,
            "cost_usd": spent,
            "ceiling_usd": ceiling,
            "remaining_usd": remaining,
            "over_budget": (remaining is not None and remaining < 0),
        },
        "context": {
            "window": window,
            "used": used_ctx or None,
            "pct": pct,
            "compactions": compactions,
        },
        "models": [
            {"model": k, **v} for k, v in sorted(
                routing.items(), key=lambda kv: -kv[1]["turns"])
        ],
        "tools": [{"name": n, "count": c} for n, c in tools.most_common()],
        "subagents": subagents or [],
    }
