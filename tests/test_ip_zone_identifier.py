"""
IP addresses and prefixes with a zone identifier (`<address>%<zone>`) are
refused on every write path for exchange connections and prefixes (#534).
"""

import ipaddress

import pytest
import reversion
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django_grainy.models import GroupPermission
from rest_framework.test import APIClient

from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    User,
)
from peeringdb_server.validators import validate_address_space, validate_ip_no_zone

pytestmark = pytest.mark.django_db

HELD_V6 = "2001:db8:534::11"


@pytest.mark.parametrize(
    "value",
    [
        "2001:db8::1%eth0",
        "2001:db8::1%1",
        ipaddress.IPv6Address("2001:db8::1%x"),
        ipaddress.IPv6Network("2001:db8::%x/64"),
        "2001:db8::%x/64",
    ],
)
def test_validate_ip_no_zone_rejects(value):
    with pytest.raises(ValidationError):
        validate_ip_no_zone(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2001:db8::1",
        "198.51.100.1",
        ipaddress.IPv6Address("2001:db8::1"),
        ipaddress.IPv4Address("198.51.100.1"),
        ipaddress.IPv6Network("2001:db8::/64"),
        ipaddress.IPv4Network("198.51.100.0/24"),
    ],
)
def test_validate_ip_no_zone_accepts(value):
    validate_ip_no_zone(value)


@pytest.fixture
def zone_data(settings):
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
        net_org = Organization.objects.create(name="Zone net org", status="ok")
        other_org = Organization.objects.create(name="Zone other org", status="ok")
        ix_org = Organization.objects.create(name="Zone ix org", status="ok")
        net = Network.objects.create(
            name="Zone net", asn=63534, org=net_org, status="ok"
        )
        other_net = Network.objects.create(
            name="Zone other net", asn=63535, org=other_org, status="ok"
        )
        for each in (net, other_net):
            NetworkContact.objects.create(
                network=each,
                role="Technical",
                visible="Public",
                status="ok",
                name="Zone NOC",
                email="noc@zone.example",
            )
        ix = InternetExchange.objects.create(name="Zone IX", org=ix_org, status="ok")
        IXLanPrefix.objects.create(
            ixlan=ix.ixlan, status="ok", prefix="198.51.100.0/24", protocol="IPv4"
        )
        IXLanPrefix.objects.create(
            ixlan=ix.ixlan, status="ok", prefix="2001:db8:534::/64", protocol="IPv6"
        )
        held = NetworkIXLan.objects.create(
            network=other_net,
            ixlan=ix.ixlan,
            asn=other_net.asn,
            speed=1000,
            ipaddr4="198.51.100.11",
            ipaddr6=HELD_V6,
            status="ok",
        )
        own = NetworkIXLan.objects.create(
            network=net,
            ixlan=ix.ixlan,
            asn=net.asn,
            speed=1000,
            ipaddr4="198.51.100.21",
            ipaddr6="2001:db8:534::21",
            status="ok",
        )

    users = {}
    for name, org in (("netadmin", net_org), ("ixadmin", ix_org)):
        user = User.objects.create(username=f"zone-{name}")
        user.groups.add(user_group)
        user.set_verified()
        org.admin_usergroup.user_set.add(user)
        users[name] = user

    return {"net": net, "ix": ix, "held": held, "own": own, "users": users}


def client_for(data, name):
    client = APIClient()
    client.force_authenticate(user=data["users"][name])
    return client


def create_netixlan(data, ipaddr4, ipaddr6):
    return client_for(data, "netadmin").post(
        "/api/netixlan",
        {
            "net_id": data["net"].id,
            "ixlan_id": data["ix"].ixlan.id,
            "asn": data["net"].asn,
            "speed": 1000,
            "ipaddr4": ipaddr4,
            "ipaddr6": ipaddr6,
        },
        format="json",
    )


def test_api_create_plain_address(zone_data):
    resp = create_netixlan(zone_data, "198.51.100.77", "2001:db8:534::77")
    assert resp.status_code == 201, resp.content


