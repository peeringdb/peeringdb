"""
The facility sides of a netixlan on the generic API routes (#524).

The set-net-side and set-ix-side endpoints decide who may set which side:
the network sets its own side to a facility it is present at, the exchange
sets its side to a facility it is present at. PUT and POST on
/api/netixlan apply the same rules to changed sides; values sent back
unchanged are not re-checked.
"""

import pytest
import reversion
from django.contrib.auth.models import Group
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
)

pytestmark = pytest.mark.django_db


def make_facility(name, org):
    return Facility.objects.create(
        name=name,
        org=org,
        status="ok",
        city="Chicago",
        country="US",
        latitude=41.88,
        longitude=-87.63,
    )


@pytest.fixture
def sides_data(settings):
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
        net_org = Organization.objects.create(
            name="Sides net org", status="ok", website="https://net.example"
        )
        ix_org = Organization.objects.create(name="Sides ix org", status="ok")
        fac_org = Organization.objects.create(name="Sides fac org", status="ok")
        other_ix_org = Organization.objects.create(
            name="Sides other ix org", status="ok"
        )
        net = Network.objects.create(
            name="Sides net", asn=63461, org=net_org, status="ok"
        )
        other_net = Network.objects.create(
            name="Sides other net", asn=63462, org=net_org, status="ok"
        )
        for each in (net, other_net):
            NetworkContact.objects.create(
                network=each,
                role="Technical",
                visible="Public",
                status="ok",
                name="Sides NOC",
                email="noc@sides.example",
            )
        ix = InternetExchange.objects.create(name="Sides IX", org=ix_org, status="ok")
        IXLanPrefix.objects.create(
            ixlan=ix.ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
        other_ix = InternetExchange.objects.create(
            name="Sides other IX", org=other_ix_org, status="ok"
        )
        IXLanPrefix.objects.create(
            ixlan=other_ix.ixlan,
            status="ok",
            prefix="195.69.152.0/22",
            protocol="IPv4",
        )
        fac_ix = make_facility("Sides exchange facility", ix_org)
        InternetExchangeFacility.objects.create(ix=ix, facility=fac_ix, status="ok")
        fac_net = make_facility("Sides network facility", fac_org)
        NetworkFacility.objects.create(network=net, facility=fac_net, status="ok")
        fac_other = make_facility("Sides unrelated facility", fac_org)
        netixlan = NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=net.asn,
            speed=1000,
            ipaddr4="195.69.147.31",
            status="ok",
        )

    users = {}
    for name, orgs in (
        ("netadmin", (net_org,)),
        ("ixadmin", (ix_org,)),
        ("bothadmin", (net_org, ix_org)),
    ):
        user = User.objects.create(username=f"sides-{name}")
        user.groups.add(user_group)
        user.set_verified()
        for org in orgs:
            org.admin_usergroup.user_set.add(user)
        users[name] = user

    return {
        "net": net,
        "other_net": other_net,
        "ix": ix,
        "other_ix": other_ix,
        "fac_ix": fac_ix,
        "fac_net": fac_net,
        "fac_other": fac_other,
        "netixlan": netixlan,
        "users": users,
    }


def client_for(data, name):
    client = APIClient()
    client.force_authenticate(user=data["users"][name])
    return client


def netixlan_data(client, netixlan):
    resp = client.get(f"/api/netixlan/{netixlan.id}")
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"][0]
    data.pop("_grainy", None)
    for field in ("ipaddr4", "ipaddr6"):
        if data.get(field) is None:
            data[field] = ""
    return data


def put(client, netixlan, **changes):
    data = netixlan_data(client, netixlan)
    data.update(changes)
    return client.put(f"/api/netixlan/{netixlan.id}", data, format="json")


def test_network_cannot_set_ix_side(sides_data):
    netixlan = sides_data["netixlan"]
    client = client_for(sides_data, "netadmin")

    # the exchange is present at this facility, but the side is the exchange's
    resp = put(client, netixlan, ix_side_id=sides_data["fac_ix"].id)

    assert resp.status_code == 400, resp.content
    assert "ix_side_id" in resp.json()
    netixlan.refresh_from_db()
    assert netixlan.ix_side_id is None


