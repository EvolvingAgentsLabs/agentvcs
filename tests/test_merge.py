"""Tests for agentvcs merge (Feature A)."""
import json
import sys

import pytest

from agentvcs import Repository, RepoError
from agentvcs.merge import merge, merge_base


# ------------------------------------------------------------------ helpers

def setup_repo(tmp_path, goal="initial goal", file_content="line1\nline2\nline3\n"):
    repo = Repository.init(tmp_path)
    (tmp_path / "agent.json").write_text(json.dumps({
        "goal": goal,
        "models": [{"provider": "anthropic", "model": "claude-opus-4-8",
                    "params": {"temperature": 1.0}}],
        "trace": None,
        "state": "fluid",
    }))
    (tmp_path / "main.py").write_text(file_content)
    return repo


def commit_with(repo, tmp_path, goal=None, file_content=None, filename="main.py",
                message="commit"):
    if goal is not None:
        manifest = json.loads((tmp_path / "agent.json").read_text())
        manifest["goal"] = goal
        (tmp_path / "agent.json").write_text(json.dumps(manifest))
    if file_content is not None:
        (tmp_path / filename).write_text(file_content)
    return repo.commit(message)


# ------------------------------------------------------------------ merge_base tests

def test_merge_base_diamond(tmp_path):
    """Diamond DAG: A -> B, A -> C, B -> D, C -> D. merge_base(B, C) == A."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, message="A")

    # Branch to B
    repo.branch("branch-b")
    repo.checkout("branch-b")
    b = commit_with(repo, tmp_path, file_content="branch-b content\n", message="B")

    # Back to main, branch to C
    repo.checkout("main")
    repo.branch("branch-c")
    repo.checkout("branch-c")
    c = commit_with(repo, tmp_path, file_content="branch-c content\n", message="C")

    lca = merge_base(repo, b, c)
    assert lca == a, f"Expected LCA={a[:8]}, got {lca[:8] if lca else None}"


def test_merge_base_linear(tmp_path):
    """Linear chain: A -> B -> C. merge_base(A, C) == A."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, message="A")
    commit_with(repo, tmp_path, file_content="v2\n", message="B")
    c = commit_with(repo, tmp_path, file_content="v3\n", message="C")

    lca = merge_base(repo, a, c)
    assert lca == a


def test_merge_base_no_common(tmp_path):
    """Two repos with no common ancestor → None."""
    repo = setup_repo(tmp_path)
    a = commit_with(repo, tmp_path, message="A")

    # Simulate a detached commit with no parents
    detached_oid = repo.objects.write_obj({
        "type": "commit",
        "parents": [],
        "tree": repo.objects.read_obj(a)["tree"],
        "goal": repo.objects.read_obj(a)["goal"],
        "models": [],
        "trace": None,
        "state": "fluid",
        "metrics": {},
        "message": "detached",
        "author": "test",
        "timestamp": 0,
    })
    lca = merge_base(repo, a, detached_oid)
    assert lca is None


# ------------------------------------------------------------------ clean three-way merge

def test_clean_merge_theirs_only_change(tmp_path):
    """File changed only on theirs → taken in merge."""
    repo = setup_repo(tmp_path, file_content="shared\n")
    commit_with(repo, tmp_path, message="base")

    # Create theirs branch
    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="shared\ntheirs added\n",
                         message="theirs")

    # Back to main — make a commit that doesn't touch main.py so ours diverges
    repo.checkout("main")
    commit_with(repo, tmp_path, goal="ours goal", message="ours")

    result = merge(repo, "feature")
    assert result["status"] == "merged"
    assert result["conflicts"] == []
    merged_content = (tmp_path / "main.py").read_text()
    assert "theirs added" in merged_content


def test_clean_merge_ours_only_change(tmp_path):
    """File changed only on ours → kept in merge."""
    repo = setup_repo(tmp_path, file_content="shared\n")
    commit_with(repo, tmp_path, message="base")

    # Create theirs branch (no change to main.py)
    repo.branch("feature")
    repo.checkout("feature")
    (tmp_path / "other.py").write_text("other\n")
    commit_with(repo, tmp_path, message="theirs adds other.py")

    # Back to main, change main.py
    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="shared\nours added\n",
                       message="ours")

    result = merge(repo, "feature")
    assert result["status"] == "merged"
    assert result["conflicts"] == []
    merged_content = (tmp_path / "main.py").read_text()
    assert "ours added" in merged_content
    assert (tmp_path / "other.py").exists()


