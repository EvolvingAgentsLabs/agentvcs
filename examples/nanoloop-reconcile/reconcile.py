#!/usr/bin/env python
"""nanoLoop-powered reconciliation brain for `agentvcs merge --reconcile`.

agentvcs core never calls an LLM. When two branches diverge, `merge` writes a
*reconciliation bundle* (base/ours/theirs goals + traces + code diffs + metrics +
conflicts) to this process's stdin and reads back
``{goal, trace, notes, resolved_files?}`` on stdout. That seam is identical in
spirit to `replay --exec`.

This script is a **thin shim**: the actual prompt and contract live in nanoLoop,
in ``nanoloop.reconcile`` — a single source of truth shared with the
``nanoloop reconcile`` CLI subcommand, so the two can never drift. Run it with
nanoLoop's venv python so its deps + .env are in scope::

    agentvcs merge <branch> --reconcile \
      "/path/nanoLoop/.venv/bin/python /path/reconcile.py /path/nanoLoop/.env"

Equivalent to (and preferred over) calling the installed CLI directly::

    agentvcs merge <branch> --reconcile "/path/nanoLoop/.venv/bin/nanoloop reconcile /path/.env"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Re-exported for backward compatibility: older code imported SYSTEM /
# build_user_prompt from this module. They now live in nanoLoop.
from nanoloop.reconcile import (  # noqa: F401
    SYSTEM,
    build_user_prompt,
    reconcile_bundle,
)


def main() -> int:
    from dotenv import load_dotenv  # lazy: only the CLI entrypoint needs it
    # load nanoLoop's .env (OPENROUTER_API_KEY, HARNESS_MODEL) if a path is given
    if len(sys.argv) > 1:
        load_dotenv(Path(sys.argv[1]))
    else:
        load_dotenv()

    bundle = json.load(sys.stdin)
    out = reconcile_bundle(bundle)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
