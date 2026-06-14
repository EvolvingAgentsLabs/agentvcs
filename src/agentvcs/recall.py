"""Recall — the cache reflex a closed runtime never gives the agent.

A runtime re-reasons every task from scratch; it has no memory that "this exact
goal was already solved, here is the frozen recipe, replay it for ~$0". agentvcs
*does* have that memory — every ``crystallize`` leaves a deterministic recipe
keyed by its goal. ``recall`` is the lookup over it: given a goal, rank the
crystallized commits whose goals overlap, so the agent can ``replay`` a proven
solution instead of paying to rediscover it.

Scoring is deliberately dependency-free — token-overlap (Jaccard) over the goal
text, lowercased and split on non-word characters. It is a *retrieval* signal,
not a guarantee: recall returns ranked candidates, and the trust gate is the
crystallized recipe itself (it only exists because the solution was frozen).
Swapping in embeddings later is a one-function change and an optional extra.
"""
from __future__ import annotations

import re

from .repository import Repository

_WORD = re.compile(r"\w+")


def _tokens(text: str) -> set:
    # drop 1-2 char tokens ("a", "3d", "of") — stopword noise that inflates the
    # overlap score and makes unrelated goals look like weak hits.
    return {t for t in _WORD.findall((text or "").lower()) if len(t) > 2}


def _score(query: set, goal: set) -> float:
    if not query or not goal:
        return 0.0
    inter = len(query & goal)
    union = len(query | goal)
    return round(inter / union, 4) if union else 0.0


def _crystallized_commits(repo: Repository):
    """Every crystallized commit in the object store, with its recipe goal. We
    scan the store directly so recall sees frozen recipes on *any* branch, not
    just the current history."""
    root = repo.objects.root
    if not root.is_dir():
        return
    for bucket in root.iterdir():
        if not bucket.is_dir():
            continue
        for blob in bucket.iterdir():
            oid = bucket.name + blob.name
            try:
                obj = repo.objects.read_obj(oid)
            except Exception:
                continue  # blobs and non-JSON objects
            if obj.get("type") != "commit" or obj.get("state") != "crystallized":
                continue
            goal = ""
            crystal = obj.get("crystal")
            if crystal:
                try:
                    goal = repo.objects.read_obj(crystal).get("goal", "")
                except Exception:
                    goal = ""
            if not goal:
                try:
                    goal = repo.objects.read_obj(obj["goal"]).get("text", "")
                except Exception:
                    goal = ""
            yield oid, obj, goal


def recall(repo: Repository, query: str, limit: int = 5, min_score: float = 0.0,
           verified_only: bool = False) -> list:
    """Rank crystallized recipes by goal similarity to ``query``. Each hit is
    ``{commit, goal, score, verified, eval_score, replay_ready}``. **Verified**
    recipes (those that passed their eval gate) rank ahead of look-alikes, so an
    agent replays a solution that is *known* to work — feed ``commit`` straight to
    ``agentvcs replay``."""
    q = _tokens(query)
    hits = []
    for oid, _commit, goal in _crystallized_commits(repo):
        s = _score(q, _tokens(goal))
        if s < min_score:
            continue
        ev = repo.read_eval(oid)
        verified = bool(ev and ev.get("ok"))
        if verified_only and not verified:
            continue
        hits.append({"commit": oid, "goal": goal, "score": s,
                     "verified": verified,
                     "eval_score": ev.get("score") if ev else None,
                     "replay_ready": True})
    # trust first (verified ahead of unverified), then goal match, then stable id
    hits.sort(key=lambda h: (not h["verified"], -h["score"], h["commit"]))
    return hits[:limit]
