import ipaddress
import os
from unittest.mock import patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, override_settings
from rest_framework.exceptions import ValidationError as RestValidationError

import peeringdb_server.geo as geo
from peeringdb_server.context import current_request
from peeringdb_server.models import (
    Facility,
    InternetExchange,
    IXLan,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    ProtectedAction,
)
from peeringdb_server.validators import (
    validate_address_space,
    validate_asn_prefix,
    validate_distance_geocode,
    validate_info_prefixes4,
    validate_info_prefixes6,
    validate_irr_as_set,
    validate_latitude,
    validate_longitude,
    validate_phonenumber,
    validate_prefix_overlap,
    validate_social_media,
    validate_website_override,
)
from tests.test_ixf_member_import_protocol import setup_test_data

pytestmark = pytest.mark.django_db

INVALID_ADDRESS_SPACES = [
    "0.0.0.0/1",
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    # FIXME: this fails still
    #'172.0.0.0/11',
    "172.16.0.0/12",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    # FIXME: this fails still
    #'224.0.0.0/3',
    "224.0.0.0/4",
    "240.0.0.0/4",
    "100.64.0.0/10",
    "0000::/8",
    "0064:ff9b::/96",
    "0100::/8",
    "0200::/7",
    "0400::/6",
    "0800::/5",
    "1000::/4",
    "2001::/33",
    "2001:0:8000::/33",
    "2001:0002::/48",
    "2001:0003::/32",
    "2001:10::/28",
    "2001:20::/28",
    "2001:db8::/32",
    "2002::/16",
    "3ffe::/16",
    "4000::/2",
    "4000::/3",
    "5f00::/8",
    "6000::/3",
    "8000::/3",
    "a000::/3",
    "c000::/3",
    "e000::/4",
    "f000::/5",
    "f800::/6",
    "fc00::/7",
    "fe80::/10",
    "fec0::/10",
    "ff00::/8",
]


@pytest.fixture(params=INVALID_ADDRESS_SPACES)
def prefix(request):
    return request.param


# @pytest.mark.django_db
def test_validate_address_space(prefix):
    """
    Tests peeringdb_server.validators.validate_address_space
    """
    with pytest.raises(ValidationError) as exc:
        validate_address_space(ipaddress.ip_network(str(prefix)))


