"""Shared pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_soul_home(tmp_path_factory, monkeypatch):
    """Souls store their secret seed OUTSIDE the repo (under ~/.config by default).
    Point that store at a throwaway dir for every test so no test ever writes a real
    key into the developer's home, and tests stay hermetic."""
    monkeypatch.setenv("AGENTVCS_SOUL_HOME", str(tmp_path_factory.mktemp("soul-home")))
