"""
Line breaks, tabs and other control characters are refused in the
single-line entity name fields (`name`, `aka`, `name_long`) on the API, the
/cp forms and the affiliation form (#533).
"""

import pytest
import reversion
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django_grainy.models import GroupPermission
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.test import APIClient

from peeringdb_server.admin import CarrierAdminForm, NetworkAdminForm
from peeringdb_server.forms import AffiliateToOrgForm
from peeringdb_server.models import Carrier, Network, Organization, User
from peeringdb_server.serializers import (
    CampusSerializer,
    CarrierSerializer,
    FacilitySerializer,
    InternetExchangeSerializer,
    NetworkSerializer,
    OrganizationSerializer,
)
from peeringdb_server.validators import (
    replace_control_chars,
    validate_no_control_chars,
)

pytestmark = pytest.mark.django_db

CONTROL_VALUES = [
    "Acme\nCorp",
    "Acme\r\nCorp Two",
    "Acme\rCorp",
    "Acme\tCorp",
    "Acme\x00Corp",
    "Acme\x1bCorp",
    "Acme\x7fCorp",
    "Acme\x85Corp",
    "Acme\x98Corp",
    "Acme\u2028Corp",
    "Acme\u2029Corp",
]


@pytest.mark.parametrize("value", CONTROL_VALUES)
def test_validate_no_control_chars_rejects(value):
    with pytest.raises(ValidationError):
        validate_no_control_chars(value)


@pytest.mark.parametrize(
    "value", [None, "", "Acme Corp", "Acme Corp (Europe)", "Ünïcödé Ltd", "株式会社"]
)
def test_validate_no_control_chars_allows(value):
    assert validate_no_control_chars(value) == value


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", ""),
        ("Acme Corp", "Acme Corp"),
        ("Acme\nCorp", "Acme Corp"),
        ("Acme\r\nCorp", "Acme  Corp"),
        ("Acme\x98", "Acme "),
        ("Acme\u2028Corp", "Acme Corp"),
        ("Acme\u2029Corp", "Acme Corp"),
    ],
)
def test_replace_control_chars(value, expected):
    assert replace_control_chars(value) == expected


@pytest.mark.parametrize(
    "serializer_class",
    [
        OrganizationSerializer,
        NetworkSerializer,
        InternetExchangeSerializer,
        FacilitySerializer,
        CarrierSerializer,
        CampusSerializer,
    ],
)
@pytest.mark.parametrize("field", ["name", "aka", "name_long"])
def test_serializer_rejects_control_chars(serializer_class, field):
    fields = serializer_class().fields
    if field not in fields:
        pytest.skip(f"{serializer_class.__name__} has no {field}")
    serializer_field = fields[field]
    assert serializer_field.run_validation("Acme Corp") == "Acme Corp"
    with pytest.raises(RestValidationError):
        serializer_field.run_validation("Acme\nCorp")


@pytest.mark.parametrize("value", CONTROL_VALUES)
def test_network_admin_form_rejects_control_chars(value):
    form_class = modelform_factory(
        Network, form=NetworkAdminForm, fields=["name", "aka", "name_long"]
    )
    form = form_class()
    form.cleaned_data = {"name": "Acme Corp", "aka": value, "name_long": value}
    form.clean()
    assert "aka" in form.errors
    assert "name_long" in form.errors
    assert "name" not in form.errors


def test_carrier_admin_form_rejects_control_chars():
    form_class = modelform_factory(Carrier, form=CarrierAdminForm, fields=["name"])
    form = form_class()
    form.cleaned_data = {"name": "Acme\r\nCorp"}
    form.clean()
    assert "name" in form.errors


@pytest.mark.parametrize("value", ["Acme\nCorp", "Acme\r\nCorp", "Acme\tCorp"])
def test_affiliate_to_org_form_rejects_control_chars(value):
    form = AffiliateToOrgForm(data={"org": value})
    assert not form.is_valid()
    assert "org" in form.errors


@pytest.fixture
def carrier_data(settings):
    settings.API_CACHE_ENABLED = False
    settings.RATELIMIT_ENABLE = False
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )

    with reversion.create_revision():
        org = Organization.objects.create(name="Control org", status="ok")
        carrier = Carrier.objects.create(
            name="Control carrier",
            org=org,
            status="ok",
            website="https://carrier.example",
        )

    user = User.objects.create(username="control-admin")
    user.groups.add(user_group)
    user.set_verified()
    org.admin_usergroup.user_set.add(user)

    client = APIClient()
    client.force_authenticate(user=user)
    return {"carrier": carrier, "client": client}


def put_carrier(data, **changes):
    client = data["client"]
    carrier = data["carrier"]
    payload = client.get(f"/api/carrier/{carrier.id}").json()["data"][0]
    payload.pop("_grainy", None)
    payload.update(changes)
    return client.put(f"/api/carrier/{carrier.id}", payload, format="json")


def test_api_carrier_plain_name_accepted(carrier_data):
    resp = put_carrier(carrier_data, aka="Control aka")
    assert resp.status_code == 200, resp.content


@pytest.mark.parametrize("field", ["name", "aka", "name_long"])
@pytest.mark.parametrize(
    "value",
    ["Control\nsecond", "Control\r\nsecond", "C\x98", "C\u2028x", "C\u2029x"],
)
def test_api_carrier_control_chars_refused(carrier_data, field, value):
    resp = put_carrier(carrier_data, **{field: value})

    assert resp.status_code == 400, resp.content
    assert set(resp.json()) - {"meta"} == {field}
    carrier = carrier_data["carrier"]
    carrier.refresh_from_db()
    assert getattr(carrier, field) != value