def test_network_cannot_clear_ix_side(sides_data):
    netixlan = sides_data["netixlan"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.save()
    client = client_for(sides_data, "netadmin")

    resp = put(client, netixlan, ix_side_id=None)

    assert resp.status_code == 400, resp.content
    netixlan.refresh_from_db()
    assert netixlan.ix_side_id == sides_data["fac_ix"].id


def test_network_side_must_be_a_network_facility(sides_data):
    netixlan = sides_data["netixlan"]
    client = client_for(sides_data, "netadmin")

    resp = put(client, netixlan, net_side_id=sides_data["fac_other"].id)

    assert resp.status_code == 400, resp.content
    assert "net_side_id" in resp.json()
    netixlan.refresh_from_db()
    assert netixlan.net_side_id is None


def test_network_sets_own_side(sides_data):
    netixlan = sides_data["netixlan"]
    client = client_for(sides_data, "netadmin")

    resp = put(client, netixlan, net_side_id=sides_data["fac_net"].id)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.net_side_id == sides_data["fac_net"].id

    resp = put(client, netixlan, net_side_id=None)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.net_side_id is None


def test_unchanged_sides_are_not_rechecked(sides_data):
    # stored sides may not satisfy the rules (set before them, or by the
    # IX-F importer); echoing them back must keep working
    netixlan = sides_data["netixlan"]
    netixlan.net_side = sides_data["fac_other"]
    netixlan.ix_side = sides_data["fac_other"]
    netixlan.save()
    client = client_for(sides_data, "netadmin")

    resp = put(client, netixlan, speed=2000)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.speed == 2000
    assert netixlan.net_side_id == sides_data["fac_other"].id
    assert netixlan.ix_side_id == sides_data["fac_other"].id


def test_exchange_and_network_admin_sets_ix_side(sides_data):
    netixlan = sides_data["netixlan"]
    client = client_for(sides_data, "bothadmin")

    resp = put(client, netixlan, ix_side_id=sides_data["fac_other"].id)

    assert resp.status_code == 400, resp.content
    assert "ix_side_id" in resp.json()

    resp = put(client, netixlan, ix_side_id=sides_data["fac_ix"].id)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.ix_side_id == sides_data["fac_ix"].id


def test_create_with_ix_side_refused(sides_data):
    client = client_for(sides_data, "netadmin")

    resp = client.post(
        "/api/netixlan",
        {
            "net_id": sides_data["net"].id,
            "ixlan_id": sides_data["ix"].ixlan.id,
            "speed": 1000,
            "ipaddr4": "195.69.147.32",
            "ipaddr6": "",
            "ix_side_id": sides_data["fac_ix"].id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert "ix_side_id" in resp.json()
    assert not NetworkIXLan.objects.filter(ipaddr4="195.69.147.32").exists()


@pytest.mark.parametrize(
    "caller,endpoint", (("ixadmin", "set-ix-side"), ("netadmin", "set-net-side"))
)
def test_side_endpoint_facility_not_present(sides_data, caller, endpoint):
    netixlan = sides_data["netixlan"]
    client = client_for(sides_data, caller)

    resp = client.post(
        f"/api/netixlan/{netixlan.id}/{endpoint}",
        {"fac_id": sides_data["fac_other"].id},
        format="json",
    )

    assert resp.status_code == 404, resp.content
    netixlan.refresh_from_db()
    assert netixlan.ix_side_id is None
    assert netixlan.net_side_id is None


def test_move_to_another_exchange_does_not_carry_ix_side(sides_data):
    netixlan = sides_data["netixlan"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.save()
    client = client_for(sides_data, "netadmin")
    move = {"ixlan_id": sides_data["other_ix"].ixlan.id, "ipaddr4": "195.69.152.10"}

    resp = put(client, netixlan, **move)

    assert resp.status_code == 400, resp.content
    assert "ix_side_id" in resp.json()
    netixlan.refresh_from_db()
    assert netixlan.ixlan_id == sides_data["ix"].ixlan.id

    resp = put(client, netixlan, ix_side_id=None, **move)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.ixlan_id == sides_data["other_ix"].ixlan.id
    assert netixlan.ix_side_id is None


def test_move_to_another_network_rechecks_net_side(sides_data):
    netixlan = sides_data["netixlan"]
    netixlan.net_side = sides_data["fac_net"]
    netixlan.save()
    client = client_for(sides_data, "netadmin")
    other_net = sides_data["other_net"]

    resp = put(client, netixlan, net_id=other_net.id)

    assert resp.status_code == 400, resp.content
    assert "net_side_id" in resp.json()
    netixlan.refresh_from_db()
    assert netixlan.network_id == sides_data["net"].id

    resp = put(client, netixlan, net_id=other_net.id, net_side_id=None)

    assert resp.status_code == 200, resp.content
    netixlan.refresh_from_db()
    assert netixlan.network_id == other_net.id
    assert netixlan.net_side_id is None


@pytest.mark.parametrize("facility,expected", (("fac_net", 201), ("fac_other", 400)))
def test_create_with_net_side(sides_data, facility, expected):
    client = client_for(sides_data, "netadmin")

    resp = client.post(
        "/api/netixlan",
        {
            "net_id": sides_data["net"].id,
            "ixlan_id": sides_data["ix"].ixlan.id,
            "speed": 1000,
            "ipaddr4": "195.69.147.33",
            "ipaddr6": "",
            "net_side_id": sides_data[facility].id,
        },
        format="json",
    )

    assert resp.status_code == expected, resp.content
    created = NetworkIXLan.objects.filter(ipaddr4="195.69.147.33").first()
    if expected == 201:
        assert created.net_side_id == sides_data[facility].id
    else:
        assert created is None


def reclaim(client, net_id, deleted, ixlan_id=None):
    return client.post(
        "/api/netixlan",
        {
            "net_id": net_id,
            "ixlan_id": ixlan_id or deleted.ixlan_id,
            "speed": 1000,
            "ipaddr4": str(deleted.ipaddr4),
            "ipaddr6": "",
        },
        format="json",
    )


def test_reclaim_by_another_network_drops_old_sides(sides_data):
    # the exchange reassigned a departed member's address, the old sides
    # described that member's port
    netixlan = sides_data["netixlan"]
    netixlan.net_side = sides_data["fac_net"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.status = "deleted"
    netixlan.save()
    other_net = sides_data["other_net"]

    resp = reclaim(client_for(sides_data, "netadmin"), other_net.id, netixlan)

    assert resp.status_code == 201, resp.content
    netixlan.refresh_from_db()
    assert netixlan.network_id == other_net.id
    assert netixlan.status == "ok"
    assert netixlan.net_side_id is None
    assert netixlan.ix_side_id is None


def test_reclaim_by_same_network_keeps_sides(sides_data):
    netixlan = sides_data["netixlan"]
    netixlan.net_side = sides_data["fac_net"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.status = "deleted"
    netixlan.save()

    resp = reclaim(client_for(sides_data, "netadmin"), sides_data["net"].id, netixlan)

    assert resp.status_code == 201, resp.content
    netixlan.refresh_from_db()
    assert netixlan.status == "ok"
    assert netixlan.net_side_id == sides_data["fac_net"].id
    assert netixlan.ix_side_id == sides_data["fac_ix"].id


def test_reclaim_on_another_exchange_drops_only_ix_side(sides_data):
    # the address now belongs to another exchange's LAN: the network side is
    # still the network's own, the exchange side was the old exchange's
    netixlan = sides_data["netixlan"]
    netixlan.ipaddr4 = "195.69.152.20"
    netixlan.net_side = sides_data["fac_net"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.status = "deleted"
    netixlan.save()
    other_ixlan = sides_data["other_ix"].ixlan

    resp = reclaim(
        client_for(sides_data, "netadmin"),
        sides_data["net"].id,
        netixlan,
        ixlan_id=other_ixlan.id,
    )

    assert resp.status_code == 201, resp.content
    netixlan.refresh_from_db()
    assert netixlan.status == "ok"
    assert netixlan.ixlan_id == other_ixlan.id
    assert netixlan.net_side_id == sides_data["fac_net"].id
    assert netixlan.ix_side_id is None


def test_reclaim_with_non_canonical_net_id_keeps_sides(sides_data):
    # the reset compares the resolved network, not the submitted string
    netixlan = sides_data["netixlan"]
    netixlan.net_side = sides_data["fac_net"]
    netixlan.ix_side = sides_data["fac_ix"]
    netixlan.status = "deleted"
    netixlan.save()

    resp = reclaim(
        client_for(sides_data, "netadmin"), f"00{sides_data['net'].id}", netixlan
    )

    assert resp.status_code == 201, resp.content
    netixlan.refresh_from_db()
    assert netixlan.status == "ok"
    assert netixlan.network_id == sides_data["net"].id
    assert netixlan.net_side_id == sides_data["fac_net"].id
    assert netixlan.ix_side_id == sides_data["fac_ix"].id


def test_deleted_connectors_are_not_presence(sides_data):
    netixlan = sides_data["netixlan"]
    fac_net, fac_ix = sides_data["fac_net"], sides_data["fac_ix"]
    NetworkFacility.objects.filter(facility=fac_net).update(status="deleted")
    InternetExchangeFacility.objects.filter(facility=fac_ix).update(status="deleted")

    resp = put(client_for(sides_data, "netadmin"), netixlan, net_side_id=fac_net.id)
    assert resp.status_code == 400, resp.content
    assert "net_side_id" in resp.json()

    resp = put(client_for(sides_data, "bothadmin"), netixlan, ix_side_id=fac_ix.id)
    assert resp.status_code == 400, resp.content
    assert "ix_side_id" in resp.json()

    for caller, endpoint, fac in (
        ("netadmin", "set-net-side", fac_net),
        ("ixadmin", "set-ix-side", fac_ix),
    ):
        resp = client_for(sides_data, caller).post(
            f"/api/netixlan/{netixlan.id}/{endpoint}",
            {"fac_id": fac.id},
            format="json",
        )
        assert resp.status_code == 404, resp.content

    netixlan.refresh_from_db()
    assert netixlan.net_side_id is None
    assert netixlan.ix_side_id is None
