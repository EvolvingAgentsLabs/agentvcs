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
    ap.add_argument("--paired", action="store_true",
                    help="also score the patch's from_manifest on the same documents and report the gain")
    a = ap.parse_args(argv)
    with open(os.environ["AGENTVCS_MANIFEST_FILE"]) as f:
        m = avcs.Manifest(json.load(f))
    base = None
    if a.paired:
        # `agentvcs gate run` exports the patch's from_manifest id and the store; the
        # normalized manifest lives at <store>/manifests/<hex>.json (as MANIFEST_FILE does)
        hex_id = os.environ["AGENTVCS_FROM_MANIFEST"].split(":", 1)[1]
        with open(os.path.join(os.environ["AGENTVCS_STORE"], "manifests", hex_id + ".json")) as f:
            base = avcs.Manifest(json.load(f))
    server = None
    base_url = a.base_url
    if a.backend == "fake":
        from agentvcs.testing import FakeOpenAIServer

        server = FakeOpenAIServer(pipeline.fake_respond).start()
        base_url = server.base_url
    try:
        client = OpenAICompatClient(base_url)
        scores, base_scores = [], []
        for doc in pipeline.documents(a.docs, a.seed):
            c = client.complete("extract", {"document": doc.text}, manifest=m)  # not recorded
            scores.append(pipeline.recall(pipeline.parse_json(c.text), doc.gold))
            if base is not None:
                b = client.complete("extract", {"document": doc.text}, manifest=base)
                base_scores.append(pipeline.recall(pipeline.parse_json(b.text), doc.gold))
    finally:
        if server:
            server.stop()
    metrics = {"extract.recall": sum(scores) / len(scores), "n": len(scores)}
    if base_scores:
        # paired on the same documents: the gate judges the gain, not an absolute level
        metrics["extract.recall.baseline"] = sum(base_scores) / len(base_scores)
        metrics["extract.recall.gain"] = metrics["extract.recall"] - metrics["extract.recall.baseline"]
    print(json.dumps({"metrics": metrics}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
