"""
Regression tests for the depth-gated COUNT(*) in the API list path (GH #1976 PR).

`get_queryset` used to run `qset.count()` on every list request and then only
use the result when `depth > 0` — a wasted COUNT(*) on the depth=0 path that
sync clients hit constantly. The count is now only issued when a depth-based
truncation decision actually needs it.
"""

from contextlib import ExitStack

import pytest
from django.db import connections
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from peeringdb_server.models import Organization


@pytest.fixture
def orgs(db):
    return [
        Organization.objects.create(name=f"Count Query Org {i}", status="ok")
        for i in range(3)
    ]


def _org_count_queries(client, path, params=None):
    # reads may be routed to the replica alias, so capture on every connection
    with ExitStack() as stack:
        captures = [
            stack.enter_context(CaptureQueriesContext(connections[alias]))
            for alias in connections
        ]
        response = client.get(path, params)
    assert response.status_code == 200
    return [
        q["sql"]
        for captured in captures
        for q in captured.captured_queries
        if "COUNT(" in q["sql"].upper() and "peeringdb_organization" in q["sql"]
    ]


@pytest.mark.django_db
def test_depth_zero_list_skips_count(orgs):
    assert _org_count_queries(APIClient(), "/api/org", {"depth": 0}) == []


@pytest.mark.django_db
def test_depth_list_still_counts_for_truncation(orgs):
    # the guard must not drop the count where the truncation decision needs it.
    # A filter is required: an unfiltered depth>0 list is served from the api
    # cache (CacheRedirect) and never reaches the count at all.
    params = {"depth": 1, "name__startswith": "Count Query"}
    # more than one count can legitimately occur (other layers count the
    # filtered set too); the invariant is that the truncation count still runs
    assert len(_org_count_queries(APIClient(), "/api/org", params)) >= 1
