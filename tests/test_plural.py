"""Tests for Plural Intelligence: correlation discounting and diverse-fleet
selection (DeSoc §4.5/§5.2 applied to agent swarms)."""
import pytest

from agentvcs.plural import correlation, competence, select_fleet, fleet_diversity


def test_correlation_identical_and_disjoint():
    a = {"react": 5, "css": 3}
    assert correlation(a, dict(a)) == pytest.approx(1.0)        # clones
    assert correlation(a, {"security": 4}) == pytest.approx(0.0)  # disjoint
    assert correlation(a, {}) == 0.0                            # empty


def test_competence_is_total_weight():
    assert competence({"a": 2, "b": 3}) == 5.0


def _pool():
    return [
        {"soul": "react1", "profile": {"react": 5, "frontend": 4, "css": 3}},
        {"soul": "react2", "profile": {"react": 5, "frontend": 4, "css": 3}},  # clone
        {"soul": "react3", "profile": {"react": 4, "frontend": 5, "css": 2}},  # near-clone
        {"soul": "sec1", "profile": {"security": 5, "audit": 4, "crypto": 3}},
        {"soul": "back1", "profile": {"backend": 5, "sql": 4, "api": 3}},
    ]


def test_discounting_prefers_diversity_over_clones():
    # DeSoc default: correlation discounting picks complementary souls
    diverse = select_fleet(_pool(), 3, discount=1.0)
    chosen = {m["soul"] for m in diverse["fleet"]}
    # the three picks should span the three distinct specialties, not stack react
    assert "sec1" in chosen and "back1" in chosen
    assert not ({"react1", "react2"} <= chosen)         # never both clones
    assert diverse["diversity"] == pytest.approx(1.0)


def test_no_discount_is_willing_to_take_clones():
    naive = select_fleet(_pool(), 3, discount=0.0)
    # without discounting, the two identical react souls (top competence) come along
    assert naive["diversity"] < 1.0


def test_fleet_diversity_bounds():
    clones = [{"soul": "x", "profile": {"a": 1}}, {"soul": "y", "profile": {"a": 1}}]
    assert fleet_diversity(clones) == pytest.approx(0.0)
    complementary = [{"soul": "x", "profile": {"a": 1}}, {"soul": "y", "profile": {"b": 1}}]
    assert fleet_diversity(complementary) == pytest.approx(1.0)


def test_select_fleet_edges():
    assert select_fleet([], 3)["fleet"] == []
    one = select_fleet([{"soul": "s", "profile": {"a": 1}}], 5)
    assert len(one["fleet"]) == 1                        # can't exceed the pool
    assert select_fleet(_pool(), 0)["fleet"] == []
