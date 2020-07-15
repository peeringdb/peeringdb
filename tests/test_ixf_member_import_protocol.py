import json
import os
from pprint import pprint
import reversion
import requests
import jsonschema
import time
import io
import datetime

from peeringdb_server.models import (
    Organization,
    Network,
    NetworkIXLan,
    NetworkContact,
    IXLan,
    IXLanPrefix,
    InternetExchange,
    IXFMemberData,
    IXLanIXFMemberImportLog,
    User,
    DeskProTicket
)
from peeringdb_server import ixf
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

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0


@pytest.mark.django_db
def test_update_data_attributes(entities):
    """
    The NetIXLan differs from the remote data, but allow_ixp_update is enabled
    so we update automatically.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    with reversion.create_revision():
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
    assert IXFMemberData.objects.count() == 0
    log = importer.log["data"][0]

    assert log["action"] == "modify"
    assert "is_rs_peer" in log["reason"]
    assert "operational" in log["reason"]
    assert "speed" in log["reason"]

    netixlan = NetworkIXLan.objects.first()
    assert netixlan.operational == True
    assert netixlan.is_rs_peer == True
    assert netixlan.speed == 10000

    # Assert idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.count() == 1

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    netixlan.refresh_from_db()
    assert netixlan.operational == False
    assert netixlan.is_rs_peer == False
    assert netixlan.speed == 20000


@pytest.mark.django_db
def test_suggest_modify_local_ixf(entities):
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


    # Assert idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert preexisting_ixfmember_data == IXFMemberData.objects.first()

@pytest.mark.django_db
def test_suggest_modify(entities, capsys):
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

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])


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

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    log = importer.log["data"][0]
    assert log["action"] == "add"
    assert NetworkIXLan.objects.count() == 1

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.count() == 1

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    assert NetworkIXLan.objects.first().status == "deleted"
    assert NetworkIXLan.objects.first().ipaddr4 == None
    assert NetworkIXLan.objects.first().ipaddr6  == None



@pytest.mark.django_db
def test_add_netixlan_conflict_local_ixf(entities, capsys):
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
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)


    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    ixfmemberdata = IXFMemberData.objects.first()
    assert "IPv4 195.69.147.250 does not match any prefix on this ixlan" in ixfmemberdata.error

    assert_no_ticket_exists()

    stdout = capsys.readouterr().out
    assert stdout == ''

    updated_timestamp = ixfmemberdata.updated
    importer.update(ixlan, data=data)
    assert updated_timestamp == IXFMemberData.objects.first().updated

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    assert_no_ticket_exists()



@pytest.mark.django_db
def test_add_netixlan_conflict(entities, capsys):
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
    assert "IPv4 195.69.147.250 does not match any prefix on this ixlan" in ixfmemberdata.error

    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])

    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    assert_ticket_exists([(network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1')])

@pytest.mark.django_db
def test_suggest_add_local_ixf(entities, capsys):
    """
    The netixlan described in the remote-ixf doesn't exist,
    but there is a relationship btw the network and ix (ie a different netixlan).
    The network does not have automatic updates.
    There's a local-ixf that matches the remote-ixf so we do nothing.
    """
    data = setup_test_data("ixf.member.2")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # This appears in the remote-ixf data so should not
    # create a IXFMemberData instance

    entities["netixlan"].append(
                    NetworkIXLan.objects.create(
                        network=network,
                        ixlan=ixlan,
                        asn=network.asn,
                        speed=10000,
                        ipaddr4="195.69.150.250",
                        ipaddr6="2001:7f8:1::a500:2906:3",
                        status="ok",
                        is_rs_peer=True,
                        operational=True,
                    ))


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
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1

    stdout = capsys.readouterr().out
    assert stdout == ''
    assert_no_ticket_exists()

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1
    assert_no_ticket_exists()


@pytest.mark.django_db
def test_suggest_add(entities, capsys):
    """
    The netixlan described in the remote-ixf doesn't exist,
    but there is a relationship btw the network and ix (ie a different netixlan).
    The network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We suggest adding the netixlan, create an admin ticket, and send emails to the
    network and IX.
    """

    data = setup_test_data("ixf.member.2") #asn1001
    network = entities["net"]["UPDATE_DISABLED"] #asn1001
    ixlan = entities["ixlan"][0]

    # This appears in the remote-ixf data so should not
    # create a IXFMemberData instance
    entities["netixlan"].append(
                    NetworkIXLan.objects.create(
                        network=network,
                        ixlan=ixlan,
                        asn=network.asn,
                        speed=10000,
                        ipaddr4="195.69.150.250",
                        ipaddr6="2001:7f8:1::a500:2906:3",
                        status="ok",
                        is_rs_peer=True,
                        operational=True,
                    ))

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1

    log = importer.log["data"][0]
    assert log["action"] == "suggest-add"

    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))

    assert_ticket_exists([(1001, '195.69.147.250', '2001:7f8:1::a500:2906:1')])

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1
    assert_ticket_exists([(1001, '195.69.147.250', '2001:7f8:1::a500:2906:1')])


@pytest.mark.django_db
def test_suggest_add_no_netixlan_local_ixf(entities, capsys):
    """
    There isn't any netixlan between ix and network.
    Network does not have automatic updates.
    There is a local-ixf that matches the remote-ixf so we do nothing
    """
    data = setup_test_data("ixf.member.1") #asn1001
    network = entities["net"]["UPDATE_DISABLED"] #asn1001
    ixlan = entities["ixlan"][0]

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001, #Matches remote-ixf data
        ipaddr4="195.69.147.250", #Matches remote-ixf data
        ipaddr6="2001:7f8:1::a500:2906:1", #Matches remote-ixf data
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
    assert NetworkIXLan.objects.count() == 0

    stdout = capsys.readouterr().out
    assert stdout == ""
    assert_no_ticket_exists()


    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    assert_no_ticket_exists()

@pytest.mark.django_db
def test_suggest_add_no_netixlan(entities, capsys):
    """
    There isn't any netixlan between ix and network.
    Network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We create local-ixf[as,ip4,ip6] and email the network
    but don't create a ticket or email the IX.
    """
    data = setup_test_data("ixf.member.1") #asn1001
    network = entities["net"]["UPDATE_DISABLED"] #asn1001
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    log = importer.log["data"][0]
    assert log["action"] == "suggest-add"

    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (network.asn, '195.69.147.250', '2001:7f8:1::a500:2906:1'))
    assert_no_ticket_exists()


    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    assert_no_ticket_exists()

@pytest.mark.django_db
def test_single_ipaddr_matches(entities, capsys):
    """
    If only one ipaddr matches, it's the same as not matching at all.
    Here we expect to delete the two netixlans and create a new one
    from the remote-ixf.
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
                        ipaddr6=None,
                        status="ok",
                        is_rs_peer=True,
                        operational=True
                    ))

    entities["netixlan"].append(
                    NetworkIXLan.objects.create(
                        network=network,
                        ixlan=ixlan,
                        asn=network.asn,
                        speed=10000,
                        ipaddr4=None,
                        ipaddr6="2001:7f8:1::a500:2906:1",
                        status="ok",
                        is_rs_peer=True,
                        operational=True,
                    ))


    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert len(importer.log["data"]) == 3
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

    assert importer.log["data"][0]["action"] == "delete"
    assert importer.log["data"][1]["action"] == "delete"
    assert importer.log["data"][2]["action"] == "add"

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.filter(status="ok").count() == 1
    assert_no_ticket_exists()



