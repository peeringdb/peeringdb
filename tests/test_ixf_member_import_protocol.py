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
from django.test import TestCase, Client, RequestFactory
from django.core.management import call_command

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
from peeringdb_server.import_views import (
    view_import_ixlan_ixf_preview,
    view_import_net_ixf_preview,
    view_import_net_ixf_postmortem,
)
from peeringdb_server import ixf

from .util import ClientCase

import pytest

@pytest.mark.django_db
def test_resolve_local_ixf(entities):
    """
    Netixlan exists, remote data matches the netixlan, and there is a local-ixf
    entry that also matches all the data.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
            NetworkIXLan.objects.create(
                network=network,
                ixlan=ixlan,
                asn=network.asn,
                speed=10000,
                ipaddr4="195.69.147.250",
                ipaddr6="2001:7f8:1::a500:2906:1",
                status="ok",
                is_rs_peer=True,
                operational=True
            ))

    # Create a local IXF that matches remote details
    IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",
        ipaddr6="2001:7f8:1::a500:2906:1",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok"
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0
    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])


@pytest.mark.django_db
def test_update_data_attributes(entities):
    """
    The NetIXLan differs from the remote data, but allow_ixp_update is enabled
    so we update automatically.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=20000,
                    ipaddr4="195.69.147.250",
                    ipaddr6="2001:7f8:1::a500:2906:1",
                    status="ok",
                    is_rs_peer=False,
                    operational=False,
                ))

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]

    assert log["action"] == "modify"
    assert "is_rs_peer" in log["reason"]
    assert "operational" in log["reason"]
    assert "speed" in log["reason"]

    netixlan = NetworkIXLan.objects.first()
    assert netixlan.operational == True
    assert netixlan.is_rs_peer == True
    assert netixlan.speed == 10000

@pytest.mark.django_db
def test_update_disabled_local_ixf_matches(entities):
    """
    Netixlan is different from remote in terms of speed, operational, and is_rs_peer
    BUT there is already a local-ixf for the update.
    Automatic updates are disabled (so netixlan will not change).
    We do nothing and confirm the local-ixf stays the same.
    """
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=20000,
                    ipaddr4="195.69.147.250",
                    ipaddr6="2001:7f8:1::a500:2906:1",
                    status="ok",
                    is_rs_peer=False,
                    operational=False,
                ))

    # Matches the json data, doesn't match the existing netixlan.
    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",
        ipaddr6="2001:7f8:1::a500:2906:1",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok"
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 1
    assert preexisting_ixfmember_data == IXFMemberData.objects.first()

@pytest.mark.django_db
def test_update_disabled_no_local_ixf(entities, capsys):
    """
    Netixlan is different from remote in terms of speed, operational, and is_rs_peer.
    There is no local-ixf existing.
    We need to create a local ixf, create a ticket for admin com,
    email the network and email the ix.
    """
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=20000,
                    ipaddr4="195.69.147.250",
                    ipaddr6="2001:7f8:1::a500:2906:1",
                    status="ok",
                    is_rs_peer=False,
                    operational=False,
                ))

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    # Create local ixf
    assert IXFMemberData.objects.count() == 1
    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]
    assert log["action"] == "suggest-modify"

    # Create a ticket for Admin Com
    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])

    # NetIXLAN is unchanged
    assert NetworkIXLan.objects.first().speed == 20000
    assert NetworkIXLan.objects.first().is_rs_peer == False
    assert NetworkIXLan.objects.first().operational == False

    # Email is sent to the Network and the IX
    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))


# def test_update_disabled_outdated_local_ixf():
#     """
#     Netixlan is different from remote in terms of speed, operational, and is_rs_peer.
#     There is a local-ixf existing but it's outdated.
#     We need to create a local ixf, create a ticket for admin com,
#     email the network and email the ix.
#     """
#     pass

@pytest.mark.django_db
def test_add_netixlan(entities):
    """
    No NetIXLan exists but remote IXF data has information
    to create one (without conflicts). Updates are enabled
    so we create the NetIXLan.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    assert NetworkIXLan.objects.count() == 0

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    log = importer.log["data"][0]
    assert log["action"] == "add"
    assert NetworkIXLan.objects.count() == 1

@pytest.mark.django_db
def test_add_netixlan_conflict_local_ixf_exists(entities, capsys):
    """
    No NetIXLan exists. Network allows auto updates. While remote IXF data has information
    to create a new NetIXLan, there are conflicts with the ipaddresses that
    prevent it from being created. 
    There is already a local-ixf so we do nothing.
    """

    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][1] #So we have conflicts with IPAddresses 

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250", # Matches remote-ixf, but conflicts with IXLan
        ipaddr6="2001:7f8:1::a500:2906:1", # Matches remote-ixf, but conflicts with IXLan
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error=['IPv4 195.69.147.250 does not match any prefix on this ixlan'],
        data={"test":"test"},
    )

    original_update_timestamp = preexisting_ixfmember_data.updated

    assert IXFMemberData.objects.count() == 1
    importer = ixf.Importer()
    importer.update(ixlan, data=data)


    assert NetworkIXLan.objects.count() == 0

    ixfmemberdata = IXFMemberData.objects.first()
    assert IXFMemberData.objects.count() == 1
    assert original_update_timestamp == ixfmemberdata.updated

    assert_no_ticket_exists()

    stdout = capsys.readouterr().out
    assert stdout == ''
    
    


@pytest.mark.django_db
def test_add_netixlan_conflict_no_local_ixf(entities, capsys):
    """
    No NetIXLan exists. Network allows auto updates. While remote IXF data has information
    to create a new NetIXLan, there are conflicts with the ipaddresses that
    prevent it from being created. 
    There is no local-ixf so we create one.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][1] #So we have conflicts with IPAddresses 

    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    
    ixfmemberdata = IXFMemberData.objects.first()
    assert IXFMemberData.objects.count() == 1

    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])
   
    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))


