"""Plural Intelligence — correlation discounting for agent fleets.

As local inference approaches free, the temptation is brute force: deploy 100 copies
of your best agent at one problem. But clones share a Soul — the same SBTs, the same
blind spots — so they fail *together*. A correlated swarm buys far less than its head
count suggests. *Decentralized Society* §4.5/§5.2 names the fix: measure the
correlation between Souls and **discount it**, rewarding cooperation across genuinely
different lived experience.

This module applies that to AgentVCS. Each candidate is a Soul described by its
skill profile — the weighted skill→competence vector built from its SBTs
(``sbt.skill_profile``). Two Souls trained in the same "university" (same goals, same
crystallized recipes) have near-identical profiles and high correlation; a backend
specialist and a security auditor have low correlation. ``select_fleet`` greedily
assembles the team that maximizes total competence *after* discounting overlap, so a
fixed budget of N agents covers the most ground.

Pure functions over plain dicts — no crypto, no I/O. Feed it
``[{"soul": id, "profile": {tag: weight}}, ...]``.

Population-genetics note: correlation discounting is the *spatial* half of variant
diversity (who is in the fleet right now). Its *temporal* half — how variant
frequencies evolve as they compete for a shared task pool — is replicator dynamics,
``ẋᵢ = xᵢ(fᵢ − φ̄)``. agentvcs already measures the fitness differential that drives it
(``dynamics.price``: the selection term ``Cov(w, z)`` over sibling variants). If
variants ever start competing over one pool, this module's diversity score and that
selection term are the two inputs a replicator step would need.
"""
from __future__ import annotations

import math


def _dot(a: dict, b: dict) -> float:
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    return sum(v * large.get(k, 0.0) for k, v in small.items())


def _norm(a: dict) -> float:
    return math.sqrt(sum(v * v for v in a.values()))


def correlation(a: dict, b: dict) -> float:
    """Cosine similarity of two skill profiles, in [0, 1] for non-negative weights.
    1.0 = identical competence (redundant clones); 0.0 = disjoint expertise."""
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


def competence(profile: dict) -> float:
    """Scalar standing of a Soul: the total verified weight across its skills."""
    return float(sum(profile.values()))


def select_fleet(candidates: list[dict], size: int,
                 discount: float = 1.0) -> dict:
    """Pick ``size`` Souls maximizing *diversity-discounted* competence.

    ``candidates``: ``[{"soul": id, "profile": {tag: weight}}, ...]``.
    ``discount``: how hard to penalize correlation (0 = ignore overlap and just take
    the strongest; 1 = full correlation discounting, the DeSoc default).

    Greedy facility-location: seed with the most competent Soul, then repeatedly add
    the candidate whose marginal value — its competence minus ``discount`` times its
    peak correlation with anyone already chosen — is highest. Returns the chosen
    Souls in pick order plus the fleet's diversity score (mean pairwise distance)."""
    pool = [c for c in candidates if c.get("profile")]
    if not pool or size <= 0:
        return {"fleet": [], "diversity": 0.0, "discount": discount}
    size = min(size, len(pool))

    chosen: list[dict] = [max(pool, key=lambda c: competence(c["profile"]))]
    remaining = [c for c in pool if c is not chosen[0]]

    while len(chosen) < size and remaining:
        def marginal(c):
            peak = max(correlation(c["profile"], s["profile"]) for s in chosen)
            return competence(c["profile"]) - discount * peak * competence(c["profile"])
        nxt = max(remaining, key=marginal)
        chosen.append(nxt)
        remaining.remove(nxt)

    return {
        "fleet": [{"soul": c["soul"], "competence": round(competence(c["profile"]), 4)}
                  for c in chosen],
        "diversity": round(fleet_diversity(chosen), 4),
        "discount": discount,
    }


def fleet_diversity(fleet: list[dict]) -> float:
    """Mean pairwise (1 - correlation) across the fleet. 1.0 = fully complementary,
    0.0 = a monoculture of identical Souls."""
    profs = [c["profile"] for c in fleet if c.get("profile")]
    if len(profs) < 2:
        return 0.0
    total, pairs = 0.0, 0
    for i in range(len(profs)):
        for j in range(i + 1, len(profs)):
            total += 1.0 - correlation(profs[i], profs[j])
            pairs += 1
    return total / pairs if pairs else 0.0