@override_settings(DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000)
def test_validate_info_prefixes4():
    """
    Tests peeringdb_server.validators.validate_info_prefixes4
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes4(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes4(-1)
    validate_info_prefixes4(500000)
    assert validate_info_prefixes4(None) == 0
    assert validate_info_prefixes4("") == 0


@override_settings(DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000)
def test_validate_info_prefixes6():
    """
    Tests peeringdb_server.validators.validate_info_prefixes6
    """
    with pytest.raises(ValidationError):
        validate_info_prefixes6(500001)
    with pytest.raises(ValidationError):
        validate_info_prefixes6(-1)
    validate_info_prefixes6(500000)
    assert validate_info_prefixes6(None) == 0
    assert validate_info_prefixes6("") == 0


@override_settings(
    DATA_QUALITY_MIN_PREFIXLEN_V4=24,
    DATA_QUALITY_MAX_PREFIXLEN_V4=24,
    DATA_QUALITY_MIN_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_PREFIXLEN_V6=48,
)
def test_validate_prefixlen():
    """
    Tests prefix length limits
    """
    with pytest.raises(ValidationError):
        validate_address_space("37.77.32.0/20")
    with pytest.raises(ValidationError):
        validate_address_space("131.72.77.240/28")
    with pytest.raises(ValidationError):
        validate_address_space("2403:c240::/32")
    with pytest.raises(ValidationError):
        validate_address_space("2001:504:0:2::/64")


@pytest.mark.django_db
def test_validate_prefix_overlap():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Text exchange", status="ok", org=org)
    ixlan = ix.ixlan

    pfx1 = IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("198.32.125.0/24"),
        status="ok",
    )

    with pytest.raises(ValidationError) as exc:
        validate_prefix_overlap("198.32.124.0/23")


@pytest.mark.parametrize(
    "value,validated",
    [
        # success validation
        ("RIPE::AS-FOO", "RIPE::AS-FOO"),
        ("AS-FOO@RIPE", "AS-FOO@RIPE"),
        ("AS-FOO-BAR@RIPE", "AS-FOO-BAR@RIPE"),
        ("ripe::as-foo", "RIPE::AS-FOO"),
        ("as-foo@ripe", "AS-FOO@RIPE"),
        ("as-foo@ripe as-bar@ripe", "AS-FOO@RIPE AS-BAR@RIPE"),
        ("as-foo@ripe,as-bar@ripe", "AS-FOO@RIPE AS-BAR@RIPE"),
        ("as-foo@ripe, as-bar@ripe", "AS-FOO@RIPE AS-BAR@RIPE"),
        (
            "RIPE::AS12345:AS-FOO RIPE::AS12345:AS-FOO:AS9876",
            "RIPE::AS12345:AS-FOO RIPE::AS12345:AS-FOO:AS9876",
        ),
        ("ripe::as-foo:as123:as345", "RIPE::AS-FOO:AS123:AS345"),
        ("RIPE::AS12345", "RIPE::AS12345"),
        ("AS12345@RIPE", "AS12345@RIPE"),
        ("RIPE::AS123456:RS-FOO", "RIPE::AS123456:RS-FOO"),
        ("as-foo", "AS-FOO"),
        ("rs-foo", "RS-FOO"),
        ("as-foo as-bar", "AS-FOO AS-BAR"),
        ("rs-foo as-bar", "RS-FOO AS-BAR"),
        ("rs-foo rs-bar", "RS-FOO RS-BAR"),
        ("AS15562", "AS15562"),
        ("AS-15562", "AS-15562"),
        ("AS15562 AS33333", "AS15562 AS33333"),
        # hyphenated source validation
        # we currently do not have valid hyphentated sources in the IRR_SOURCE
        # so this test is commented out
        # ("AS-20C@ARIN-NONAUTH", "AS-20C@ARIN-NONAUTH"),
        # ("ARIN-NONAUTH::AS-20C", "ARIN-NONAUTH::AS-20C"),
        # fail validation
        ("UNKNOWN::AS-FOO", False),
        ("AS-FOO@UNKNOWN", False),
        ("ASFOO@UNKNOWN", False),
        ("UNKNOWN::ASFOO", False),
        ("RIPE:AS-FOO", False),
        ("RIPE::RS15562:RS-FOO", False),
        ("RIPE::AS123456:RS-FOO:AS-FOO", False),
        ('!"*([])?.=+/\\', False),
        ('RIPE::!"*([])?.=+/\\', False),
        ('!"*([])?.=+/\\@RIPE', False),
        # > DATA_QUALITY_MAX_IRR_DEPTH
        ("ripe::as-foo:as123:as345:as678", False),
    ],
)
def test_validate_irr_as_set(value, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_irr_as_set(value)
    else:
        assert validate_irr_as_set(value) == validated


@pytest.mark.django_db
def test_validate_phonenumber():
    # test standalone validator

    validate_phonenumber("+1 206 555 0199")
    validate_phonenumber("012065550199", "US")

    with pytest.raises(ValidationError):
        validate_phonenumber("invalid number")

    with pytest.raises(ValidationError):
        validate_phonenumber("012065550199")

    # test model field validation

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange",
        status="ok",
        org=org,
        country="US",
        city="Some city",
        region_continent="North America",
        media="Ethernet",
    )
    net = Network.objects.create(name="Text network", asn=12345, status="ok", org=org)
    poc = NetworkContact.objects.create(network=net, status="ok", role="Abuse")

    # test poc phone validation

    with pytest.raises(ValidationError):
        poc.phone = "invalid"
        poc.full_clean()

    poc.phone = "+1 206 555 0199"
    poc.full_clean()

    # test ix phone validation

    with pytest.raises(ValidationError):
        ix.tech_phone = "invalid"
        ix.full_clean()

    ix.tech_phone = "+1 206 555 0199"
    ix.full_clean()

    with pytest.raises(ValidationError):
        ix.policy_phone = "invalid"
        ix.full_clean()

    ix.policy_phone = "+1 206 555 0199"
    ix.full_clean()


@pytest.mark.django_db
def test_validate_ixpfx_ixlan_status_match():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange", status="pending", org=org
    )
    ixlan = ix.ixlan

    pfx = IXLanPrefix.objects.create(
        ixlan=ixlan,
        protocol="IPv4",
        prefix=ipaddress.ip_network("198.32.125.0/24"),
        status="ok",
    )

    with pytest.raises(ValidationError) as exc1:
        pfx.clean()

    assert (
        exc1.value.args[0]
        == "IXLanPrefix with status 'ok' cannot be linked to a IXLan with status 'pending'."
    )

    ixlan.status = "deleted"
    ixlan.save()
    pfx.status = "pending"
    pfx.save()

    with pytest.raises(ValidationError) as exc2:
        pfx.clean()

    assert (
        exc2.value.args[0]
        == "IXLanPrefix with status 'pending' cannot be linked to a IXLan with status 'deleted'."
    )


@pytest.mark.django_db
@override_settings(
    DATA_QUALITY_MAX_PREFIX_V4_LIMIT=500000,
    DATA_QUALITY_MAX_PREFIX_V6_LIMIT=500000,
    DATA_QUALITY_MIN_PREFIXLEN_V4=24,
    DATA_QUALITY_MAX_PREFIXLEN_V4=24,
    DATA_QUALITY_MIN_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_PREFIXLEN_V6=48,
    DATA_QUALITY_MAX_IRR_DEPTH=3,
    DATA_QUALITY_MIN_SPEED=10,
    DATA_QUALITY_MAX_SPEED=100,
)
def test_bypass_validation():
    User = get_user_model()

    superuser = User.objects.create_user(
        username="superuser",
        password="superuser",
        email="su@localhost",
        is_superuser=True,
    )
    user = User.objects.create_user(
        username="user", password="user", email="user@localhost"
    )

    factory = RequestFactory()

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(
        name="Text exchange",
        status="ok",
        org=org,
        country="US",
        city="Some city",
        region_continent="North America",
        media="Ethernet",
    )
    net = Network.objects.create(name="Text network", asn=12345, status="ok", org=org)

    # super user should bypass validation

    request = factory.get("/")
    request.user = superuser
    with current_request(request):
        validate_address_space("37.77.32.0/20")
        validate_address_space("131.72.77.240/28")
        validate_address_space("2403:c240::/32")
        validate_address_space("2001:504:0:2::/64")
        validate_info_prefixes4(500001)
        validate_info_prefixes6(500001)
        NetworkIXLan(speed=1, network=net, ixlan=ix.ixlan).clean()
        NetworkIXLan(speed=1000, network=net, ixlan=ix.ixlan).clean()
        validate_irr_as_set("ripe::as-foo:as123:as345:as678")

    # user should NOT bypass validation

    request = factory.get("/")
    request.user = user
    with current_request(request):
        with pytest.raises(ValidationError):
            validate_address_space("37.77.32.0/20")
        with pytest.raises(ValidationError):
            validate_address_space("131.72.77.240/28")
        with pytest.raises(ValidationError):
            validate_address_space("2403:c240::/32")
        with pytest.raises(ValidationError):
            validate_address_space("2001:504:0:2::/64")
        with pytest.raises(ValidationError):
            validate_info_prefixes4(500001)
        with pytest.raises(ValidationError):
            validate_info_prefixes6(500001)
        with pytest.raises(ValidationError):
            NetworkIXLan(speed=1, network=net, ixlan=ix.ixlan).clean()
        with pytest.raises(ValidationError):
            NetworkIXLan(speed=1000, network=net, ixlan=ix.ixlan).clean()
        with pytest.raises(ValidationError):
            validate_irr_as_set("ripe::as-foo:as123:as345:as678")


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_one_netixlan():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on the same netixlan.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F cache

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it claimed both ip4 and ip6, the ghost
    # peer is now deleted

    ghost_peer.refresh_from_db()

    assert ghost_peer.status == "deleted"


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_two_netixlan():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on separate netixlans.

    In this test both conflicting netixlans will have neither ipv4 nor ipv6 set in the end
    and will be deleted
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer_a = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=None,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    ghost_peer_b = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=None,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F data

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it claimed both ip4 and ip6, the ghost
    # peer is now deleted

    ghost_peer_a.refresh_from_db()
    ghost_peer_b.refresh_from_db()

    assert ghost_peer_a.status == "deleted"
    assert ghost_peer_b.status == "deleted"


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_two_netixlan_partial():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    In this test both ipv4 and ipv6 exist on separate netixlans.

    In this test the conflicting netixlans will have the other ip address still set and will not be deleted.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer_a = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6="2001:7f8:1::a500:2906:2",
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    ghost_peer_b = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4="195.69.147.251",
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )

    # setup IX-F data

    data = setup_test_data("ixf.member.1")
    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", data)

    ix = ixlan.ix

    # real peer should exist in IX-F data

    real4, real6 = ix.peer_exists_in_ixf_data(1001, IP4, IP6)
    assert real4
    assert real6

    # ghost peer should NOT exist in IX-F data

    ghost4, ghost6 = ix.peer_exists_in_ixf_data(1010, IP4, IP6)
    assert not ghost4
    assert not ghost6

    # create and save a real peer that has the same ip addresses
    # as the ghost peer

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    real_peer.full_clean()
    real_peer.save()

    # real peer has been saved and since it only claimed one ip address
    # from either ghost peer, both ghost peers remain

    ghost_peer_a.refresh_from_db()
    ghost_peer_b.refresh_from_db()

    assert ghost_peer_a.status == "ok"
    assert ghost_peer_a.ipaddr4 is None
    assert ghost_peer_a.ipaddr6 is not None

    assert ghost_peer_b.status == "ok"
    assert ghost_peer_b.ipaddr4 is not None
    assert ghost_peer_b.ipaddr6 is None


@pytest.mark.django_db
def test_ghost_peer_vs_real_peer_invalid_ixf_data():
    """
    Tests that a real peer can claim the ip addresses of a gohst peer. #983

    Test the handling of invalid IX-F data, in which case the ghost peer vs real peer
    logic should be skipped.
    """

    # set up entities

    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test ix", status="ok", org=org)
    network = Network.objects.create(asn=1001, name="AS1001", status="ok", org=org)
    network_other = Network.objects.create(
        asn=1010, name="AS1010", status="ok", org=org
    )
    ixlan = ix.ixlan
    ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
    ixlan.save()

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="195.69.144.0/22",
        protocol="IPv4",
    )

    IXLanPrefix.objects.create(
        ixlan=ixlan,
        status="ok",
        prefix="2001:7f8:1::/64",
        protocol="IPv6",
    )

    IP4 = "195.69.147.250"
    IP6 = "2001:7f8:1::a500:2906:1"

    ghost_peer = NetworkIXLan.objects.create(
        network=network_other,
        ixlan=ixlan,
        asn=network_other.asn,
        speed=20000,
        ipaddr4=IP4,
        ipaddr6=IP6,
        status="ok",
        is_rs_peer=False,
        operational=False,
    )
    # setup IX-F data

    cache.set(f"IXF-CACHE-{ix.ixlan.ixf_ixp_member_list_url}", {"invalid": "data"})

    ix = ixlan.ix

    real_peer = NetworkIXLan(
        network=network,
        status="ok",
        ipaddr4=IP4,
        ipaddr6=IP6,
        ixlan=ixlan,
        speed=1000,
        asn=network.asn,
    )

    # run full validation (this will run `validate_real_vs_ghost_peer`)

    with pytest.raises(Exception) as excinfo:
        real_peer.full_clean()
    assert "IP already exists" in str(excinfo.value)


@pytest.mark.parametrize(
    "value,validated",
    [
        # success validation
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "x", "identifier": "unknown12"},
            ],
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "x", "identifier": "unknown12"},
            ],
        ),
        (
            [
                {"service": "instagram", "identifier": "john__doe_"},
                {"service": "tiktok", "identifier": "unknown_12"},
            ],
            [
                {"service": "instagram", "identifier": "john__doe_"},
                {"service": "tiktok", "identifier": "unknown_12"},
            ],
        ),
        (
            [
                {"service": "instagram", "identifier": "john-doe-"},
                {"service": "tiktok", "identifier": "-unknown-12"},
            ],
            [
                {"service": "instagram", "identifier": "john-doe-"},
                {"service": "tiktok", "identifier": "-unknown-12"},
            ],
        ),
        # fail validation
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "x", "identifier": "unknown11."},
            ],
            False,
        ),
        ([{"service": "instagram", "identifier": "john__doe_*"}], False),
        (
            [
                {"service": "website", "identifier": ""},
                {"service": "x", "identifier": "unknown"},
            ],
            False,
        ),
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "", "identifier": "unknown"},
            ],
            False,
        ),
        (
            [
                {"service": "website", "identifier": None},
                {"service": "", "identifier": "unknown"},
            ],
            False,
        ),
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": None, "identifier": "unknown"},
            ],
            False,
        ),
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"service": "website", "identifier": "https://www.unknown.com"},
            ],
            False,
        ),
        (
            [
                {"service": "website", "identifier": "https://www.example.com"},
                {"foo": "bar"},
            ],
            False,
        ),
        (
            {
                "service": {
                    "service": "website",
                    "identifier": "https://www.example.com",
                },
            },
            False,
        ),
        (
            [
                {"service": "x", "identifier": "aaa"},
            ],
            False,
        ),
        (
            [
                {"service": "x", "identifier": "a" * 16},
            ],
            False,
        ),
        (
            [
                {"service": "x", "identifier": "$bla/"},
            ],
            False,
        ),
    ],
)
@pytest.mark.django_db
def test_validate_social_media(value, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_social_media(value)
    else:
        assert validate_social_media(value) == validated


@pytest.mark.parametrize(
    "website,org_website,validated",
    [
        # success validation website not null
        (
            "https://www.example.com",
            "https://www.example1.com",
            "https://www.example.com",
        ),
        # success validation website null and overrided by organization website
        (None, "https://www.example1.com", "https://www.example1.com"),
        # fail validation
        (
            None,
            None,
            False,
        ),
    ],
)
@pytest.mark.django_db
def test_validate_website_override(website, org_website, validated):
    if not validated:
        with pytest.raises(ValidationError):
            validate_website_override(website, org_website)
    else:
        assert validate_website_override(website, org_website) == validated


@pytest.mark.django_db
def test_org_create_with_none_social_media():
    org = Organization.objects.create(name="Test org", status="ok", social_media=None)
    assert org.social_media == {}


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        ("63311", True, "63311"),
        ("as63311", True, "63311"),
        ("asn63311", True, "63311"),
        ("AS63311", True, "63311"),
        ("ASN63311", True, "63311"),
        # fail validation
        ("AN63311", False, None),
        ("6as3311", False, None),
        ("63311asn", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_asn_prefix(value, is_valid, validated):
    print(is_valid)
    if not is_valid:
        with pytest.raises(RestValidationError):
            validate_asn_prefix(value)
    else:
        assert validate_asn_prefix(value) == validated


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        (37.7749, True, 37.7749),
        (-23.5505, True, -23.5505),
        (51.5074, True, 51.5074),
        (40.7128, True, 40.7128),
        ("-33.8688", True, -33.8688),
        # fail validation
        (95.1234, False, None),
        (-120.5678, False, None),
        ("-122.5678", False, None),
        ("abcdef", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_latitude(value, is_valid, validated):
    if not is_valid:
        with pytest.raises(ValidationError):
            validate_latitude(value)
    else:
        assert validate_latitude(value) == validated


@pytest.mark.parametrize(
    "value,is_valid,validated",
    [
        # success validation
        (-122.4194, True, -122.4194),
        (-46.6333, True, -46.6333),
        (-0.1270, True, -0.1270),
        (-74.0060, True, -74.0060),
        ("151.2093", True, 151.2093),
        # fail validation
        (190.1234, False, None),
        (-250.5678, False, None),
        ("360.9876", False, None),
        ("abcdef", False, None),
    ],
)
@pytest.mark.django_db
def test_validate_longitude(value, is_valid, validated):
    if not is_valid:
        with pytest.raises(ValidationError):
            validate_longitude(value)
    else:
        assert validate_longitude(value) == validated


def geo_mock_init(self, key, timeout):
    pass


def geo_gmaps_mock_geocode_freeform(location):
    return {"lat": 40.712776, "lng": -74.005974}


@pytest.mark.parametrize(
    "current_geocode,new_geocode,current_city,new_city,is_valid,validated",
    [
        # test success with exists geocode (max 1km from previous geocode)
        (
            (50.951533, 1.852570),
            (50.951533, 1.851440),
            "london",
            "london",
            True,
            (50.951533, 1.851440),
        ),
        (
            (40.712776, -74.005974),
            (40.712790, -74.003974),
            "new york",
            "new york",
            True,
            (40.712790, -74.003974),
        ),
        # # test fail with exists geocode (max 1km from previous geocode)
        (
            (40.712776, -74.005974),
            (40.712790, -73.003974),
            "new york",
            "new york",
            False,
            None,
        ),
        ((50.951533, 1.852570), (51.951533, 0.851440), "london", "london", False, None),
        # test success with not exists geocode (max 50km from city)
        (
            (None, None),
            (40.712771, -74.005970),
            "new york",
            "new york",
            True,
            (40.712771, -74.005970),
        ),
        (
            (None, None),
            (40.716822, -73.991032),
            "new york",
            "new york",
            True,
            (40.716822, -73.991032),
        ),
        # test fail with not exists geocode (max 50km from city)
        ((None, None), (36.169941, -115.139832), "new york", "new york", False, None),
        ((None, None), (36.201902, -115.328808), "new york", "new york", False, None),
    ],
)
@patch.object(geo.GoogleMaps, "__init__", geo_mock_init)
@patch.object(geo.Melissa, "__init__", geo_mock_init)
@pytest.mark.django_db
def test_validate_distance_geocode(
    current_geocode, new_geocode, current_city, new_city, is_valid, validated, settings
):
    settings.MELISSA_KEY = ""
    settings.GOOGLE_GEOLOC_API_KEY = ""
    with patch.object(
        geo.GoogleMaps, "geocode_freeform", side_effect=geo_gmaps_mock_geocode_freeform
    ):
        if not is_valid:
            with pytest.raises(ValidationError):
                validate_distance_geocode(
                    current_geocode, new_geocode, current_city, new_city
                )
        else:
            assert (
                validate_distance_geocode(
                    current_geocode, new_geocode, current_city, new_city
                )
                == validated
            )


def test_validate_status_change():
    org = Organization.objects.create(name="Test org", status="ok")
    ix = InternetExchange.objects.create(name="Test exchange", status="ok", org=org)
    ix.status = "pending"
    with pytest.raises(ValidationError):
        ix.clean()
        ix.save()

    fac = Facility.objects.create(name="Test facility", status="ok", org=org)
    fac.status = "pending"
    with pytest.raises(ValidationError):
        fac.clean()
        fac.save()

    net = Network.objects.create(name="Test network", status="ok", org=org, asn=101)
    net.status = "pending"
    with pytest.raises(ValidationError):
        net.clean()
        net.save()
