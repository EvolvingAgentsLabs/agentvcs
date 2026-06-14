"""agentvcs — version control for software that is cultivated, not written.

A multidimensional VCS for evolving agent fleets: every commit captures code,
goal, model pins and the inter-agent message trace together, and any commit can
be crystallized from a fluid (probabilistic) state into a frozen, deterministic
recipe.
"""
from .repository import Repository, RepoError, Snapshot
from .crystallize import crystallize
from .diff import diff_commits
from .replay import replay
from .recall import recall
from .runtime import build_frame
from .eval import run_eval

__version__ = "0.3.0"
__all__ = ["Repository", "RepoError", "Snapshot", "crystallize", "diff_commits",
           "replay", "recall", "build_frame", "run_eval"]
