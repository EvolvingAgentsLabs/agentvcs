"""The harness: three agents (extractor -> checker -> summarizer) over a stream of
contracts, driven by the manifest of its agentvcs run. It never decides its own
configuration: model, sampling and prompts are read from ``run.manifest``, and a
patch applied by anyone (here: the supervisor process, through the CLI) is picked
up at the next step boundary via ``run.on_patch``.

``--no-reload`` is the control arm: the harness pins the manifest it started with
and ignores patches (the ledger still records the active manifest — this is the
"harness that lies" the blame test must be able to tell apart).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentvcs as avcs  # noqa: E402
from agentvcs.integrations.openai_compat import OpenAICompatClient  # noqa: E402

import pipeline  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--manifest", required=True, help="manifest id or file")
    ap.add_argument("--run-id", default="toy")
    ap.add_argument("--backend", choices=["fake", "openai"], default="fake")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--docs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--step-delay", type=float, default=0.0, help="seconds slept inside each step")
    ap.add_argument("--no-reload", action="store_true")
    ap.add_argument("--status-file", default=None)
    a = ap.parse_args(argv)

    server = None
    base_url = a.base_url
    if a.backend == "fake":
        from agentvcs.testing import FakeOpenAIServer

        server = FakeOpenAIServer(pipeline.fake_respond).start()
        base_url = server.base_url
    elif not base_url:
        ap.error("--backend openai needs --base-url (e.g. http://127.0.0.1:8080/v1)")
    client = OpenAICompatClient(base_url)

    reloads = []
    docs = pipeline.documents(a.docs, a.seed)
    t_start = time.time()
    try:
        with avcs.run(a.manifest, store=a.store, run_id=a.run_id) as run:
            pinned = run.manifest if a.no_reload else None

            @run.on_patch
            def reload(ev: avcs.PatchEvent) -> None:
                # A real harness would rebuild clients, reload adapters, etc. Ours
                # reads every dimension from run.manifest per call, so a reload is
                # a log line — unless it is the control arm, which keeps `pinned`.
                reloads.append({"patch_id": ev.patch_id, "at_step": ev.applied_at_step,
                                "dimensions": ev.changed_dimensions})
                what = "IGNORED (--no-reload)" if pinned else "reloaded"
                print(f"[harness] patch {ev.patch_id[:15]}… at step {ev.applied_at_step}: "
                      f"{', '.join(ev.changed_dimensions)} {what}", flush=True)

            def cfg():
                return pinned  # None = the run's active manifest at this step

            @avcs.step("extractor", inputs=lambda doc: [doc.text])
            def extract(doc):
                time.sleep(a.step_delay)
                c = client.complete("extract", {"document": doc.text}, manifest=cfg())
                fields = pipeline.parse_json(c.text) or {}
                avcs.current_step().metric("extract.recall", pipeline.recall(fields, doc.gold))
                return fields

            @avcs.step("checker", inputs=lambda doc, ex: [doc.text, ex])
            def check(doc, ex):
                time.sleep(a.step_delay)
                c = client.complete("check", {"document": doc.text, "extraction": json.dumps(ex)},
                                    manifest=cfg())
                ok = c.text.strip().upper().startswith("OK")
                avcs.current_step().metric("check.ok", 1.0 if ok else 0.0)
                return c.text.strip()

            @avcs.step("summarizer", inputs=lambda doc, ex: [ex])
            def summarize(doc, ex):
                time.sleep(a.step_delay)
                c = client.complete("summarize", {"extraction": json.dumps(ex)}, manifest=cfg())
                hit = pipeline._norm(doc.gold["cap_amount"]) in pipeline._norm(c.text)
                avcs.current_step().metric("summary.mentions_cap", 1.0 if hit else 0.0)
                return c.text.strip()

            for i, doc in enumerate(docs):
                ex = extract(doc)
                verdict = check(doc, ex)
                summarize(doc, ex)
                print(f"[harness] doc {i + 1}/{len(docs)} steps={run.next_step} "
                      f"recall={pipeline.recall(ex, doc.gold):.2f} check={verdict[:24]!r} "
                      f"manifest={run.manifest.id[:15]}…", flush=True)
    finally:
        if server:
            server.stop()
    status = {"run_id": a.run_id, "reloads": reloads, "stats": run.stats,
              "seconds": round(time.time() - t_start, 2), "no_reload": a.no_reload}
    if a.status_file:
        with open(a.status_file, "w") as f:
            json.dump(status, f, indent=2)
    print("[harness] done " + json.dumps(status), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
