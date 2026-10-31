"""What a scan searches for, and where: built from the profile's files alone."""

from __future__ import annotations

import pytest

from helpers import example
import scan_config
from scan_config import (NATIONWIDE, cluster_terms, metro_keys, plan_queries,
                         remote_mode, search_locations)

FILTERS = {"metros": {"a": {"search_as": "Austin, TX"},
                      "b": {"search_as": ["Dallas, TX", "Fort Worth, TX"]},
                      "c": {}},
           "remote": {"mode": "include"}}


def test_remote_modes():
    assert remote_mode(FILTERS) == "include"
    assert remote_mode(FILTERS, "only") == "only"
    with pytest.raises(SystemExit):
        remote_mode(FILTERS, "sometimes")


def test_search_locations_follow_the_remote_mode():
    assert search_locations(FILTERS) == {"a": ["Austin, TX"],
                                         "b": ["Dallas, TX", "Fort Worth, TX"]}
    assert search_locations(FILTERS, mode="only") == {NATIONWIDE: [NATIONWIDE]}
    wide = dict(FILTERS, remote={"mode": "include", "search_nationwide": True})
    assert NATIONWIDE in search_locations(wide)
    assert scan_config.unsearchable_metros(FILTERS) == ["c"]


def test_an_unknown_metro_stops_the_run():
    assert metro_keys(FILTERS, only={"a"}) == ["a"]
    with pytest.raises(SystemExit, match="unknown metro"):
        metro_keys(FILTERS, only={"z"})


def test_shared_terms_are_queried_once():
    clusters = {"clusters": [{"id": "x", "search_terms": ["nurse educator", "rn"]},
                             {"id": "y", "search_terms": ["rn"]}]}
    plan = plan_queries({"x", "y"}, cluster_terms(clusters), {"a": ["Austin, TX"]})
    assert sorted(t for t, _, _ in plan) == ["nurse educator", "rn"]


@pytest.mark.parametrize("name, adzuna, usajobs", [
    ("nurse-sacramento", 11, 1),            # 11 terms, one metro; "nurse" for USAJOBS
    ("product-marketer-chicago", 16, 0),    # 8 terms, Chicago plus nationwide remote
])
def test_example_request_plans(name, adzuna, usajobs):
    filters = scan_config.load_yaml(example(name, "filters.yaml"))
    clusters = scan_config.load_yaml(example(name, "clusters.yaml"))
    ids = {c["id"] for c in clusters["clusters"]}
    places = search_locations(filters)
    assert len(plan_queries(ids, cluster_terms(clusters), places)) == adzuna
    federal = plan_queries(ids, cluster_terms(clusters, "usajobs_terms"), places)
    assert len(federal) == usajobs
