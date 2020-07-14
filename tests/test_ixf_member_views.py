import json
import os
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
    DeskProTicket
)
from peeringdb_server import ixf

import pytest

@pytest.mark.django_db
def test_reset_ixf_proposals(admin_user, entities, prefixes):
    network = entities["network"]
    ixlan = entities["ixlan"]

    client = setup_client(admin_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id, ))

    create_IXFMemberData(network, ixlan, prefixes, True)

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(dismissed=True).count() == 0

@pytest.mark.django_db
def test_dismiss_ixf_proposals(admin_user, entities, prefixes):
    IXF_ID = 3
    network = entities["network"]
    ixlan = entities["ixlan"]

    create_IXFMemberData(network, ixlan, prefixes, False)

    client = setup_client(admin_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, IXF_ID))


    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(pk=IXF_ID).first().dismissed == True
     

@pytest.mark.django_db
def test_reset_ixf_proposals_no_perm(regular_user, entities, prefixes):
    network = entities["network"]
    ixlan = entities["ixlan"]

    client = setup_client(regular_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id, ))

    create_IXFMemberData(network, ixlan, prefixes, True)

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content

@pytest.mark.django_db
def test_dismiss_ixf_proposals_no_perm(regular_user, entities, prefixes):
    IXF_ID = 3
    network = entities["network"]
    ixlan = entities["ixlan"]

    create_IXFMemberData(network, ixlan, prefixes, False)

    client = setup_client(regular_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, IXF_ID))


    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content


# Functions and fixtures

def setup_client(user):
    client = Client()
    client.force_login(user)
    return client

def create_IXFMemberData(network, ixlan, prefixes, dismissed):
    """
    Creates IXFMember data
    """
    for prefix in prefixes:
        ixfmember = IXFMemberData.instantiate(network.asn, prefix[0], prefix[1], ixlan)
        ixfmember.save()
        ixfmember.dismissed = dismissed
        ixfmember.save()

@pytest.fixture
def prefixes():
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
def entities():
    entities = {}
    with reversion.create_revision():
        entities["org"] = [Organization.objects.create(name="Netflix", status="ok")]

        # create exchange(s)
        entities["ix"] = InternetExchange.objects.create(
                name="Test Exchange One", org=entities["org"][0], status="ok"
        )
        

        # create ixlan(s)
        entities["ixlan"] = entities["ix"].ixlan

        # create ixlan prefix(s)
        entities["ixpfx"] = [
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"],
                status="ok",
                prefix="195.69.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"],
                status="ok",
                prefix="2001:7f8:1::/64",
                protocol="IPv6",
            )
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

