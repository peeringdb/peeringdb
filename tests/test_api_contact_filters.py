"""
Contact detail filters on /api/poc and through /api/net poc_set (#492, #493).

A blocked filter is ignored: it returns the same list as no filter at all,
whatever value is sent. The other poc filters keep working on both paths.
The net__poc_set relation route on /api/fac and /api/ix is pinned as well.
"""

import pytest
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
)
from peeringdb_server.serializers import (
    NetworkContactSerializer,
    NetworkSerializer,
    OrganizationSerializer,
)

pytestmark = pytest.mark.django_db

BLOCKED_FIELDS = ("name", "phone", "email", "url")

# filter key forms, formatted with the field name as sent and upper-cased
KEY_FORMS = (
    "{field}",
    "{field}__contains",
    "{field}__startswith",
    "{field}__in",
    "{field}__iexact",
    "{field}__gt",
    "{field}_id",
    "{FIELD}",
)

CALLERS = ("guest", "authenticated", "member")


@pytest.fixture
def contact_data(db, settings):
    settings.API_CACHE_ENABLED = False
    guest_group = Group.objects.create(name="guest")
    user_group = Group.objects.create(name="user")
    settings.GUEST_GROUP_ID = guest_group.pk
    settings.USER_GROUP_ID = user_group.pk
    for group in (guest_group, user_group):
        GroupPermission.objects.create(
            group=group, namespace="peeringdb.organization", permission=0x01
        )
    GroupPermission.objects.create(
        group=guest_group,
        namespace="peeringdb.organization.*.network.*.poc_set.public",
        permission=0x01,
    )
    GroupPermission.objects.create(
        group=user_group,
        namespace="peeringdb.organization.*.network.*.poc_set.users",
        permission=0x01,
    )

    org = Organization.objects.create(name="Contact filter org", status="ok")
    other_org = Organization.objects.create(
        name="Other contact filter org", status="ok"
    )
    net = Network.objects.create(
        name="Contact filter net", asn=63321, org=org, status="ok"
    )
    other_net = Network.objects.create(
        name="Other contact filter net", asn=63322, org=other_org, status="ok"
    )

    facs = {}
    ixs = {}
    for key, network, ipaddr4, ipaddr6 in (
        ("net", net, "195.69.147.21", "2001:7f8:1::a506:3321:1"),
        ("other_net", other_net, "195.69.147.22", "2001:7f8:1::a506:3322:1"),
    ):
        facs[key] = Facility.objects.create(
            name=f"{network.name} fac",
            org=network.org,
            status="ok",
            city="City",
            country="US",
        )
        NetworkFacility.objects.create(network=network, facility=facs[key], status="ok")
        ixs[key] = InternetExchange.objects.create(
            name=f"{network.name} IX", org=network.org, status="ok"
        )
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixs[key].ixlan,
            asn=network.asn,
            speed=1000,
            ipaddr4=ipaddr4,
            ipaddr6=ipaddr6,
            status="ok",
        )

    user = User.objects.create(username="contact-filter-user")
    user.groups.add(user_group)
    member = User.objects.create(username="contact-filter-member")
    member.groups.add(user_group)
    org.usergroup.user_set.add(member)

    def poc(network, visible, role, slug, phone, status="ok"):
        return NetworkContact.objects.create(
            network=network,
            visible=visible,
            role=role,
            status=status,
            name=f"Contact {slug}",
            phone=phone,
            email=f"{slug}@example.invalid",
            url=f"https://example.invalid/{slug}",
        )

    pocs = {
        "public": poc(net, "Public", "Technical", "public", "+12065550101"),
        "users": poc(net, "Users", "NOC", "users", "+12065550102"),
        "private": poc(net, "Private", "Policy", "private", "+12065550103"),
        "deleted": poc(
            net, "Public", "Abuse", "deleted", "+12065550104", status="deleted"
        ),
        "other": poc(other_net, "Public", "Sales", "other", "+12065550105"),
    }

    return {
        "net": net,
        "other_net": other_net,
        "fac": facs,
        "ix": ixs,
        "user": user,
        "member": member,
        "pocs": pocs,
    }


def api_client(data, caller):
    client = APIClient()
    if caller != "guest":
        client.force_authenticate(
            user=data["user"] if caller == "authenticated" else data["member"]
        )
    return client


def result_ids(client, path, params=None):
    resp = client.get(path, params or {})
    assert resp.status_code == 200, resp.content
    return sorted(row["id"] for row in resp.json()["data"])


def filter_key(form, field):
    return form.format(field=field, FIELD=field.upper())


