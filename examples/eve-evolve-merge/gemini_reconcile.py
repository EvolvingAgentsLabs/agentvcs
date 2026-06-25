#!/usr/bin/env python3
"""nanoLoop-style merge reconciler, backed by Gemini (gemini-3.5-flash).

Same contract and same Consolidated-Knowledge-Trace approach as the bundled
nanoLoop reconciler (../nanoloop-reconcile/reconcile.py) — agentvcs pipes the merge
*bundle* to stdin and reads back `{goal, trace, notes, resolved_files?}` on stdout —
but the "brain" is the Gemini API instead of nanoLoop's OpenRouter layer.

  Run:  GEMINI_API_KEY=... agentvcs merge main \
          --reconcile "python3.12 gemini_reconcile.py"

The key is read from the environment only; nothing is written to disk.
Override the model with GEMINI_MODEL (default: gemini-3.5-flash).
"""
from __future__ import annotations

import json
import os
import sys

# Reuse nanoLoop's reconciliation prompt verbatim, so this really is "the nanoLoop
# merge" with a Gemini backend — only the model call differs.
_NL = os.path.join(os.path.dirname(__file__), "..", "nanoloop-reconcile")
sys.path.insert(0, os.path.abspath(_NL))
try:
    from reconcile import SYSTEM, build_user_prompt          # type: ignore
except Exception:                                            # pragma: no cover
    # Fallback: inline a minimal equivalent if the nanoLoop example isn't present.
    SYSTEM = ("You reconcile two divergent agent branches into one working memory and "
              "resolve their code conflicts. The bundle has base/ours/theirs goals, "
              "traces, metrics, an optional target_goal, and conflict_files (full "
              "base/ours/theirs text). Return STRICT JSON: {\"goal\": str, \"trace\": "
              "[{\"role\":...,\"content\":...}], \"resolved_files\": {path: full clean "
              "file, no <<<<<<< markers}, \"notes\": str}. Include resolved_files only "
              "for paths in conflict_files.")

    def build_user_prompt(bundle):  # type: ignore
        return json.dumps(bundle)[:200_000]


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def main() -> int:
    bundle = json.load(sys.stdin)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.stderr.write("GEMINI_API_KEY not set\n")
        return 2
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=build_user_prompt(bundle),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    parsed = _extract_json(resp.text)

    out = {
        "goal": parsed["goal"],
        "trace": parsed["trace"],
        "notes": parsed.get("notes", f"reconciled by {model}"),
    }
    rf = parsed.get("resolved_files")
    if isinstance(rf, dict) and rf:
        out["resolved_files"] = rf
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
