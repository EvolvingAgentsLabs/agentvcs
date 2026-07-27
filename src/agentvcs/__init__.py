"""agentvcs — version control for software that is cultivated, not written.

A multidimensional VCS for evolving agent fleets: every commit captures code,
goal, model pins and the inter-agent message trace together, and any commit can
be crystallized from a fluid (probabilistic) state into a frozen, deterministic
recipe.
"""
from .repository import Repository, RepoError, Snapshot
from .crystallize import crystallize
from .diff import diff_commits
from .merge import merge
from .replay import replay
from .recall import recall
from .runtime import build_frame
from .eval import run_eval
from .sbt import issue_sbt, read_sbts, verify_sbt, skill_profile
from .plural import select_fleet, correlation
from .soul import verify_commit
from .dynamics import price, slowing, ratchet, health, infobits, contain

__version__ = "0.4.0"
__all__ = ["Repository", "RepoError", "Snapshot", "crystallize", "diff_commits",
           "merge", "replay", "recall", "build_frame", "run_eval",
           "issue_sbt", "read_sbts", "verify_sbt", "skill_profile",
           "select_fleet", "correlation", "verify_commit",
           "price", "slowing", "ratchet", "health", "infobits", "contain"]