def test_contact_fields_not_filterable():
    poc_fields = dict(NetworkContactSerializer.filterable_fields())
    net_fields = dict(NetworkSerializer.filterable_fields())
    for field in BLOCKED_FIELDS:
        assert field not in poc_fields
        assert f"poc_set__{field}" not in net_fields

    # the block is scoped to the contact model's fields
    assert "role" in poc_fields
    assert "visible" in poc_fields
    assert "poc_set__role" in net_fields
    assert "poc_set__visible" in net_fields
    assert "name" in net_fields
    assert "name" in dict(OrganizationSerializer.filterable_fields())


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("field", BLOCKED_FIELDS)
@pytest.mark.parametrize("form", KEY_FORMS)
def test_poc_contact_filter_ignored(contact_data, caller, field, form):
    client = api_client(contact_data, caller)
    unfiltered = result_ids(client, "/api/poc")
    assert unfiltered

    key = filter_key(form, field)
    values = [getattr(poc, field) for poc in contact_data["pocs"].values()]
    for value in values + ["no-such-contact"]:
        filtered = result_ids(client, "/api/poc", {key: value})
        assert filtered == unfiltered, (key, value)


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("field", BLOCKED_FIELDS)
@pytest.mark.parametrize("form", KEY_FORMS)
def test_net_poc_set_contact_filter_ignored(contact_data, caller, field, form):
    client = api_client(contact_data, caller)
    unfiltered = result_ids(client, "/api/net")
    assert len(unfiltered) == 2

    key = f"poc_set__{filter_key(form, field)}"
    values = [getattr(poc, field) for poc in contact_data["pocs"].values()]
    for value in values + ["no-such-contact"]:
        filtered = result_ids(client, "/api/net", {key: value})
        assert filtered == unfiltered, (key, value)


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("endpoint", ("fac", "ix"))
@pytest.mark.parametrize("field", BLOCKED_FIELDS)
def test_relation_route_never_compares_contact_fields(
    contact_data, caller, endpoint, field
):
    """
    get_relation_filters() cuts net__poc_set__<field> back to net__poc_set,
    which is a contact id condition. The contact field is never compared:
    the response is the one for net__poc_set with the same value, and does
    not depend on which contact the value belongs to.
    """
    client = api_client(contact_data, caller)
    pocs = contact_data["pocs"]
    path = f"/api/{endpoint}"

    def outcome(params):
        resp = client.get(path, params)
        if resp.status_code != 200:
            return resp.status_code, None
        return resp.status_code, sorted(row["id"] for row in resp.json()["data"])

    # the route is live: a contact id narrows to the contact's network
    assert outcome({"net__poc_set": pocs["public"].id}) == (
        200,
        [contact_data[endpoint]["net"].id],
    )

    key = f"net__poc_set__{field}"
    other_value = getattr(pocs["other"], field)
    for poc in pocs.values():
        value = getattr(poc, field)
        sent = outcome({key: value})
        assert sent == outcome({"net__poc_set": value}), (key, value)
        assert sent == outcome({key: other_value}), (key, value)


@pytest.mark.parametrize("caller", CALLERS)
def test_poc_other_filters_still_work(contact_data, caller):
    client = api_client(contact_data, caller)
    pocs = contact_data["pocs"]
    visible = set(result_ids(client, "/api/poc"))

    expected_visible = {pocs["public"].id, pocs["other"].id}
    if caller != "guest":
        expected_visible.add(pocs["users"].id)
    if caller == "member":
        expected_visible.add(pocs["private"].id)
    assert visible == expected_visible

    def expect(*keys):
        return sorted(pocs[key].id for key in keys if pocs[key].id in visible)

    assert result_ids(client, "/api/poc", {"role": "Technical"}) == expect("public")
    assert result_ids(client, "/api/poc", {"role": "NOC"}) == expect("users")
    assert result_ids(client, "/api/poc", {"role__in": "Policy,Sales"}) == expect(
        "private", "other"
    )
    assert result_ids(client, "/api/poc", {"visible": "Public"}) == expect(
        "public", "other"
    )
    assert result_ids(
        client, "/api/poc", {"net_id": contact_data["other_net"].id}
    ) == expect("other")
    assert result_ids(client, "/api/poc", {"id": pocs["public"].id}) == expect("public")


@pytest.mark.parametrize("caller", CALLERS)
def test_net_poc_set_other_filters_still_work(contact_data, caller):
    client = api_client(contact_data, caller)
    net = contact_data["net"].id
    other_net = contact_data["other_net"].id

    assert result_ids(client, "/api/net", {"poc_set__role": "Sales"}) == [other_net]
    assert result_ids(client, "/api/net", {"poc_set__role": "Technical"}) == [net]
    assert result_ids(client, "/api/net", {"poc_set__visible": "Private"}) == [net]
    assert result_ids(
        client, "/api/net", {"poc_set__id": contact_data["pocs"]["other"].id}
    ) == [other_net]
