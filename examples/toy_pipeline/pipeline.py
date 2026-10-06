"""The toy pipeline's shared pieces: documents, manifests, the deterministic fake
model, scoring. Harness, supervisor and gate import this; none of them shares
state with another except through the agentvcs store and the model endpoint.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import random
import re
from typing import Optional

PARTIES = ["Acme Robotics", "Globex Corporation", "Initech LLC", "Umbrella Health",
           "Stark Components", "Wayne Logistics", "Hooli Cloud", "Vandelay Imports",
           "Soylent Foods", "Tyrell Systems", "Cyberdyne Labs", "Wonka Industries"]
LAWS = ["New York", "Delaware", "England and Wales", "Ontario", "Singapore"]
FIELDS = ("party", "term", "cap_amount")


@dataclasses.dataclass(frozen=True)
class Doc:
    doc_id: str
    text: str
    gold: dict


def documents(n: int, seed: int = 0) -> list[Doc]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        party = rng.choice(PARTIES)
        term = f"{rng.choice([6, 12, 18, 24, 36, 48, 60])} months"
        cap = f"USD {rng.randrange(50, 5000) * 1000:,}"
        law = rng.choice(LAWS)
        text = (
            f"MASTER SERVICES AGREEMENT No. {seed}-{i}. This agreement is made between "
            f"{party} (\"Supplier\") and Northwind Ltd (\"Customer\"). The term of this "
            f"agreement is {term} from the effective date. The Supplier's aggregate "
            f"liability under this agreement shall not exceed {cap}. This agreement is "
            f"governed by the laws of {law}."
        )
        out.append(Doc(f"{seed}-{i}", text, {"party": party, "term": term, "cap_amount": cap}))
    return out


# ------------------------------------------------------------------ manifests

def _agent(name: str, system: str, template: str, variables: list, provider: str, model: str,
           max_tokens: int) -> dict:
    return {
        f"{name}.prompt": {"kind": "prompt", "content": {"system": system, "template": template, "variables": variables}},
        f"{name}.model": {"kind": "model", "content": {"provider": provider, "id": model}},
        f"{name}.sampling": {"kind": "sampling", "content": {"temperature": 0.0, "seed": 7, "max_tokens": max_tokens}},
    }


EXTRACT_TEMPLATE = (
    "Fields: {fields}\n"
    "For each field, copy its value verbatim from the document. Reply with a single "
    "JSON object whose keys are exactly the field names above, and nothing else.\n"
    "Document:\n{document}"
)


def base_manifest(provider: str = "fake", model: str = "toy-fake") -> dict:
    """v1: the extraction prompt never asks for the liability cap."""
    dims = {}
    dims.update(_agent(
        "extract", "You extract fields from contracts.",
        EXTRACT_TEMPLATE.replace("{fields}", "party, term"), ["document"], provider, model, 128))
    dims.update(_agent(
        "check", "You audit contract extractions.",
        "Document:\n{document}\nExtraction:\n{extraction}\n"
        "Which of these terms appear in the document but are missing from the extraction: "
        "party, term, cap_amount? Reply OK if none are missing, otherwise "
        "MISSING: followed by the comma-separated names.",
        ["document", "extraction"], provider, model, 32))
    dims.update(_agent(
        "summarize", "You write one-sentence contract summaries.",
        "Write one sentence summarizing this contract from the extracted terms, "
        "quoting every amount exactly:\n{extraction}",
        ["extraction"], provider, model, 96))
    return {"protocol": "agentvcs/0.1", "type": "harness_manifest", "name": "toy-pipeline v1",
            "dimensions": dims}


def add_cap_field(manifest: dict) -> dict:
    """The supervisor's patch: ask the extractor for the cap amount too."""
    m = copy.deepcopy(manifest)
    m["name"] = "toy-pipeline v2"
    m["parent_ids"] = []
    c = m["dimensions"]["extract.prompt"]["content"]
    c["template"] = EXTRACT_TEMPLATE.replace("{fields}", "party, term, cap_amount")
    m["dimensions"]["extract.prompt"].pop("content_hash", None)
    m.pop("manifest_id", None)
    return m


# ------------------------------------------------------------------ the fake model

_RX = {
    "party": re.compile(r'between (.+?) \("Supplier"\)'),
    "term": re.compile(r"\b(\d+ months)\b"),
    "cap_amount": re.compile(r"\b(USD [\d,]+)"),
}


def _section(text: str, label: str) -> str:
    m = re.search(label + r":\n(.*?)(?:\n[A-Z][a-z]+:\n|\Z)", text, re.S)
    return m.group(1) if m else ""


def fake_respond(request: dict) -> str:
    """A deterministic stand-in for a model. It sees only the request — exactly
    what a real server would see — so the pipeline's behaviour can change only
    through what the manifest puts in the prompt."""
    user = request["messages"][-1]["content"]
    if user.startswith("Fields:"):
        wanted = [f.strip() for f in user.splitlines()[0][len("Fields:"):].split(",")]
        doc = user.split("Document:\n", 1)[1]
        out = {}
        for f in wanted:
            rx = _RX.get(f)
            m = rx.search(doc) if rx else None
            out[f] = m.group(1) if m else None
        return json.dumps(out)
    if "\nExtraction:\n" in user:
        doc = user.split("Document:\n", 1)[1].split("\nExtraction:\n", 1)[0]
        extraction = parse_json(user.split("\nExtraction:\n", 1)[1]) or {}
        missing = [f for f in FIELDS if _RX[f].search(doc) and not extraction.get(f)]
        return "OK" if not missing else "MISSING: " + ", ".join(missing)
    if user.startswith("Write one sentence"):
        ex = parse_json(user.split(":\n", 1)[1]) or {}
        s = f"Agreement with {ex.get('party') or 'an unnamed supplier'} for {ex.get('term') or 'an unstated term'}"
        if ex.get("cap_amount"):
            s += f", liability capped at {ex['cap_amount']}"
        return s + "."
    return "I do not understand the request."


# ------------------------------------------------------------------ scoring

def parse_json(text: str) -> Optional[dict]:
    """The first JSON object in a model reply (real models wrap it in prose/fences)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start:i + 1])
                        return v if isinstance(v, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def recall(extraction: Optional[dict], gold: dict) -> float:
    """Fraction of the gold fields extracted with the right value."""
    ex = extraction or {}
    return sum(1 for f in FIELDS if _norm(ex.get(f)) == _norm(gold[f]) and gold[f]) / len(FIELDS)