# ------------------------------------------------------------------ conflict tests

def test_conflict_no_force_no_commit(tmp_path):
    """Conflicting edit → markers present, status==conflict, no new commit."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")
    repo.head_commit()

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path,
                         file_content="line1\nTHEIRS changed line2\nline3\n",
                         message="theirs")

    repo.checkout("main")
    ours = commit_with(repo, tmp_path,
                       file_content="line1\nOURS changed line2\nline3\n",
                       message="ours")

    result = merge(repo, "feature")
    assert result["status"] == "conflict"
    assert len(result["conflicts"]) > 0
    # HEAD must not have advanced to a new merge commit
    assert repo.head_commit() == ours

    # Conflict markers must be in the file
    content = (tmp_path / "main.py").read_text()
    assert "<<<<<<< ours" in content
    assert ">>>>>>> theirs" in content


def test_conflict_with_force_creates_two_parent_commit(tmp_path):
    """With --force, a 2-parent merge commit is created despite conflicts."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    theirs = commit_with(repo, tmp_path,
                         file_content="line1\nTHEIRS\nline3\n",
                         message="theirs")

    repo.checkout("main")
    ours = commit_with(repo, tmp_path,
                       file_content="line1\nOURS\nline3\n",
                       message="ours")

    result = merge(repo, "feature", force=True)
    assert result["status"] == "merged"
    assert len(result["conflicts"]) > 0

    new_oid = repo.head_commit()
    assert new_oid != ours
    new_commit = repo.objects.read_obj(new_oid)
    assert len(new_commit["parents"]) == 2
    assert new_commit["parents"][0] == ours
    assert new_commit["parents"][1] == theirs


# ------------------------------------------------------------------ fallback trace

def test_fallback_trace_contains_mechanical_marker(tmp_path):
    """Fallback trace (no --reconcile) contains KNOWLEDGE RECONCILIATION marker."""
    repo = setup_repo(tmp_path, file_content="shared\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="shared\nfeature\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="shared\nmain\n", message="ours")

    result = merge(repo, "feature", force=True)
    assert result["status"] == "merged"

    new_commit = repo.objects.read_obj(repo.head_commit())
    assert new_commit.get("trace") is not None
    trace_obj = repo.objects.read_obj(new_commit["trace"])
    messages = trace_obj["messages"]
    assert len(messages) > 0
    combined = " ".join(m.get("content", "") for m in messages)
    assert "KNOWLEDGE RECONCILIATION" in combined


# ------------------------------------------------------------------ --reconcile CMD

def test_reconcile_cmd_used_for_merge_trace(tmp_path):
    """--reconcile with a stub echo CMD is used for the merge trace."""
    repo = setup_repo(tmp_path, file_content="shared\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="shared\nfeature\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="shared\nmain\n", message="ours")

    # Stub reconcile command: reads stdin JSON, prints fixed response
    stub_cmd = (
        f"{sys.executable} -c \""
        "import sys, json; "
        "data = json.load(sys.stdin); "
        "print(json.dumps({'goal': 'RECONCILED GOAL', "
        "'trace': [{'role': 'system', 'content': 'reconciled'}], "
        "'notes': 'test'}))\""
    )

    result = merge(repo, "feature", reconcile=stub_cmd, force=True)
    assert result["status"] == "merged"
    assert result["goal"] == "RECONCILED GOAL"

    new_commit = repo.objects.read_obj(repo.head_commit())
    trace_obj = repo.objects.read_obj(new_commit["trace"])
    messages = trace_obj["messages"]
    assert any(m.get("content") == "reconciled" for m in messages)


# ------------------------------------------------------------------ up_to_date / fast-forward