@pytest.mark.parametrize(
    "ipaddr6", ["2001:db8:534::77%534", "2001:db8:534::77%eth0 x", "2001:db8:534::77%0"]
)
def test_api_create_zone_refused(zone_data, ipaddr6):
    resp = create_netixlan(zone_data, "198.51.100.77", ipaddr6)

    assert resp.status_code == 400, resp.content
    assert set(resp.json()) - {"meta"} == {"ipaddr6"}
    assert not NetworkIXLan.objects.filter(ipaddr4="198.51.100.77").exists()


def test_api_create_held_address_with_zone_refused(zone_data):
    resp = create_netixlan(zone_data, "198.51.100.78", f"{HELD_V6}%1")

    assert resp.status_code == 400, resp.content
    assert set(resp.json()) - {"meta"} == {"ipaddr6"}
    assert (
        not NetworkIXLan.objects.filter(ipaddr6__startswith=HELD_V6)
        .exclude(id=zone_data["held"].id)
        .exists()
    )


def test_api_update_zone_refused(zone_data):
    own = zone_data["own"]
    client = client_for(zone_data, "netadmin")
    data = client.get(f"/api/netixlan/{own.id}").json()["data"][0]
    data.pop("_grainy", None)
    data["ipaddr6"] = f"{HELD_V6}%1"

    resp = client.put(f"/api/netixlan/{own.id}", data, format="json")

    assert resp.status_code == 400, resp.content
    assert set(resp.json()) - {"meta"} == {"ipaddr6"}
    own.refresh_from_db()
    assert str(own.ipaddr6) == "2001:db8:534::21"


def test_model_clean_zone_refused(zone_data):
    own = zone_data["own"]
    own.ipaddr6 = "2001:db8:534::21%x"

    with pytest.raises(ValidationError) as exc:
        own.full_clean()

    assert "ipaddr6" in exc.value.error_dict


def create_prefix(data, prefix):
    return client_for(data, "ixadmin").post(
        "/api/ixpfx",
        {"ixlan_id": data["ix"].ixlan.id, "protocol": "IPv6", "prefix": prefix},
        format="json",
    )


def test_api_prefix_plain_accepted(zone_data):
    resp = create_prefix(zone_data, "2001:7f8:535::/64")
    assert resp.status_code == 201, resp.content


def test_validate_address_space_accepts_plain():
    validate_address_space("2001:7f8:535::/64")


def test_api_prefix_zone_refused(zone_data):
    resp = create_prefix(zone_data, "2001:7f8:535::%x/64")

    assert resp.status_code == 400, resp.content
    assert set(resp.json()) - {"meta"} == {"prefix"}
    assert not IXLanPrefix.objects.filter(prefix__contains="%").exists()


def test_model_prefix_clean_zone_refused(zone_data):
    prefix = IXLanPrefix(
        ixlan=zone_data["ix"].ixlan,
        status="ok",
        protocol="IPv6",
        prefix="2001:7f8:535::%x/64",
    )

    with pytest.raises(ValidationError):
        prefix.clean()


def test_api_ix_create_prefix_zone_refused(zone_data):
    resp = client_for(zone_data, "ixadmin").post(
        "/api/ix",
        {
            "org_id": zone_data["ix"].org_id,
            "name": "Zone IX two",
            "city": "Chicago",
            "country": "US",
            "region_continent": "North America",
            "media": "Ethernet",
            "website": "https://zone-ix.example",
            "tech_email": "noc@zone-ix.example",
            "policy_email": "noc@zone-ix.example",
            "prefix": "2001:7f8:535::%x/64",
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    errors = resp.json()
    assert set(errors) - {"meta"} == {"prefix"}
    # the zone check runs once, not once per prefix validator
    assert len(errors["prefix"]) == 1
    assert not InternetExchange.objects.filter(name="Zone IX two").exists()
    assert not IXLanPrefix.objects.filter(prefix__contains="%").exists()
