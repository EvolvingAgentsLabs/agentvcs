"""Gate suite command: score the candidate manifest's extractor on held-out
contracts and print ``{"metrics": {...}}``. ``agentvcs gate run`` sets
``AGENTVCS_MANIFEST_FILE`` to the candidate (``to_manifest``)."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentvcs as avcs  # noqa: E402
from agentvcs.integrations.openai_compat import OpenAICompatClient  # noqa: E402

import pipeline  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["fake", "openai"], default="fake")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--docs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1000)  # disjoint from the run's docs
    a = ap.parse_args(argv)
    with open(os.environ["AGENTVCS_MANIFEST_FILE"]) as f:
        m = avcs.Manifest(json.load(f))
    server = None
    base_url = a.base_url
    if a.backend == "fake":
        from agentvcs.testing import FakeOpenAIServer

        server = FakeOpenAIServer(pipeline.fake_respond).start()
        base_url = server.base_url
    try:
        client = OpenAICompatClient(base_url)
        scores = []
        for doc in pipeline.documents(a.docs, a.seed):
            c = client.complete("extract", {"document": doc.text}, manifest=m)  # not recorded
            scores.append(pipeline.recall(pipeline.parse_json(c.text), doc.gold))
    finally:
        if server:
            server.stop()
    print(json.dumps({"metrics": {"extract.recall": sum(scores) / len(scores), "n": len(scores)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
