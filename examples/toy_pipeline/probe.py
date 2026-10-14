"""`agentvcs bisect --exec` probe: re-execute the extractor from the run's checkpoint under one candidate
manifest and print ``{"metrics": {"extract.recall": …}}``.

What it restores. The toy run's state is its position in the document stream: each extractor step stores
``checkpoint_ref = "doc:<next document index>"`` (``regression.py``). bisect exports the checkpoint of the
step before the first patch, so every candidate is re-executed on the SAME documents — the ones the run
went on to process — and only the manifest differs. That is what lets bisect separate two patches that
blame can only attribute jointly. Fake backend by default: deterministic, no model.

    agentvcs bisect toy.audit.json --metric extract.recall --bad '<0.9' \\
        --exec 'python examples/toy_pipeline/probe.py'
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentvcs as avcs  # noqa: E402
from agentvcs.integrations.openai_compat import OpenAICompatClient  # noqa: E402

import pipeline  # noqa: E402


def restore(checkpoint_ref: str, from_step: int) -> int:
    """The document index the run resumes at: the checkpoint if there is one, else the step index (one
    extractor step per document)."""
    if checkpoint_ref.startswith("doc:"):
        return int(checkpoint_ref[len("doc:"):])
    return from_step


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["fake", "openai"], default="fake")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--docs", type=int, default=6, help="documents re-executed from the checkpoint")
    ap.add_argument("--seed", type=int, default=0, help="the run's document stream")
    a = ap.parse_args(argv)
    env = os.environ
    with open(env["AGENTVCS_MANIFEST_FILE"]) as f:
        m = avcs.Manifest(json.load(f))
    start = restore(env.get("AGENTVCS_CHECKPOINT_REF", ""), int(env.get("AGENTVCS_FROM_STEP", "0")))
    docs = pipeline.documents(start + a.docs, a.seed)[start:]
    server, base_url = None, a.base_url
    if a.backend == "fake":
        from agentvcs.testing import FakeOpenAIServer

        server = FakeOpenAIServer(pipeline.fake_respond).start()
        base_url = server.base_url
    try:
        client = OpenAICompatClient(base_url)
        scores = [pipeline.recall(pipeline.parse_json(client.complete("extract", {"document": d.text}, manifest=m).text),
                                  d.gold) for d in docs]
    finally:
        if server:
            server.stop()
    print(json.dumps({"metrics": {"extract.recall": sum(scores) / len(scores), "n": len(scores), "from_doc": start}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
