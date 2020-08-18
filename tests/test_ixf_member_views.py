import json
import os
import re
from pprint import pprint
import reversion
import requests
import jsonschema
import time
import io
import datetime

from django.db import transaction
from django.core.cache import cache
from django.test import Client, TestCase, RequestFactory
from django.urls import reverse

import django_namespace_perms as nsp

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    IXLan,
    IXLanPrefix,
    InternetExchange,
    IXFMemberData,
    IXLanIXFMemberImportAttempt,
    IXLanIXFMemberImportLog,
    IXLanIXFMemberImportLogEntry,
    User,
    DeskProTicket,
)
from peeringdb_server import ixf

import pytest


@pytest.mark.django_db
def test_reset_ixf_proposals(admin_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    client = setup_client(admin_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id,))

    create_IXFMemberData(network, ixlan, ip_addresses, True)

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(dismissed=True).count() == 0


@pytest.mark.django_db
def test_dismiss_ixf_proposals(admin_user, entities, ip_addresses):
    IXF_ID = 3
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    create_IXFMemberData(network, ixlan, ip_addresses, False)

    client = setup_client(admin_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, IXF_ID))

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(pk=IXF_ID).first().dismissed == True


@pytest.mark.django_db
def test_reset_ixf_proposals_no_perm(regular_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    client = setup_client(regular_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id,))

    create_IXFMemberData(network, ixlan, ip_addresses, True)

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content


@pytest.mark.django_db
def test_dismiss_ixf_proposals_no_perm(regular_user, entities, ip_addresses):
    IXF_ID = 3
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    create_IXFMemberData(network, ixlan, ip_addresses, False)

    client = setup_client(regular_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, IXF_ID))

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content

@pytest.mark.django_db
def test_ix_order(admin_user, entities, ip_addresses, ip_addresses_other):

    """
    Test that multiple exchanges proposing changes appear
    sorted by exchange name
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]
    ixlan_b = entities["ixlan"][1]

    create_IXFMemberData(network, ixlan_a, ip_addresses, False)
    create_IXFMemberData(network, ixlan_b, ip_addresses_other, False)

    client = setup_client(admin_user)
    url = reverse("net-view", args=(network.id,))

    response = client.get(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200

    matches = re.findall('<a class="ix-name">([^<]+)</a>', content)
    assert matches == ['Test Exchange One', 'Test Exchange Two']



@pytest.mark.django_db
def test_check_ixf_proposals(admin_user, entities, ip_addresses):
    network = Network.objects.create(
        name="Network w allow ixp update disabled",
        org=entities["org"][0],
        asn=1001,
        allow_ixp_update=False,
        status="ok",
        info_prefixes4=42,
        info_prefixes6=42,
        website="http://netflix.com/",
        policy_general="Open",
        policy_url="https://www.netflix.com/openconnect/",
        info_unicast=False,
        info_ipv6=False
    )
    ixlan = entities["ixlan"][0]

    # We create one Netixlan that matches the ASN and ipaddr6 of the import.json
    # Therefore, the hint will suggest we modify this netixlan
    netixlan = NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=10000,
        ipaddr4="195.69.147.251",
        ipaddr6="2001:7f8:1::a500:2906:3",
        status="ok",
        is_rs_peer=True,
        operational=True,
    )

    with open(
        os.path.join(
            os.path.dirname(__file__), "data", "ixf", "views", "import.json",
        ),
    ) as fh:
        json_data = json.load(fh)

    importer = ixf.Importer()
    importer.update(ixlan, data=json_data)


    client = setup_client(admin_user)
    url = reverse("net-view", args=(network.id,))
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    # Suggest add
    assert 'data-field="ipaddr4" value="195.69.147.250"' in content
    assert 'data-field="ipaddr6" value="2001:7f8:1::a500:2906:1"' in content

    # Suggest modify
    assert 'data-field="ipaddr4" data-value=""' in content
    assert 'data-field="ipaddr6" data-value="2001:7f8:1::a500:2906:3"' in content


# Functions and fixtures


def setup_client(user):
    client = Client()
    client.force_login(user)
    return client


def create_IXFMemberData(network, ixlan, ip_addresses, dismissed):
    """
    Creates IXFMember data
    """
    for ip_address in ip_addresses:
        ixfmember = IXFMemberData.instantiate(network.asn, ip_address[0], ip_address[1], ixlan, data={"foo":"bar"})
        ixfmember.save()
        ixfmember.dismissed = dismissed
        ixfmember.save()


@pytest.fixture
def ip_addresses():
    """
    Returns a list of tuples of ipaddr4 and ipaddr6
    """
    return [
        ("195.69.144.1", "2001:7f8:1::a500:2906:1"),
        ("195.69.144.2", "2001:7f8:1::a500:2906:2"),
        ("195.69.144.3", "2001:7f8:1::a500:2906:3"),
        ("195.69.144.4", "2001:7f8:1::a500:2906:4"),
        ("195.69.144.5", "2001:7f8:1::a500:2906:5"),
    ]

@pytest.fixture
def ip_addresses_other():
    """
    Returns a list of tuples of ipaddr4 and ipaddr6
    """
    return [
        ("195.70.144.1", "2001:7f8:2::a500:2906:1"),
        ("195.70.144.2", "2001:7f8:2::a500:2906:2"),
        ("195.70.144.3", "2001:7f8:2::a500:2906:3"),
        ("195.70.144.4", "2001:7f8:2::a500:2906:4"),
        ("195.70.144.5", "2001:7f8:2::a500:2906:5"),
    ]



@pytest.fixture
def entities():
    entities = {}
    with reversion.create_revision():
        entities["org"] = [Organization.objects.create(name="Netflix", status="ok")]

        # create exchange(s)
        entities["ix"] = [
            InternetExchange.objects.create(
                name="Test Exchange One", org=entities["org"][0], status="ok"
            ),
            InternetExchange.objects.create(
                name="Test Exchange Two", org=entities["org"][0], status="ok"
            )
        ]

        # create ixlan(s)
        entities["ixlan"] = [ix.ixlan for ix in entities["ix"]]

        # create ixlan prefix(s)
        entities["ixpfx"] = [
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][0],
                status="ok",
                prefix="195.69.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][0],
                status="ok",
                prefix="2001:7f8:1::/64",
                protocol="IPv6",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="195.70.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="2001:7f8:2::/64",
                protocol="IPv6",
            ),
        ]

        # create network(s)
        entities["network"] = Network.objects.create(
            name="Network w allow ixp update enabled",
            org=entities["org"][0],
            asn=2906,
            info_prefixes4=42,
            info_prefixes6=42,
            website="http://netflix.com/",
            policy_general="Open",
            policy_url="https://www.netflix.com/openconnect/",
            allow_ixp_update=True,
            status="ok",
            irr_as_set="AS-NFLX",
        )
    return entities


@pytest.fixture
def admin_user():
    admin_user = User.objects.create_user(
        "admin", "admin@localhost", first_name="admin", last_name="admin"
    )
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user


@pytest.fixture
def regular_user():
    user = User.objects.create_user(
        "user", "user@localhost", first_name="user", last_name="user"
    )
    user.set_password("user")
    user.save()
    return user
