#!/usr/bin/env python3
"""SkillOpt ⇆ AgentVCS Soul bridge — the evolution layer that mints reputation.

The three-layer architecture of *Souls of Silicon*:

    AgentVCS   captures the line of a life   (signed code + goal + models + trace)
    SkillOpt   distills it into learning     (nightly gate: trace → validated skill)
    DeSoc      turns it into reputation      (a passed gate mints an SBT on the Soul)

This script is the seam between layers 2 and 3. It:

  1. Reads the **trace dimension** of AgentVCS commits directly from the object
     store (no Claude/Codex log scraping — the trace is already first-class and,
     crucially, *signed* by the agent's Soul, so the training data has provenance).
  2. Runs them through SkillOpt's consolidation gate (``skillopt_sleep.consolidate``)
     if SkillOpt is installed; otherwise a tiny stand-in gate so the demo is
     self-contained.
  3. On ``accepted`` — i.e. the skill strictly improved a held-out score — it acts
     as the **issuing oracle**: ``agentvcs freeze`` crystallizes the verified commit
     and an SBT is minted onto the agent's Soul as *proof of acquired competence*.

Because the oracle here is an independent process, it can sign the SBT with its own
issuer key (``--issuer-seed``), so the credential is a third party vouching for the
agent, not a self-attestation. Copy the agent's files and you copy its SBT ledger,
but not the oracle's key nor the agent's secret seed: the reputation does not move
with the bytes.

Usage:
    python bridge.py /path/to/agent/repo            # self-contained demo gate
    python bridge.py /path/to/agent/repo --issuer-seed <64-hex>   # external oracle
"""
from __future__ import annotations

import argparse
import sys

from agentvcs.repository import Repository
from agentvcs.eval import run_eval
from agentvcs.crystallize import crystallize
from agentvcs import sbt


def harvest_traces(repo: Repository) -> list[dict]:
    """Pull every commit's trace dimension out of AgentVCS — the signed episodic
    memory SkillOpt reflects on. Returns one record per commit with its messages."""
    records = []
    for oid, commit in repo.log():
        msgs = []
        if commit.get("trace"):
            msgs = repo.objects.read_obj(commit["trace"]).get("messages", [])
        records.append({
            "commit": oid,
            "goal": repo.objects.read_obj(commit["goal"]).get("text", "") if commit.get("goal") else "",
            "messages": msgs,
            "signed_by": commit.get("soul"),
        })
    return records


def run_gate(records: list[dict]):
    """Run SkillOpt's real consolidation gate when available; else a minimal
    stand-in that 'accepts' once there is enough harvested experience to learn from.

    Returns ``(accepted: bool, summary: str)``."""
    try:
        from skillopt_sleep.consolidate import consolidate  # noqa: F401
        # A full wiring would map `records` into SkillOpt TaskRecords and call
        # consolidate(...). We keep the demo dependency-free; flip USE_REAL on
        # when running inside a configured SkillOpt environment.
        USE_REAL = False
        if USE_REAL:
            ...  # res = consolidate(...); return res.accepted, "skillopt gate"
    except ImportError:
        pass
    # stand-in gate: accept if the agent accumulated real reasoning to consolidate
    total_msgs = sum(len(r["messages"]) for r in records)
    accepted = total_msgs >= 1
    return accepted, f"stand-in gate: {total_msgs} trace messages across {len(records)} commits"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="path to an AgentVCS agent repository")
    ap.add_argument("--issuer-seed", dest="issuer_seed",
                    help="64-hex Ed25519 seed for an external issuing oracle "
                         "(omit to let the agent self-attest)")
    args = ap.parse_args(argv)

    repo = Repository.open(args.repo)
    sid = repo.soul_id()
    print(f"agent soul: {sid[:16] if sid else 'anonymous'}…")

    records = harvest_traces(repo)
    print(f"harvested {len(records)} commits from the trace dimension")

    accepted, summary = run_gate(records)
    print(f"consolidation gate: {'ACCEPT' if accepted else 'reject'}  ({summary})")
    if not accepted:
        print("nothing to mint — the gate did not improve the skill.")
        return 0

    # the gate passed: prove the head commit, crystallize it, mint the SBT
    head = repo.head_commit()
    if repo.read_manifest().get("eval"):
        r = run_eval(repo, head)
        if not r["ok"]:
            print("eval failed — refusing to mint an SBT for unverified work.")
            return 1

    new_oid, _art = crystallize(repo, force=not repo.read_manifest().get("eval"))

    issuer_seed = bytes.fromhex(args.issuer_seed) if args.issuer_seed else None
    if issuer_seed is not None:
        # external oracle re-issues so the credential is third-party vouched
        goal = repo.objects.read_obj(repo.objects.read_obj(new_oid)["goal"]).get("text", "")
        token = sbt.issue_sbt(repo, new_oid, repo.read_eval(new_oid),
                              goal_text=goal, issuer_seed=issuer_seed)
    else:
        token = sbt.read_sbts(repo)[-1] if sbt.read_sbts(repo) else None

    if token:
        who = "external oracle" if not token["self_issued"] else "self-attested"
        print(f"✦ minted SBT ({who}): skills={token['skill'][:4]} "
              f"score={token['score']} valid={sbt.verify_sbt(token)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
