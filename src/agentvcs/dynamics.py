"""Evolutionary diagnostics over the commit graph.

agentvcs is the only tool that stores an agent's *recorded lineage*: every
iteration as a commit, with an eval score attributed per commit. That makes it the
natural — and only — place to answer a question a plain VCS cannot: is the agent's
self-modification loop actually *improving*, or is it degrading faster than
selection can recover?

Three pure-function diagnostics, standard library only, computed over data agentvcs
already stores (the commit DAG in the object store + the eval side-table):

  * ``price``   — Price-equation decomposition. How much of the trait change came
    from **selecting between branches** (``Cov(w, z)``) versus **editing within a
    lineage** (``E[w·Δz]``), plus the Eigen error-catastrophe verdict: the crossing
    where within-lineage degradation overtakes the selection differential. Fitness
    ``w`` is offspring count — the textbook Price definition (how many children a
    commit spawned); the trait ``z`` is a commit's eval score (default), its spec
    size in files, or its recorded cost.
  * ``slowing`` — critical-slowing-down early warning. Rising lag-1 autocorrelation
    and variance in the eval-score series flag an approaching collapse *before* the
    mean moves (Scheffer 2009).
  * ``ratchet`` — Muller's-ratchet load on unmerged branches. A long asexual lineage
    accumulates deleterious edits it cannot purge without recombination (``merge``);
    this quantifies the case for merging a diverged branch back.

Every function degrades gracefully when there aren't enough eval'd commits and says
so (``insufficient: true``) rather than inventing a number.

Honesty caveats worth carrying in the output, not just the docs:
  * The Eigen threshold is sharp only on a single-peak landscape; on rugged
    landscapes it softens (Wiehe 1997). Read the crossing as an order-of-magnitude
    signal, not a cliff.
  * Slowing-down needs a real time series of scored commits to mean anything.
"""
from __future__ import annotations

from .merge import merge_base
from .repository import Repository, RepoError

TRAITS = ("score", "size", "cost")


# --------------------------------------------------------------- graph helpers
def _reachable(repo: Repository) -> dict:
    """Every commit reachable from HEAD or any branch tip, as ``{oid: commit}``.

    Walks the full parent DAG (both parents of a merge), unlike ``repo.log`` which
    follows only the first parent."""
    tips = set(repo.branches().values())
    head = repo.head_commit()
    if head:
        tips.add(head)
    seen: dict = {}
    stack = list(tips)
    while stack:
        oid = stack.pop()
        if not oid or oid in seen:
            continue
        try:
            commit = repo.objects.read_obj(oid)
        except Exception:
            continue
        seen[oid] = commit
        for p in (commit.get("parents") or []):
            if p not in seen:
                stack.append(p)
    return seen


def _children_map(commits: dict) -> dict:
    children: dict = {}
    for oid, commit in commits.items():
        for p in (commit.get("parents") or []):
            children.setdefault(p, []).append(oid)
    return children


def _descendants(commits: dict, root: str) -> set:
    """``root`` and everything reachable *forward* from it (inclusive)."""
    children = _children_map(commits)
    seen: set = set()
    stack = [root]
    while stack:
        oid = stack.pop()
        if oid in seen or oid not in commits:
            continue
        seen.add(oid)
        stack.extend(children.get(oid, []))
    return seen


def _under(path: str, prefixes) -> bool:
    for pre in prefixes:
        if pre.endswith("/"):
            if path.startswith(pre):
                return True
        elif path == pre or path.startswith(pre + "/"):
            return True
    return False


