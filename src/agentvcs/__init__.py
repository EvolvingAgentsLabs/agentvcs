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

__version__ = "0.2.0"
__all__ = ["Repository", "RepoError", "Snapshot", "crystallize", "diff_commits", "replay"]
