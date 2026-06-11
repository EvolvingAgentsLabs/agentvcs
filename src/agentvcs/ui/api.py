"""The read-only JSON API behind the dashboard.

``handle(repo, route, query)`` is a pure function: it takes the parsed request
(path already split into segments, query as a dict) and returns
``(status_code, body_dict)``. It never touches a socket, so the whole API surface
can be unit-tested by calling it directly against a temp repository.

Every body reuses the exact shapes from :mod:`agentvcs.views` — the same dicts the
CLI prints under ``--json`` — so the dashboard and the terminal can never drift.
Success bodies are ``{"ok": true, ...}``; errors are
``{"ok": false, "error": {"code", "message"}}`` with the stable RepoError code,
mirroring the agent-mode contract in ``docs/AGENT_MODE.md``.
"""
from __future__ import annotations

from .. import views
from ..repository import Repository, RepoError

# RepoError codes that mean "the client asked for something that isn't there",
# mapped to 404; everything else is a 400 (a malformed request).
_NOT_FOUND_CODES = {"BAD_REF", "AMBIGUOUS_REF", "NO_COMMITS"}


def _ok(data: dict) -> tuple[int, dict]:
    return 200, {"ok": True, **data}


def _err(code: str, message: str) -> tuple[int, dict]:
    status = 404 if code in _NOT_FOUND_CODES else 400
    return status, {"ok": False, "error": {"code": code, "message": message}}


def handle(repo: Repository, route: list[str], query: dict) -> tuple[int, dict]:
    """Dispatch ``GET /api/<route...>`` to a view. ``route`` is the path segments
    after ``/api`` (e.g. ``["commit", "<oid>", "trace"]``); ``query`` is the parsed
    query string (values are single strings)."""
    try:
        return _dispatch(repo, route, query)
    except RepoError as e:
        return _err(e.code, str(e))


def _dispatch(repo: Repository, route: list[str], query: dict) -> tuple[int, dict]:
    if route == ["repo"]:
        return _ok(views.repo_view(repo))

    if route == ["log"]:
        return _ok(views.log_view(repo))

    if route == ["diff"]:
        b = repo._resolve(query["b"], expect="commit") if query.get("b") else repo.head_commit()
        if not b:
            return _err("NO_COMMITS", "no commits yet")
        if query.get("a"):
            a = repo._resolve(query["a"], expect="commit")
        else:
            a = (repo.objects.read_obj(b)["parents"] or [None])[0]
        return _ok(views.diff_view(repo, a, b))

    if route and route[0] == "commit" and len(route) in (2, 3):
        oid = repo._resolve(route[1], expect="commit")
        if len(route) == 2:
            return _ok({"commit": views.commit_view(repo, oid, include_trace=False)})
        if route[2] == "trace":
            return _ok({"trace": views.commit_view(repo, oid, include_trace=True)["trace"]})

    return _err("BAD_ROUTE", f"no such endpoint: /api/{'/'.join(route)}")