def _trait_fn(repo: Repository, trait: str, editable):
    """Return ``f(oid, commit) -> float | None`` for the requested trait."""
    if trait == "score":
        def f(oid, commit):
            ev = repo.read_eval(oid)
            s = ev.get("score") if ev else None
            return float(s) if isinstance(s, (int, float)) else None
        return f
    if trait == "size":
        def f(oid, commit):
            try:
                entries = repo.objects.read_obj(commit["tree"]).get("entries", {})
            except Exception:
                return None
            if editable:
                return float(sum(1 for p in entries if _under(p, editable)))
            return float(len(entries))
        return f
    if trait == "cost":
        def f(oid, commit):
            m = commit.get("metrics") or {}
            for k in ("cost_usd", "cost", "usd"):
                v = m.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
            return None
        return f
    raise RepoError(f"unknown trait '{trait}' (want one of {', '.join(TRAITS)})",
                    code="BAD_TRAIT")


def _r(x, nd=6):
    return round(x, nd) if isinstance(x, (int, float)) else x


# ---------------------------------------------------------------- Price equation
def price(repo: Repository, since: str | None = None, trait: str = "score",
          editable=None) -> dict:
    """Decompose the change in the mean trait into selection + transmission.

    Price's identity, with fitness = offspring count::

        w̄·Δz̄ = Cov(wᵢ, zᵢ) + E[wᵢ·Δzᵢ]
                └ selection ┘   └ transmission ┘

    Each *parent* commit i (with a trait value and ≥1 scored child) contributes:
      * ``wᵢ`` = number of its children that carry a trait value (reproductive success)
      * ``zᵢ`` = the parent's own trait
      * ``Δzᵢ`` = (mean child trait) − ``zᵢ``  (within-lineage editing effect)

    ``Cov(w, z)`` is the **selection** term — did higher-quality commits get extended
    more? ``E[w·Δz]`` is the **transmission** term — when a commit spawns children,
    are they better or worse than it? A negative transmission term is exactly the
    Eigen mutational-degradation signal.

    A purely linear history (no branch points) has zero between-branch selection by
    construction: *all* its trait change is transmission — which is precisely the
    asexual regime where the error catastrophe bites. The decomposition surfaces that
    for free.
    """
    commits = _reachable(repo)
    if editable is None:
        editable = repo.read_manifest().get("editable")
    tf = _trait_fn(repo, trait, editable)
    children = _children_map(commits)

    allowed = None
    since_oid = None
    if since:
        since_oid = repo._resolve(since, expect="commit")
        allowed = _descendants(commits, since_oid)

    rows = []  # (w, z, dz)
    for p, kids in children.items():
        if allowed is not None and p not in allowed:
            continue
        pc = commits.get(p)
        if pc is None:
            continue
        zp = tf(p, pc)
        if zp is None:
            continue
        kid_traits = [t for k in kids
                      if (t := tf(k, commits[k])) is not None]
        if not kid_traits:
            continue
        w = float(len(kid_traits))
        rows.append((w, zp, sum(kid_traits) / len(kid_traits) - zp))

    n = len(rows)
    # L_effective context: the editable surface is what actually competes with ln σ / μ
    head = repo.head_commit()
    l_total = l_eff = None
    if head:
        try:
            entries = repo.objects.read_obj(
                repo.objects.read_obj(head)["tree"]).get("entries", {})
            l_total = len(entries)
            if editable:
                l_eff = sum(1 for pth in entries if _under(pth, editable))
        except Exception:
            pass

    base = {"trait": trait, "since": since_oid, "n_parents": n,
            "editable": editable, "l_total": l_total, "l_effective": l_eff}
    if n < 2:
        return {**base, "insufficient": True,
                "message": "need ≥2 eval'd branch points to decompose — keep "
                           "committing with evals (`agentvcs eval`) on each variant"}

    ws = [r[0] for r in rows]
    zs = [r[1] for r in rows]
    dzs = [r[2] for r in rows]
    wbar = sum(ws) / n
    zbar = sum(zs) / n
    cov_wz = sum(ws[i] * zs[i] for i in range(n)) / n - wbar * zbar
    e_wdz = sum(ws[i] * dzs[i] for i in range(n)) / n
    selection_c = cov_wz / wbar if wbar else 0.0        # contribution to Δz̄
    transmission_c = e_wdz / wbar if wbar else 0.0
    delta_zbar = selection_c + transmission_c

    degrading = e_wdz < 0
    crossed = degrading and abs(e_wdz) > abs(cov_wz)
    if crossed:
        reading = ("ERROR CATASTROPHE: within-lineage editing is losing trait value "
                   "faster than selection recovers it — freeze the editable surface "
                   "or raise eval coverage")
    elif degrading:
        reading = ("within-lineage editing is degrading the trait, but selection "
                   "between branches still dominates — watch the trend")
    elif selection_c > abs(transmission_c):
        reading = "improvement is selection-driven (choosing well between branches)"
    else:
        reading = "improvement is transmission-driven (editing well within a lineage)"

    return {
        **base,
        "insufficient": False,
        "selection": _r(cov_wz),           # Cov(w, z)
        "transmission": _r(e_wdz),         # E[w·Δz]
        "selection_contrib": _r(selection_c),   # per-Price contribution to Δz̄
        "transmission_contrib": _r(transmission_c),
        "delta_zbar": _r(delta_zbar),
        "wbar": _r(wbar),
        "reading": reading,
        "threshold": {
            "crossed": crossed,
            "code": "ERROR_CATASTROPHE" if crossed else None,
            "degrading": degrading,
            "note": "sharp only on a single-peak landscape; treat as order-of-"
                    "magnitude, not a cliff (Wiehe 1997)",
        },
    }


