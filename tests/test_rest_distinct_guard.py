"""
Unit tests for `_filters_may_produce_duplicates` — the helper that decides
whether `.distinct()` is required on a REST list queryset.

These tests pin the structural guarantee that any filter traversing a reverse
FK or M2M relation triggers `.distinct()`, while own-field / forward-FK chains
do not. A regression in `queryable_relations()` (or anywhere else that widens
the filter surface) that exposed a duplicating path without this guard would
silently re-introduce duplicate driver rows in API responses.
"""

import pytest

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.rest import _filters_may_produce_duplicates

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "model,filters",
    [
        # own-field filters
        (Network, {"name__iexact": "20c"}),
        (Network, {"asn": 63311}),
        (NetworkIXLan, {"ipaddr4": "192.0.2.1"}),
        (Facility, {"city__icontains": "amsterdam"}),
        # forward FK -> own field (the production `?net__name=20c` shape)
        (NetworkIXLan, {"network__name__iexact": "20c"}),
        (NetworkIXLan, {"ixlan__name__icontains": "Foo"}),
        (Network, {"org__name__iexact": "20c"}),
        # forward FK id
        (NetworkIXLan, {"network_id": 1}),
        (Network, {"org_id": 1}),
        # lookup suffix only
        (Network, {"updated__lte": "2026-01-01"}),
        (Network, {"id__in": [1, 2, 3]}),
        # unknown segment that isn't a relation (treated as lookup, walk stops)
        (Network, {"nonexistent_field": "x"}),
    ],
)
def test_no_distinct_for_non_duplicating_filters(model, filters):
    assert _filters_may_produce_duplicates(model, filters) is False


@pytest.mark.parametrize(
    "model,filters",
    [
        # reverse FK (one_to_many) on the driving model
        (Organization, {"net_set": 1}),
        (Organization, {"fac_set__name__icontains": "ams"}),
        (Network, {"netixlan_set__ipaddr4": "192.0.2.1"}),
        (InternetExchange, {"ixlan_set__name": "foo"}),
        # reverse FK reached through a forward FK
        (NetworkIXLan, {"network__netfac_set__facility_id": 5}),
    ],
)
def test_distinct_for_reverse_fk_filters(model, filters):
    assert _filters_may_produce_duplicates(model, filters) is True


def test_distinct_for_m2m_filter():
    """The Sponsorship.orgs M2M is the only forward M2M in the schema today.

    It is not exposed via the REST API, but the helper must still flag it as
    duplicate-producing if a future filter ever traverses an M2M — that is the
    whole reason the guard exists.
    """
    from peeringdb_server.models import Sponsorship

    assert _filters_may_produce_duplicates(Sponsorship, {"orgs__name": "20c"}) is True


def test_mixed_filters_flag_when_any_duplicates():
    # one duplicating filter is enough to require distinct()
    filters = {
        "name__iexact": "20c",  # own field, would skip
        "fac_set__name__icontains": "ams",  # reverse FK, requires distinct
    }
    assert _filters_may_produce_duplicates(Organization, filters) is True


def test_empty_filters():
    assert _filters_may_produce_duplicates(Network, {}) is False
