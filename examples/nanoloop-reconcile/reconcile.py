#!/usr/bin/env python
"""A reconciliation brain for `agentvcs merge --reconcile`.

agentvcs core never calls an LLM. When two branches diverge, `merge` writes a
*reconciliation bundle* — {base, ours, theirs} goals + traces + code diffs +
recorded metrics + unresolved conflicts — to this process's stdin, and reads
back ``{goal, trace, notes, resolved_files?}`` on stdout. That seam is the whole
contract; anything that honours it can be the brain.

This is a self-contained reference implementation. It depends on nothing beyond
the standard library and imports nothing from agentvcs, so you can copy this
directory anywhere and point it at any OpenAI-compatible endpoint::

    export RECONCILE_BASE_URL=https://openrouter.ai/api/v1
    export RECONCILE_API_KEY=sk-or-...
    export RECONCILE_MODEL=anthropic/claude-sonnet-4

    agentvcs merge runtime/main --reconcile "python examples/nanoloop-reconcile/reconcile.py"

Or entirely locally, with no key and no network::

    export RECONCILE_BASE_URL=http://localhost:11434/v1
    export RECONCILE_MODEL=gemma4:12b

The prompt and contract originated in nanoLoop's ``nanoloop.reconcile``. They
were inlined here in July 2026 so that agentvcs's flagship feature does not
depend on a separate forked repository being cloned beside it, and so the
example runs without LangChain.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconcile_impl import SYSTEM, build_user_prompt, reconcile_bundle  # noqa: E402,F401


def main() -> int:
    try:
        bundle = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"reconcile: could not parse bundle on stdin: {exc}", file=sys.stderr)
        return 2

    try:
        result = reconcile_bundle(bundle)
    except Exception as exc:  # noqa: BLE001 — surface the reason back to the merge
        print(f"reconcile: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