@pytest.mark.django_db
def test_no_netixlan_local_ixf_exists(entities, capsys):
    """
    No netixlan, there is a matching IX, network has automatic updates disabled.
    But there is a local-ixf that matches the remote-ixf so do nothing.
    """
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0] 

    assert NetworkIXLan.objects.count() == 0

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001, #Matches remote-ixf data
        ipaddr4="195.69.147.250", #Matches remote-ixf data
        ipaddr6="2001:7f8:1::a500:2906:1", #Matches remote-ixf data
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data={"test":"test"}
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    # Currently failing
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    stdout = capsys.readouterr().out
    assert stdout == ''
    assert_no_ticket_exists()

    

@pytest.mark.django_db
def test_no_netixlan_no_local_ixf(entities, capsys):
    """
    No netixlan, there is a matching IX, network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We suggest adding the netixlan, create an admin ticket, and send emails to the 
    network and IX.
    """

    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0] 

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    log = importer.log["data"][0]
    assert log["action"] == "suggest-add"


    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))

    # Currently fails
    assert_ticket_exists([(2906, '195.69.147.250', '2001:7f8:1::a500:2906:1')])
    pass

def test_no_ix_local_ixf_exists():
    """
    No netixlan, no IX, network does not have automatic updates.
    But there is a local-ixf that matches the remote-ixf so do nothing.
    """
    pass

def test_no_ix_no_local_ixf():
    """
    No netixlan, no IX, network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We create local-ixf[as,ip4,ip6] and email the network
    but don't create a ticket or email the IX.
    """
    pass


def test_single_ipaddr_match():
    """
    If only one ipaddr matches, it's the same as not matching at all.
    """
    pass


@pytest.mark.django_db
def test_delete_netixlan(entities):
    """
    The ixf-remote doesn't contain an existing NetIXlan.
    Automatic updates are enabled so we delete it.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=10000,
                    ipaddr4="195.69.147.250",
                    ipaddr6="2001:7f8:1::a500:2906:1",
                    status="ok",
                    is_rs_peer=True,
                    operational=True
                ))

    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=20000,
                    ipaddr4="195.69.147.251",
                    ipaddr6=None,
                    status="ok",
                    is_rs_peer=False,
                    operational=False,
                ))
    assert NetworkIXLan.objects.filter(status="ok").count() == 2

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]

    assert log["action"] == "delete"
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

# # Update disabled
# def test_delete_netixlan_local_ixf_exists():
#     # Check deletion flag
#     # do nothing
#     pass
# def test_delete_netixlan_local_ixf_exists():
#     # Check deletion flag
#     # add deletion flag
#     pass
# def test_delete_no_local_ixf():
#     pass
#     # Create local-ixf w deletion flag

# # Check that we've emailed the IX???

# # invalid_but_parseable_data
# def local_matches_remote():
#     pass
# def no_local():
#     pass
#     # create INVALID local
#     # email ix


# # Remote cannot be parsed
# def remote_cannot_be_parsed():
#     #Create ticket
#     # Email ix
#     # Create LOCK
#     pass



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
                prefix="195.66.224.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="2001:7f8:4::/64",
                protocol="IPv6",
            ),
        ]

        # create network(s)
        entities["net"] = {
            "UPDATE_ENABLED": Network.objects.create(
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
            ),
            "UPDATE_DISABLED": Network.objects.create(
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
            )
        }

        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user("ixf_importer", "ixf_importer@localhost", "ixf_importer")
        entities["org"][0].admin_usergroup.user_set.add(admin_user)
    return entities



def setup_test_data(filename):
    json_data = {}
    entities = {}

    with open(
        os.path.join(
            os.path.dirname(__file__),
            "data",
            "json_members_list",
            "{}.json".format(filename),
        ),
        "r",
    ) as fh:
        json_data = json.load(fh)

    return json_data



def assert_ticket_exists(ticket_info):
    """
    Input is a list of tuples containing (asn, ipaddr4, ipaddr6) that should appear
    in deskpro tickets
    """
    assert DeskProTicket.objects.count() == len(ticket_info)
    
    for i, dpt in enumerate(DeskProTicket.objects.all()):
        assert all([str(s) in dpt.subject for s in ticket_info[i]])

def assert_no_ticket_exists():
    """
    Input is a list of tuples containing (asn, ipaddr4, ipaddr6) that should appear
    in deskpro tickets
    """
    assert DeskProTicket.objects.count() == 0


def assert_email_sent(email_text, email_info):
    assert all([str(s) in email_text for s in email_info])