# ----------------------------------------------------------- critical slowing down
def _pvar(xs) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / n


def slowing(repo: Repository, window: int | None = None) -> dict:
    """Critical-slowing-down early warning over the eval-score time series.

    Rising lag-1 autocorrelation and rising variance precede a bifurcation — a
    leading indicator that the loop is approaching instability *before* the mean
    score moves. Cheap statistics over the ``ts``/``score`` already in the eval
    side-table."""
    commits = _reachable(repo)
    series = []
    for oid, commit in commits.items():
        ev = repo.read_eval(oid)
        if ev and isinstance(ev.get("score"), (int, float)):
            series.append((commit.get("timestamp", 0), float(ev["score"])))
    series.sort()
    scores = [s for _, s in series]
    if window and window > 0:
        scores = scores[-window:]
    n = len(scores)
    if n < 4:
        return {"n": n, "insufficient": True,
                "message": "need ≥4 eval'd commits for a slowing-down signal"}

    mean = sum(scores) / n
    ss = sum((x - mean) ** 2 for x in scores)
    if ss == 0:
        lag1 = 0.0
    else:
        num = sum((scores[i] - mean) * (scores[i + 1] - mean) for i in range(n - 1))
        lag1 = num / ss

    half = n // 2
    v_early, v_late = _pvar(scores[:half]), _pvar(scores[half:])
    if v_late > v_early * 1.15:
        trend = "rising"
    elif v_late < v_early * 0.85:
        trend = "falling"
    else:
        trend = "flat"

    signal = trend == "rising" and lag1 > 0.4
    if signal:
        warning = "approaching_instability"
    elif trend == "rising" or lag1 > 0.6:
        warning = "watch"
    else:
        warning = "stable"

    return {"n": n, "insufficient": False, "lag1_autocorr": _r(lag1),
            "variance_early": _r(v_early), "variance_late": _r(v_late),
            "variance_trend": trend, "signal": signal, "warning": warning}


# --------------------------------------------------------------- Muller's ratchet
def _first_parent_chain(repo: Repository, tip: str, base: str | None) -> list:
    """Commits from just-after ``base`` up to ``tip`` (inclusive), oldest first,
    following first parents."""
    chain = []
    oid = tip
    seen = set()
    while oid and oid != base and oid not in seen:
        seen.add(oid)
        chain.append(oid)
        try:
            ps = repo.objects.read_obj(oid).get("parents") or []
        except Exception:
            break
        oid = ps[0] if ps else None
    chain.reverse()
    return chain