def test_up_to_date(tmp_path):
    """Merging a branch that is already an ancestor → up_to_date."""
    repo = setup_repo(tmp_path)
    commit_with(repo, tmp_path, message="base")
    repo.branch("feature")
    # feature points to same commit as main
    result = merge(repo, "feature")
    assert result["status"] == "up_to_date"


def test_fast_forward(tmp_path):
    """Merging a branch that is ahead of ours → fast-forward."""
    repo = setup_repo(tmp_path)
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    ff_oid = commit_with(repo, tmp_path, file_content="advanced\n", message="ff")

    repo.checkout("main")
    result = merge(repo, "feature")
    assert result["status"] == "fast_forward"
    assert repo.head_commit() == ff_oid


# ------------------------------------------------------------------ freeze guard

# ------------------------------------------------------------------ PR2: target-goal

def test_target_goal_directs_merge(tmp_path):
    """--target-goal overrides the unioned goal even on the mechanical path."""
    repo = setup_repo(tmp_path, file_content="shared\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, goal="cut inference cost",
                file_content="shared\nfeature\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, goal="maximize accuracy",
                file_content="shared\nmain\n", message="ours")

    result = merge(repo, "feature", target_goal="maximize retention", force=True)
    assert result["status"] == "merged"
    assert result["goal"] == "maximize retention"

    commit = repo.objects.read_obj(repo.head_commit())
    goal_obj = repo.objects.read_obj(commit["goal"])
    assert goal_obj["text"] == "maximize retention"
    assert commit["metrics"]["target_goal"] == "maximize retention"


# ------------------------------------------------------------------ PR1: AI code synthesis

def test_reconcile_resolves_conflict_files(tmp_path):
    """A reconciler returning resolved_files turns a conflict into a clean merge."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="line1\nTHEIRS\nline3\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="line1\nOURS\nline3\n", message="ours")

    # Stub reconciler: rewrites main.py into a clean, marker-free file.
    stub_cmd = (
        f"{sys.executable} -c \""
        "import sys, json; data = json.load(sys.stdin); "
        "print(json.dumps({'goal': 'merged', "
        "'trace': [{'role': 'system', 'content': 'ok'}], "
        "'resolved_files': {'main.py': 'line1\\nMERGED\\nline3\\n'}, "
        "'notes': 'ai-resolved'}))\""
    )

    # no --force: the only conflict is AI-resolved, so the merge must complete.
    result = merge(repo, "feature", reconcile=stub_cmd)
    assert result["status"] == "merged"
    assert result["conflicts"] == []
    assert "main.py" in result["ai_resolved"]

    content = (tmp_path / "main.py").read_text()
    assert "MERGED" in content
    assert "<<<<<<<" not in content


def test_conflict_files_in_bundle(tmp_path):
    """The reconciler receives full base/ours/theirs text for each content conflict."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="line1\nTHEIRS\nline3\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="line1\nOURS\nline3\n", message="ours")

    # Reconciler that asserts conflict_files carries all three sides, then resolves.
    probe = (
        f"{sys.executable} -c \""
        "import sys, json; d = json.load(sys.stdin); "
        "cf = d['conflict_files']; "
        "assert any(c['path']=='main.py' and 'OURS' in c['ours'] "
        "and 'THEIRS' in c['theirs'] and 'line2' in c['base'] for c in cf); "
        "print(json.dumps({'goal':'g','trace':[{'role':'system','content':'x'}], "
        "'resolved_files':{'main.py':'clean\\n'}}))\""
    )
    result = merge(repo, "feature", reconcile=probe)
    assert result["status"] == "merged"
    assert (tmp_path / "main.py").read_text() == "clean\n"


# ------------------------------------------------------------------ PR3: metric-weighted