@pytest.mark.django_db
def test_delete(entities):
    """
    The ixf-remote doesn't contain an existing NetIXlan.
    Automatic updates are enabled so we delete it.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    with reversion.create_revision():
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

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]

    assert log["action"] == "delete"
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.filter(status="ok").count() == 1
    assert_no_ticket_exists()

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    assert NetworkIXLan.objects.filter(status="ok").count() == 2


@pytest.mark.django_db
def test_suggest_delete_local_ixf_has_flag(entities, capsys):
    """
    Automatic updates for network are disabled.
    There is no remote-ixf corresponding to an existing netixlan.
    There is a local-ixf flagging that netixlan for deletion.
    We want to do nothing.

    """
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
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

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,
        ipaddr4="195.69.147.251",
        ipaddr6=None,
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data={} # Makes self.remote_data_missing and self.marked_for_removal True
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1

    assert_no_ticket_exists()

    # Test idempotent
    importer.update(ixlan, data=data)
    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1
    assert_no_ticket_exists()


@pytest.mark.django_db
def test_suggest_delete_local_ixf_no_flag(entities, capsys):
    """
    Automatic updates for network are disabled.
    There is no remote-ixf corresponding to an existing netixlan.
    There is a local-ixf corresponding to that netixlan but it does not flag it
    for deletion.
    We flag the local-ixf for deletion, make a ticket, and email the ix and network.
    """
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
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
                    is_rs_peer=True,
                    operational=True,
                ))

    ixf_member_data_field = {
                    "ixp_id": 42,
                    "connected_since": "2009-02-04T00:00:00Z",
                    "state": "connected",
                    "if_list": [
                        {
                            "switch_id": 1,
                            "if_speed": 20000,
                            "if_type": "LR4"
                        }
                    ],
                    "vlan_list": [
                        {
                            "vlan_id": 0,
                            "ipv4": {
                                "address": "195.69.147.251",
                                "routeserver": True,
                                "max_prefix": 42,
                                "as_macro": "AS-NFLX-V4",
                                "mac_address" : [
                                    "00:0a:95:9d:68:16"
                                ]
                            }
                        }
                    ]
    }

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,
        ipaddr4="195.69.147.251",
        ipaddr6=None,
        ixlan=ixlan,
        speed=20000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data=json.dumps(ixf_member_data_field)
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert importer.log["data"][0]["action"] == "suggest-delete"
    assert NetworkIXLan.objects.count() == 2

    # Test failing, IXFMember is getting resolved
    # instead of being flagged for deletion.
    assert IXFMemberData.objects.count() == 1
    assert_ticket_exists([("AS1001", "195.69.147.251", "No IPv6")])

    stdout = capsys.readouterr().out
    assert_email_sent(stdout, (1001, '195.69.147.251', "No IPv6"))


    # Test idempotent
    importer.update(ixlan, data=data)
    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1
    assert_ticket_exists([("AS1001", "195.69.147.251", "No IPv6")])

@pytest.mark.django_db
def test_suggest_delete_no_local_ixf(entities, capsys):
    """
    Automatic updates for network are disabled.
    There is no remote-ixf corresponding to an existing netixlan.
    We flag the local-ixf for deletion, make a ticket, and email the ix and network.
    """

    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
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

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    assert importer.log["data"][0]["action"] == "suggest-delete"
    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1
    assert_ticket_exists([("AS1001", "195.69.147.251", "No IPv6")])

    stdout = capsys.readouterr().out
    assert_email_sent(stdout, ("AS1001", '195.69.147.251', "No IPv6"))

    # Test idempotent
    importer.update(ixlan, data=data)
    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1
    assert_ticket_exists([("AS1001", "195.69.147.251", "No IPv6")])

@pytest.mark.django_db
def test_mark_invalid_remote_w_local_ixf_auto_update(entities, capsys):
    """
    Our network allows automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is already a local-ixf flagging that invalid data.
    Do nothing.
    """
    data = setup_test_data("ixf.member.invalid.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    # Just to create a connection between the network and ix
    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=10000,
                    ipaddr4="195.69.147.200",
                    ipaddr6="2001:7f8:1::a500:2906:2",
                    status="ok",
                    is_rs_peer=True,
                    operational=True
                ))

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=2906,
        ipaddr4="195.69.147.200",
        ipaddr6="2001:7f8:1::a500:2906:2",
        ixlan=ixlan,
        speed=0,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error="Invalid speed value: this is not valid",
    )

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=2906,
        ipaddr4="195.69.147.100",
        ipaddr6="2001:7f8:1::a500:2906:4",
        ixlan=ixlan,
        speed=0,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error="Invalid speed value: this is not valid",
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 2
    stdout = capsys.readouterr().out
    assert stdout == ""
    assert_no_ticket_exists()


    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 2
    assert_no_ticket_exists()


@pytest.mark.django_db
def test_mark_invalid_remote_auto_update(entities, capsys):
    """
    The network does enable automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is not a local-ixf flagging that invalid data.
    We create a local-ixf[as,ip4,ip6] and flag as invalid
    Email the ix
    Create/Update a ticket for admin com
    """
    data = setup_test_data("ixf.member.invalid.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    # Just to create a connection between the network and ix
    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=10000,
                    ipaddr4="195.69.147.200",
                    ipaddr6="2001:7f8:1::a500:2906:2",
                    status="ok",
                    is_rs_peer=True,
                    operational=True
                ))

    importer = ixf.Importer()
    data = importer.sanitize(data)
    importer.update(ixlan, data=data)

    print([(n.speed, n.ipaddr4, n.ipaddr6, n.asn) for n in NetworkIXLan.objects.all()])
    print(importer.log)
    assert NetworkIXLan.objects.count() == 1
    assert IXFMemberData.objects.count() == 2
    ERROR_MESSAGE = "Invalid speed value"
    stdout = capsys.readouterr().out
    assert ERROR_MESSAGE in stdout
    assert_ticket_exists([
        ("AS2906", "195.69.147.100", "2001:7f8:1::a500:2906:4"),
        ("AS2906", "195.69.147.200", "2001:7f8:1::a500:2906:2")
    ])

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 2
    assert_ticket_exists([
        ("AS2906", "195.69.147.100", "2001:7f8:1::a500:2906:4"),
        ("AS2906", "195.69.147.200", "2001:7f8:1::a500:2906:2")
    ])



@pytest.mark.django_db
def test_mark_invalid_remote_w_local_ixf_no_auto_update(entities, capsys):
    """
    Our network does not allow automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is already a local-ixf flagging that invalid data.
    Do nothing.
    """
    data = setup_test_data("ixf.member.invalid.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # Just to create a connection between the network and ix
    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=10000,
                    ipaddr4="195.69.147.200",
                    ipaddr6="2001:7f8:1::a500:2906:2",
                    status="ok",
                    is_rs_peer=True,
                    operational=True
                ))

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,
        ipaddr4="195.69.147.200",
        ipaddr6="2001:7f8:1::a500:2906:2",
        ixlan=ixlan,
        speed=0,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error="Invalid speed value: this is not valid",
    )

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,
        ipaddr4="195.69.147.100",
        ipaddr6="2001:7f8:1::a500:2906:4",
        ixlan=ixlan,
        speed=0,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error="Invalid speed value: this is not valid",
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 2
    stdout = capsys.readouterr().out
    assert stdout == ""
    assert_no_ticket_exists()


    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 2
    assert_no_ticket_exists()



@pytest.mark.django_db
def test_mark_invalid_remote_no_auto_update(entities, capsys):
    """
    Our network does not allow automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is not a local-ixf flagging that invalid data.
    We create a local-ixf[as,ip4,ip6] and flag as invalid
    Email the ix
    Create/Update a ticket for admin com
    """
    data = setup_test_data("ixf.member.invalid.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # Just to create a connection between the network and ix
    entities["netixlan"].append(
                NetworkIXLan.objects.create(
                    network=network,
                    ixlan=ixlan,
                    asn=network.asn,
                    speed=10000,
                    ipaddr4="195.69.147.200",
                    ipaddr6="2001:7f8:1::a500:2906:2",
                    status="ok",
                    is_rs_peer=True,
                    operational=True
                ))

    importer = ixf.Importer()
    data = importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert IXFMemberData.objects.count() == 2
    ERROR_MESSAGE = "Invalid speed value"
    stdout = capsys.readouterr().out
    assert ERROR_MESSAGE in stdout
    assert_ticket_exists([
        ("AS1001", "195.69.147.100", "2001:7f8:1::a500:2906:4"),
        ("AS1001", "195.69.147.200", "2001:7f8:1::a500:2906:2")
    ])

    # Test idempotent
    importer.update(ixlan, data=data)
    assert IXFMemberData.objects.count() == 2
    assert_ticket_exists([
        ("AS1001", "195.69.147.100", "2001:7f8:1::a500:2906:4"),
        ("AS1001", "195.69.147.200", "2001:7f8:1::a500:2906:2")
    ])

@pytest.mark.django_db
def test_remote_cannot_be_parsed(entities, capsys):
    """
    Remote cannot be parsed. We create a ticket, email the IX, and create a lock.
    """
    data = setup_test_data("ixf.member.unparsable")
    ixlan = entities["ixlan"][0]
    start = datetime.datetime.now(datetime.timezone.utc)
    importer = ixf.Importer()
    importer.sanitize(data)
    importer.update(ixlan, data=data)

    ERROR_MESSAGE = "No entries in any of the vlan_list lists, aborting"
    assert importer.ixlan.ixf_ixp_import_error_notified > start # This sets the lock
    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
    stdout = capsys.readouterr().out
    assert ERROR_MESSAGE in stdout
    assert DeskProTicket.objects.count() == 1

    # Assert idempotent / lock
    importer.sanitize(data)
    importer.update(ixlan, data=data)
    stdout = capsys.readouterr().out
    assert stdout == ""
    assert DeskProTicket.objects.count() == 1


def test_validate_json_schema():
    schema_url_base = "https://raw.githubusercontent.com/euro-ix/json-schemas/master/versions/ixp-member-list-{}.schema.json"

    for v in ["0.4","0.5","0.6","0.7"]:
        schema = requests.get(schema_url_base.format(v)).json()

        for fn in ["ixf.member.0", "ixf.member.1", "ixf.member.2", "ixf.member.unparsable"]:
            data = setup_test_data(fn)
            jsonschema.validate(data, schema)

        for fn in ["ixf.member.invalid.0", "ixf.member.invalid.1"]:
            data = setup_test_data(fn)
            with pytest.raises(jsonschema.exceptions.ValidationError):
                jsonschema.validate(data, schema)



# FIXTURES
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

        entities["netcontact"] = [
            NetworkContact.objects.create(
                email="network1@localhost",
                network=entities["net"]["UPDATE_ENABLED"]
            ),
            NetworkContact.objects.create(
                email="network2@localhost",
                network=entities["net"]["UPDATE_DISABLED"]
            )
        ]
        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user("ixf_importer", "ixf_importer@localhost", "ixf_importer")
        entities["org"][0].admin_usergroup.user_set.add(admin_user)
    return entities


# TEST FUNCTIONS
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

# CUSTOM ASSERTIONS
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