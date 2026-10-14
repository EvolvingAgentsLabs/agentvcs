"""A run with a planted regression, for `agentvcs bisect`.

The extractor processes a stream of contracts (one step per document, ``checkpoint_ref = "doc:<next>"``)
under the cap-aware manifest (v2, recall 1.0). Four patches land during the run, each through a gate:

    after doc 2   summarize.prompt wording            harmless
    after doc 4   extract.sampling max_tokens 256      harmless
    after doc 6   extract.prompt asks for "supplier"   THE REGRESSION — the documents say "Supplier"
                  instead of "party"                   but the scorer's field is `party`: recall 1.0 -> 0.667
    after doc 6   check.sampling max_tokens 64         harmless, applied with no step between

The gate is a smoke suite that never runs the extractor — which is how a regression gets past a gate, and
why bisect exists. The last two patches land back to back, so blame can only credit them jointly; bisect
re-executes each candidate from the checkpoint on the same documents and names the one.

    python examples/toy_pipeline/regression.py --workdir /tmp/reg     # writes reg.audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentvcs as avcs  # noqa: E402
from agentvcs.integrations.openai_compat import OpenAICompatClient  # noqa: E402
from agentvcs.testing import FakeOpenAIServer  # noqa: E402

import pipeline  # noqa: E402

SMOKE = 'command: |-\n  echo \'{"metrics": {"smoke": 1}}\'\nthresholds:\n  smoke: {op: ">=", value: 1}\n'


def manifests(regress: bool = True) -> list[dict]:
    v2 = pipeline.add_cap_field(pipeline.base_manifest())
    m1 = pipeline.edited(v2, "v2.1", "summarize.prompt", ("template",),
                         "Summarize this contract in one sentence from the extracted terms, quoting every amount "
                         "exactly:\n{extraction}")
    m2 = pipeline.edited(m1, "v2.2", "extract.sampling", ("max_tokens",), 256)
    m3 = (pipeline.edited(m2, "v2.3", "extract.prompt", ("template",),
                          pipeline.EXTRACT_TEMPLATE.replace("{fields}", "supplier, term, cap_amount")) if regress else
          pipeline.edited(m2, "v2.3", "extract.prompt", ("system",), "You extract fields from contracts, verbatim."))
    m4 = pipeline.edited(m3, "v2.4", "check.sampling", ("max_tokens",), 64)
    return [v2, m1, m2, m3, m4]


def build(workdir: str, docs: int = 12, regress: bool = True) -> dict:
    os.makedirs(workdir, exist_ok=True)
    store = os.path.join(workdir, "store")
    avcs.open_store(store)                         # init
    suite = os.path.join(workdir, "smoke.yaml")
    with open(suite, "w") as f:
        f.write(SMOKE)
    ms = manifests(regress)
    ids = [avcs.cli("snapshot", _write(workdir, f"m{i}.json", m), store=store)["manifest_id"]
           for i, m in enumerate(ms)]
    when = {2: [1], 4: [2], 6: [3, 4]}            # after document i: patch to these manifests
    server = FakeOpenAIServer(pipeline.fake_respond).start()
    patches = []
    try:
        client = OpenAICompatClient(server.base_url)
        with avcs.run(ids[0], store=store, run_id="reg") as run:
            run.checkpoint(lambda step: f"doc:{step.step_index + 1}")

            @avcs.step("extractor", inputs=lambda doc: [doc.text])
            def extract(doc):
                c = client.complete("extract", {"document": doc.text})
                fields = pipeline.parse_json(c.text) or {}
                avcs.current_step().metric("extract.recall", pipeline.recall(fields, doc.gold))
                return fields

            for i, doc in enumerate(pipeline.documents(docs, 0)):
                for t in when.get(i, []):
                    pid = run.propose_patch(ids[t], rationale=ms[t]["name"])
                    assert run.gate(pid, suite)["passed"]
                    run.apply_patch(pid)
                    patches.append(pid)
                extract(doc)
    finally:
        server.stop()
    audit = os.path.join(workdir, "reg.audit.json")
    avcs.cli("export", "audit", "reg", "-o", audit, store=store)
    return {"audit": audit, "store": store, "manifests": ids, "patches": patches,
            "regression": patches[2] if regress else None}


def _write(workdir: str, name: str, m: dict) -> str:
    p = os.path.join(workdir, name)
    with open(p, "w") as f:
        json.dump(m, f)
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--no-regression", action="store_true",
                    help="the control: the third patch edits the extractor's system line instead")
    a = ap.parse_args()
    print(json.dumps(build(a.workdir, regress=not a.no_regression), indent=2))