def _pick_trunk(repo: Repository, branches: dict) -> str | None:
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    # otherwise the branch with the longest first-parent history
    best, best_len = None, -1
    for name, tip in branches.items():
        length = len(_first_parent_chain(repo, tip, None))
        if length > best_len:
            best, best_len = name, length
    return best


def ratchet(repo: Repository, trunk: str | None = None, long_at: int = 5) -> dict:
    """Muller's-ratchet load on branches that have diverged without merging.

    An asexual lineage (a branch that never merges) irreversibly accumulates
    deleterious edits: once the least-loaded variant class is lost it cannot be
    recovered without recombination — and ``merge --reconcile`` *is* the
    recombination operator. This flags long, unmerged, non-improving branches as the
    ones most worth merging back.

    Per non-trunk branch it reports the divergence ``distance`` from its merge-base
    with the trunk, the eval trend across the branch, and ``deleterious_steps`` (edges
    where the score dropped and was never purged — the ratchet clicks)."""
    branches = repo.branches()
    trunk = trunk or _pick_trunk(repo, branches)
    out = {"trunk": trunk, "branches": [], "warnings": []}
    if not trunk or len(branches) < 2:
        return out

    trunk_tip = branches[trunk]
    for name, tip in sorted(branches.items()):
        if name == trunk:
            continue
        base = merge_base(repo, tip, trunk_tip)
        chain = _first_parent_chain(repo, tip, base)
        distance = len(chain)
        if distance == 0:
            continue  # merged / not ahead of trunk

        pts = [base] + chain if base else chain
        scores = []
        for oid in pts:
            ev = repo.read_eval(oid)
            scores.append(ev.get("score") if ev and isinstance(
                ev.get("score"), (int, float)) else None)
        graded = [s for s in scores if s is not None]
        deleterious = sum(1 for i in range(1, len(scores))
                          if scores[i] is not None and scores[i - 1] is not None
                          and scores[i] < scores[i - 1])
        base_score = scores[0] if scores else None
        tip_score = scores[-1] if scores else None

        long = distance >= long_at
        if long and graded and tip_score is not None and base_score is not None \
                and (tip_score < base_score or deleterious > 0):
            risk = "high"
        elif long:
            risk = "medium"
        else:
            risk = "none"

        entry = {"branch": name, "base": base, "distance": distance,
                 "base_score": _r(base_score) if base_score is not None else None,
                 "tip_score": _r(tip_score) if tip_score is not None else None,
                 "deleterious_steps": deleterious, "clicks": deleterious, "risk": risk}
        out["branches"].append(entry)
        if risk == "high":
            out["warnings"].append(
                f"branch '{name}' is a long unmerged lineage "
                f"({distance} commits, {deleterious} deleterious step(s)) losing "
                f"fitness — merge it back into '{trunk}' to reconstitute the "
                f"least-loaded class")
        elif risk == "medium":
            reason = ("no evals to assess load" if not graded
                      else "not improving over its base")
            out["warnings"].append(
                f"branch '{name}' has diverged {distance} commits without merging "
                f"({reason}) — recombine with '{trunk}' before the ratchet clicks")
    return out


# ---------------------------------------------------------------------- health
def health(repo: Repository, trait: str = "score") -> dict:
    """One-stop 'is my evolution healthy?' rollup: Price verdict + slowing signal +
    ratchet load, with a flat ``warnings`` list an agent can branch on."""
    pr = price(repo, trait=trait)
    sl = slowing(repo)
    rt = ratchet(repo)
    warnings = list(rt.get("warnings", []))
    if not pr.get("insufficient") and pr.get("threshold", {}).get("crossed"):
        warnings.append("ERROR_CATASTROPHE: self-improvement loop is degrading "
                        "(within-lineage editing outruns selection) — freeze or "
                        "raise eval coverage")
    if not sl.get("insufficient") and sl.get("signal"):
        warnings.append("critical slowing down: variance and autocorrelation rising "
                        "— the loop may be approaching a collapse")
    healthy = not warnings
    return {"healthy": healthy, "price": pr, "slowing": sl, "ratchet": rt,
            "warnings": warnings}
