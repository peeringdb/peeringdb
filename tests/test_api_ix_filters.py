import pytest
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import InternetExchange, Organization, User
from peeringdb_server.serializers import InternetExchangeSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def ix_filter_data(db, settings):
    settings.API_CACHE_ENABLED = False
    guest_group = Group.objects.create(name="guest")
    settings.GUEST_GROUP_ID = guest_group.pk
    GroupPermission.objects.create(
        group=guest_group, namespace="peeringdb.organization", permission=0x01
    )
    user = User.objects.create(
        username="import-request-fixture",
        email="import-request@example.invalid",
        password="fixture-hash-prefix-not-a-real-password",
    )
    org = Organization.objects.create(name="Filter fixture org", status="ok")
    other_org = Organization.objects.create(
        name="Other filter fixture org", status="ok"
    )
    requested = InternetExchange.objects.create(
        name="Requested fixture IX", org=org, status="ok", ixf_import_request_user=user
    )
    other = InternetExchange.objects.create(
        name="Other fixture IX", org=other_org, status="ok"
    )
    return requested, other, user


def test_ix_queryable_relations_exclude_import_request_user():
    fields = dict(InternetExchangeSerializer.queryable_relations())
    assert not any(name.startswith("ixf_import_request_user__") for name in fields)
    assert "org__name" in fields


@pytest.mark.parametrize(
    "field,value",
    [
        ("password", "fixture-hash-prefix-not-a-real-password"),
        ("password__startswith", "fixture-hash-prefix"),
        ("password__contains", "hash-prefix"),
        ("email", "import-request@example.invalid"),
        ("email__in", "import-request@example.invalid"),
        ("username", "import-request-fixture"),
        ("id", None),
        ("id__in", None),
    ],
)
def test_anonymous_ix_filters_ignore_import_request_user(ix_filter_data, field, value):
    requested, other, user = ix_filter_data
    client = APIClient()
    baseline = client.get("/api/ix")
    assert baseline.status_code == 200
    assert {row["id"] for row in baseline.json()["data"]} == {requested.pk, other.pk}
    parameter = f"ixf_import_request_user__{field}"
    for query_value in (str(user.pk) if value is None else value, "999999999"):
        response = client.get("/api/ix", {parameter: query_value})
        assert response.status_code == 200
        assert {row["id"] for row in response.json()["data"]} == {
            requested.pk,
            other.pk,
        }


@pytest.mark.parametrize("field", ["name", "name__startswith", "org__name", "org_id"])
def test_supported_ix_filters_still_apply(ix_filter_data, field):
    requested, _, _ = ix_filter_data
    values = {
        "name": requested.name,
        "name__startswith": "Requested",
        "org__name": requested.org.name,
        "org_id": requested.org_id,
    }
    for extra in ({}, {"ixf_import_request_user__email": "not-found@example.invalid"}):
        response = APIClient().get("/api/ix", {field: values[field], **extra})
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["data"]] == [requested.pk]