def test_metric_autoselect_breaks_conflict(tmp_path):
    """A clear eval winner pre-resolves a content conflict with no --force, no LLM."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    theirs = commit_with(repo, tmp_path,
                         file_content="line1\nTHEIRS\nline3\n", message="theirs")

    repo.checkout("main")
    ours = commit_with(repo, tmp_path,
                       file_content="line1\nOURS\nline3\n", message="ours")

    # ours passed its eval, theirs failed → ours wins the file outright.
    repo.write_eval(ours, {"commit": ours, "score": 0.95, "ok": True})
    repo.write_eval(theirs, {"commit": theirs, "score": 0.30, "ok": False})

    result = merge(repo, "feature")  # no force, no reconcile
    assert result["status"] == "merged"
    assert result["conflicts"] == []
    assert any(a["winner"] == "ours" and a["path"] == "main.py"
               for a in result["autoselected"])

    content = (tmp_path / "main.py").read_text()
    assert "OURS" in content and "THEIRS" not in content
    assert "<<<<<<<" not in content

    commit = repo.objects.read_obj(repo.head_commit())
    assert commit["metrics"]["ours_eval"] == 0.95
    assert commit["metrics"]["theirs_eval"] == 0.30


def test_metric_autoselect_is_per_hunk(tmp_path):
    """A metric winner resolves only the *overlapping* hunk — each side's
    non-conflicting hunks survive (per-hunk, not whole-file)."""
    # separator lines (l2, l4) keep the three change regions distinct.
    repo = setup_repo(tmp_path, file_content="l1\nl2\nl3\nl4\nl5\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    # theirs: change l3 (overlaps) AND l5 (theirs-only)
    theirs = commit_with(repo, tmp_path,
                         file_content="l1\nl2\nTHEIRS_L3\nl4\nTHEIRS_L5\n",
                         message="theirs")

    repo.checkout("main")
    # ours: change l1 (ours-only) AND l3 (overlaps)
    ours = commit_with(repo, tmp_path,
                       file_content="OURS_L1\nl2\nOURS_L3\nl4\nl5\n",
                       message="ours")

    repo.write_eval(ours, {"commit": ours, "score": 0.95, "ok": True})
    repo.write_eval(theirs, {"commit": theirs, "score": 0.30, "ok": False})

    result = merge(repo, "feature")
    assert result["status"] == "merged"
    assert result["conflicts"] == []

    content = (tmp_path / "main.py").read_text()
    assert "OURS_L1" in content      # ours-only hunk survives
    assert "THEIRS_L5" in content    # theirs-only hunk survives
    assert "OURS_L3" in content      # overlap resolved to the eval winner (ours)
    assert "THEIRS_L3" not in content
    assert "<<<<<<<" not in content


def test_metric_tie_leaves_conflict(tmp_path):
    """Eval scores within the threshold do NOT auto-resolve — conflict stands."""
    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    theirs = commit_with(repo, tmp_path,
                         file_content="line1\nTHEIRS\nline3\n", message="theirs")

    repo.checkout("main")
    ours = commit_with(repo, tmp_path,
                       file_content="line1\nOURS\nline3\n", message="ours")

    repo.write_eval(ours, {"commit": ours, "score": 0.80, "ok": True})
    repo.write_eval(theirs, {"commit": theirs, "score": 0.78, "ok": True})

    result = merge(repo, "feature")  # Δ=0.02 < 0.2 threshold
    assert result["status"] == "conflict"
    assert result["autoselected"] == []
    assert "<<<<<<<" in (tmp_path / "main.py").read_text()


def test_freeze_blocked_with_conflict_markers(tmp_path):
    """freeze must be blocked while conflict markers exist in the tree."""
    from agentvcs.crystallize import crystallize

    repo = setup_repo(tmp_path, file_content="line1\nline2\nline3\n")
    commit_with(repo, tmp_path, message="base")

    repo.branch("feature")
    repo.checkout("feature")
    commit_with(repo, tmp_path, file_content="line1\nTHEIRS\nline3\n", message="theirs")

    repo.checkout("main")
    commit_with(repo, tmp_path, file_content="line1\nOURS\nline3\n", message="ours")

    result = merge(repo, "feature")
    assert result["status"] == "conflict"

    # Now try to freeze — should raise because conflict markers exist
    with pytest.raises(RepoError) as exc_info:
        crystallize(repo)
    assert "conflict" in str(exc_info.value).lower() or exc_info.value.code in (
        "CONFLICT_MARKERS", "UNRESOLVED_CONFLICTS", "ERROR")
