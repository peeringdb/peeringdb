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
    DeskProTicket,
    IXFImportEmail
)
from peeringdb_server import ixf
import pytest


@pytest.mark.django_db
def test_resolve_local_ixf(entities, save):
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
            operational=True,
        )
    )

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
        status="ok",
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0

    # We do not email upon resolve
    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_update_data_attributes(entities, save):
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
            )
        )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()


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
    assert_idempotent(importer, ixlan, data)

    # Assert no emails
    assert_no_emails()

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    netixlan.refresh_from_db()
    assert netixlan.operational == False
    assert netixlan.is_rs_peer == False
    assert netixlan.speed == 20000


@pytest.mark.django_db
def test_suggest_modify_local_ixf(entities, save):
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
        )
    )

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
        status="ok",
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert_no_emails()

    assert IXFMemberData.objects.count() == 1
    assert preexisting_ixfmember_data == IXFMemberData.objects.first()

    # Assert idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_modify(entities, save):
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
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Create local ixf
    assert IXFMemberData.objects.count() == 1
    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]
    assert log["action"] == "suggest-modify"

    # NetIXLAN is unchanged
    assert NetworkIXLan.objects.first().speed == 20000
    assert NetworkIXLan.objects.first().is_rs_peer == False
    assert NetworkIXLan.objects.first().operational == False

    # Consolidated email is sent to the Network and the IX
    email_info = [("MODIFY", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1


@pytest.mark.django_db
def test_add_netixlan(entities, save):
    """
    No NetIXLan exists but remote IXF data has information
    to create one (without conflicts). Updates are enabled
    so we create the NetIXLan.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    log = importer.log["data"][0]
    assert log["action"] == "add"
    assert NetworkIXLan.objects.count() == 1

    # Test idempotent
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.count() == 1

    assert_no_emails()

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    assert NetworkIXLan.objects.first().status == "deleted"
    assert NetworkIXLan.objects.first().ipaddr4 == None
    assert NetworkIXLan.objects.first().ipaddr6 == None


@pytest.mark.django_db
def test_add_netixlan_conflict_local_ixf(entities, save):
    """
    No NetIXLan exists. Network allows auto updates. While remote IXF data has information
    to create a new NetIXLan, there are conflicts with the ipaddresses that
    prevent it from being created.
    There is already a local-ixf so we do nothing.
    """

    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]

    ixlan = entities["ixlan"][1]  # So we have conflicts with IPAddresses

    # invalid prefix space error will only be raised if
    # the other ipaddress (v6 in this case) matches
    # so we move that prefix over

    ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv6").first()
    ixpfx.ixlan = entities["ixlan"][1]
    ixpfx.save()

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",  # Matches remote-ixf, but conflicts with IXLan
        ipaddr6="2001:7f8:1::a500:2906:1",  # Matches remote-ixf, but conflicts with IXLan
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        error=["IPv4 195.69.147.250 does not match any prefix on this ixlan"],
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    ixfmemberdata = IXFMemberData.objects.first()
    assert (
        "IPv4 195.69.147.250 does not match any prefix on this ixlan"
        in ixfmemberdata.error
    )

    assert_no_emails()

    updated_timestamp = ixfmemberdata.updated
    importer.update(ixlan, data=data)
    importer.notify_proposals()
    assert updated_timestamp == IXFMemberData.objects.first().updated

    # Test idempotent
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    assert_no_emails()


@pytest.mark.django_db
def test_add_netixlan_conflict(entities, save):
    """
    No NetIXLan exists. Network allows auto updates. While remote IXF data has information
    to create a new NetIXLan, there are conflicts with the ipaddresses that
    prevent it from being created.
    There is no local-ixf so we create one.
    """

    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][1]  # So we have conflicts with IPAddresses

    # invalid prefix space error will only be raised if
    # the other ipaddress (v6 in this case) matches
    # so we move that prefix over

    ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv6").first()
    ixpfx.ixlan = entities["ixlan"][1]
    ixpfx.save()

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixfmemberdata = IXFMemberData.objects.first()
    assert IXFMemberData.objects.count() == 1
    assert (
        "IPv4 195.69.147.250 does not match any prefix on this ixlan"
        in ixfmemberdata.error
    )
    
    email_info = [("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0
    

@pytest.mark.django_db
def test_suggest_add_local_ixf(entities, save):
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
        )
    )

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,  # Matches remote-ixf data
        ipaddr4="195.69.147.250",  # Matches remote-ixf data
        ipaddr6="2001:7f8:1::a500:2906:1",  # Matches remote-ixf data
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1

    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add(entities, save):
    """
    The netixlan described in the remote-ixf doesn't exist,
    but there is a relationship btw the network and ix (ie a different netixlan).
    The network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We suggest adding the netixlan, create an admin ticket, and send emails to the
    network and IX.
    """

    data = setup_test_data("ixf.member.2")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
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
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 1

    log = importer.log["data"][0]
    assert log["action"] == "suggest-add"

    email_info  = [("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")]

    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add_no_netixlan_local_ixf(entities, save):
    """
    There isn't any netixlan between ix and network.
    Network does not have automatic updates.
    There is a local-ixf that matches the remote-ixf so we do nothing
    """
    data = setup_test_data("ixf.member.1")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
    ixlan = entities["ixlan"][0]

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=1001,  # Matches remote-ixf data
        ipaddr4="195.69.147.250",  # Matches remote-ixf data
        ipaddr6="2001:7f8:1::a500:2906:1",  # Matches remote-ixf data
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add_no_netixlan(entities, save):
    """
    There isn't any netixlan between ix and network.
    Network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We create local-ixf[as,ip4,ip6] and email the network
    but don't create a ticket or email the IX.
    """
    data = setup_test_data("ixf.member.1")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert NetworkIXLan.objects.count() == 0

    log = importer.log["data"][0]
    assert log["action"] == "suggest-add"

    email_info = [("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")]
    
    assert_network_email(network, email_info)
    assert_no_ix_email(ixlan.ix)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_single_ipaddr_matches(entities, save):
    """
    If only one ipaddr matches, that's still a conflict.
    Here we expect to delete the two netixlans and create a new one
    from the remote-ixf.

    There are no notifications since updates are enabled.
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
            operational=True,
        )
    )

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
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert len(importer.log["data"]) == 3
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

    assert importer.log["data"][0]["action"] == "delete"
    assert importer.log["data"][1]["action"] == "delete"
    assert importer.log["data"][2]["action"] == "add"

    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_ipaddr4_matches_no_auto_update(entities, save):
    """
    For the Netixlan, Ipaddr4 matches the remote date but Ipaddr6 is Null.
    In terms of IXFMemberData, we suggest delete the two Netixlans and create a new one.
    In terms of notifications, we consolidate that deletions + addition into a single 
    MODIFY proposal.
    This tests the changes in issue #770.
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
            ipaddr6=None,
            status="ok",
            is_rs_peer=True,
            operational=True
        )
    )
    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Assert NetworkIXLan is unchanged
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

    # On the IXFMemberData side, we create instances for a deletion and addition.
    # The deletion will be the requirement of the addition.
    ixfmdata_d = IXFMemberData.objects.filter(ipaddr4="195.69.147.250", ipaddr6=None).first()
    ixfmdata_m = IXFMemberData.objects.filter(ipaddr4="195.69.147.250", ipaddr6="2001:7f8:1::a500:2906:1").first()

    assert IXFMemberData.objects.count() == 2
    assert ixfmdata_d.action == "delete"
    assert ixfmdata_m.action == "modify"
    assert ixfmdata_d.requirement_of == ixfmdata_m


    # We consolidate notifications into a single MODIFY
    assert len(importer.log["data"]) == 1
    assert importer.log["data"][0]["action"] == "suggest-modify"

    
    email_info = [("MODIFY", network.asn, "195.69.147.250", "IPv6 not set")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)



@pytest.mark.django_db
def test_ipaddr6_matches_no_auto_update(entities, save):
    """
    For the Netixlan, Ipaddr6 matches the remote date but Ipaddr4 is Null.
    In terms of IXFMemberData, we suggest delete the two Netixlans and create a new one.
    In terms of notifications, we consolidate that deletions + addition into a single 
    MODIFY proposal.

    This tests the changes in issue #770.
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
            ipaddr4=None,
            ipaddr6="2001:7f8:1::a500:2906:1",
            status="ok",
            is_rs_peer=True,
            operational=True
        )
    )
    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Assert NetworkIXLan is unchanged
    assert NetworkIXLan.objects.filter(status="ok").count() == 1

    # On the IXFMemberData side, we create instances for a deletion and addition.
    # The deletion will be the requirement of the addition.
    ixfmdata_d = IXFMemberData.objects.filter(ipaddr4=None, ipaddr6="2001:7f8:1::a500:2906:1").first()
    ixfmdata_m = IXFMemberData.objects.filter(ipaddr4="195.69.147.250", ipaddr6="2001:7f8:1::a500:2906:1").first()

    assert IXFMemberData.objects.count() == 2
    assert ixfmdata_d.action == "delete"
    assert ixfmdata_m.action == "modify"
    assert ixfmdata_d.requirement_of == ixfmdata_m


    # We consolidate notifications into a single MODIFY
    assert len(importer.log["data"]) == 1
    assert importer.log["data"][0]["action"] == "suggest-modify"

    email_info = [("MODIFY", network.asn, "IPv4 not set", "2001:7f8:1::a500:2906:1")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_two_missing_ipaddrs_no_auto_update(entities, save):
    """
    Now we have two Netixlans, each missing 1 ipaddr. The remote has data for a single netixlan with 
    both ip addressses.

    In terms of IXFMemberData, we suggest delete the two Netixlans and create a new one.
    In terms of notifications, we consolidate that deletions + addition into a single 
    MODIFY proposal.

    This tests the changes in issue #770.
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
            ipaddr6=None,
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )

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
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()
    # Assert NetworkIXLans are unchanged
    assert NetworkIXLan.objects.filter(status="ok").count() == 2

    # On the IXFMemberData side, we create instances for two deletions and one addition.
    # The deletions will be the requirement of the addition.
    assert IXFMemberData.objects.count() == 3
    ixfmdata_d4 = IXFMemberData.objects.filter(ipaddr4="195.69.147.250", ipaddr6=None).first()
    ixfmdata_d6 = IXFMemberData.objects.filter(ipaddr4=None, ipaddr6="2001:7f8:1::a500:2906:1").first()
    ixfmdata_m = IXFMemberData.objects.filter(ipaddr4="195.69.147.250", ipaddr6="2001:7f8:1::a500:2906:1").first()

    assert ixfmdata_d4.action == "delete"
    assert ixfmdata_d6.action == "delete"
    assert ixfmdata_m.action == "modify"
    assert ixfmdata_d4.requirement_of == ixfmdata_m
    assert ixfmdata_d6.requirement_of == ixfmdata_m

    assert ixfmdata_m.primary_requirement == ixfmdata_d4
    assert ixfmdata_m.secondary_requirements == [ixfmdata_d6]

    # We consolidate notifications into a single MODIFY
    assert len(importer.log["data"]) == 1
    assert importer.log["data"][0]["action"] == "suggest-modify"


    # We only create an email for the primary requirement 
    email_info_4 = [("MODIFY", network.asn, "195.69.147.250", "IPv6 not set")]
    assert IXFImportEmail.objects.count() == 2
    assert_ix_email(ixlan.ix, email_info_4)
    assert_network_email(network, email_info_4)
    
    # Test idempotent
    assert_idempotent(importer, ixlan, data)

@pytest.mark.django_db
def test_delete(entities, save):
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
                operational=True,
            )
        )

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
            )
        )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]

    assert log["action"] == "delete"
    assert NetworkIXLan.objects.filter(status="ok").count() == 1
    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    assert NetworkIXLan.objects.filter(status="ok").count() == 2


@pytest.mark.django_db
def test_suggest_delete_local_ixf_has_flag(entities, save):
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
            operational=True,
        )
    )

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
        )
    )

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
        data={},  # Makes self.remote_data_missing and self.marked_for_removal True
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1

    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_delete_local_ixf_no_flag(entities, save):
    """
    Automatic updates for network are disabled.
    There is no remote-ixf corresponding to an existing netixlan.
    There is a local-ixf corresponding to that netixlan but it does not flag it
    for deletion.
    We flag the local-ixf for deletion, and email the ix and network.
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
            operational=True,
        )
    )

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
        )
    )

    ixf_member_data_field = {
        "ixp_id": 42,
        "connected_since": "2009-02-04T00:00:00Z",
        "state": "connected",
        "if_list": [{"switch_id": 1, "if_speed": 20000, "if_type": "LR4"}],
        "vlan_list": [
            {
                "vlan_id": 0,
                "ipv4": {
                    "address": "195.69.147.251",
                    "routeserver": True,
                    "max_prefix": 42,
                    "as_macro": "AS-NFLX-V4",
                    "mac_address": ["00:0a:95:9d:68:16"],
                },
            }
        ],
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
        data=json.dumps(ixf_member_data_field),
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert importer.log["data"][0]["action"] == "suggest-delete"
    assert NetworkIXLan.objects.count() == 2

    assert IXFMemberData.objects.count() == 1

    email_info = [("REMOVE", 1001, "195.69.147.251", "IPv6 not set")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_delete_no_local_ixf(entities, save):
    """
    Automatic updates for network are disabled.
    There is no remote-ixf corresponding to an existing netixlan.
    We flag the local-ixf for deletion, and email the ix and network.
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
            operational=True,
        )
    )

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
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert importer.log["data"][0]["action"] == "suggest-delete"
    assert NetworkIXLan.objects.count() == 2
    assert IXFMemberData.objects.count() == 1

    email_info = [("REMOVE", 1001, "195.69.147.251", "IPv6 not set")]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_mark_invalid_remote_w_local_ixf_auto_update(entities, save):
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
            operational=True,
        )
    )

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

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 2
    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_mark_invalid_remote_auto_update(entities, save):
    """
    The network does enable automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is not a local-ixf flagging that invalid data.
    We create a local-ixf[as,ip4,ip6] and flag as invalid
    Email the ix
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
            operational=True,
        )
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert NetworkIXLan.objects.count() == 1
    assert IXFMemberData.objects.count() == 2

    # We email to say there is invalid data
    email_info = [
        ("CREATE", network.asn,"195.69.147.100","2001:7f8:1::a500:2906:4"),
        ("MODIFY", network.asn,"195.69.147.200","2001:7f8:1::a500:2906:2")
    ]
    assert_network_email(network, email_info)
    assert_ix_email(ixlan.ix, email_info)
    assert "Invalid speed value: This is invalid" in IXFImportEmail.objects.filter(net=network.id).first().message
    assert "Invalid speed value: This is invalid" in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message

    # Test idempotent
    assert_idempotent(importer, ixlan, data)

@pytest.mark.django_db
def test_mark_invalid_remote_w_local_ixf_no_auto_update(entities, save):
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
            operational=True,
        )
    )

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

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 2
    assert_no_emails()

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_mark_invalid_remote_no_auto_update(entities, save):
    """
    Our network does not allow automatic updates.
    Remote-ixf[as,ip4,ip6] contains invalid data **but** it can be parsed.
    There is not a local-ixf flagging that invalid data.
    We create a local-ixf[as,ip4,ip6] and flag as invalid
    Email the ix
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
            operational=True,
        )
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()


    assert IXFMemberData.objects.count() == 2

    # We send an email about the updates 
    # But it also contains information about the invalid speed
    email_info = [
        ("CREATE", network.asn,"195.69.147.100","2001:7f8:1::a500:2906:4"),
        ("MODIFY", network.asn,"195.69.147.200","2001:7f8:1::a500:2906:2")
    ]
    assert_ix_email(ixlan.ix, email_info)
    assert "Invalid speed value: This is invalid" in IXFImportEmail.objects.first().message
    assert_no_network_email(network)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)

@pytest.mark.django_db
def test_remote_cannot_be_parsed(entities, save):
    """
    Remote cannot be parsed. We create a ticket, email the IX, and create a lock.
    """
    data = setup_test_data("ixf.member.unparsable")
    ixlan = entities["ixlan"][0]
    start = datetime.datetime.now(datetime.timezone.utc)
    importer = ixf.Importer()
    importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ERROR_MESSAGE = "No entries in any of the vlan_list lists, aborting"
    assert importer.ixlan.ixf_ixp_import_error_notified > start  # This sets the lock
    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
    assert ERROR_MESSAGE in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message

    # Assert idempotent / lock
    importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
    assert IXFImportEmail.objects.filter(ix=ixlan.ix.id).count() == 1


def test_validate_json_schema():
    schema_url_base = "https://raw.githubusercontent.com/euro-ix/json-schemas/master/versions/ixp-member-list-{}.schema.json"

    for v in ["0.4", "0.5", "0.6", "0.7"]:
        schema = requests.get(schema_url_base.format(v)).json()

        for fn in [
            "ixf.member.0",
            "ixf.member.1",
            "ixf.member.2",
            "ixf.member.unparsable",
        ]:
            data = setup_test_data(fn)
            jsonschema.validate(data, schema)

        for fn in ["ixf.member.invalid.0", "ixf.member.invalid.1"]:
            data = setup_test_data(fn)
            with pytest.raises(jsonschema.exceptions.ValidationError):
                jsonschema.validate(data, schema)


# FIXTURES
@pytest.fixture(params=[True, False])
def save(request):
    return request.param


@pytest.fixture
def entities():
    entities = {}
    with reversion.create_revision():
        entities["org"] = [Organization.objects.create(name="Netflix", status="ok")]

        # create exchange(s)
        entities["ix"] = [
            InternetExchange.objects.create(
                name="Test Exchange One", org=entities["org"][0], status="ok", tech_email="ix1@localhost"
            ),
            InternetExchange.objects.create(
                name="Test Exchange Two", org=entities["org"][0], status="ok", tech_email="ix2@localhost"
            ),
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
                info_unicast=True,
                info_ipv6=True
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
                info_unicast=True,
                info_ipv6=True
            ),
        }

        entities["netcontact"] = [
            NetworkContact.objects.create(
                email="network1@localhost", network=entities["net"]["UPDATE_ENABLED"], status="ok", role="Policy"
            ),
            NetworkContact.objects.create(
                email="network2@localhost", network=entities["net"]["UPDATE_DISABLED"], status="ok", role="Policy"
            ),
        ]
        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"][0].admin_usergroup.user_set.add(admin_user)
    return entities


# TEST FUNCTIONS
def setup_test_data(filename):
    json_data = {}
    entities = {}

    with open(
        os.path.join(
            os.path.dirname(__file__), "data", "json_members_list", f"{filename}.json",
        ),
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

    for ticket in DeskProTicket.objects.all():
        print(ticket.subject)
        print("-" * 80)

    for asn, ip4, ip6 in ticket_info:
        assert DeskProTicket.objects.filter(
            subject__endswith=f"AS{asn} {ip4} {ip6}"
        ).exists()


def assert_network_email(network, email_info):
    network_email = IXFImportEmail.objects.filter(net=network.id).first()
    print("Network email")
    print("Body:")
    print(network_email.message)

    for email_i in email_info:
        email_str = create_email_str(email_i)
        assert email_str in network_email.message

def assert_ix_email(ix, email_info):
    ix_email = IXFImportEmail.objects.filter(ix=ix.id).first()
    print("IX email")
    print("Body:")
    print(ix_email.message)
    for email_i in email_info:
        email_str = create_email_str(email_i)
        assert email_str in ix_email.message

def create_email_str(email):
    return '{} AS{} - {} - {}'.format(*email)

def assert_no_ticket_exists():
    """
    Input is a list of tuples containing (asn, ipaddr4, ipaddr6) that should appear
    in deskpro tickets
    """
    assert DeskProTicket.objects.count() == 0

def assert_email_sent(email_text, email_info):
    assert all([str(s) in email_text for s in email_info])

def assert_no_emails():
    assert IXFImportEmail.objects.count() == 0

def assert_no_ix_email(ix):
    assert IXFImportEmail.objects.filter(ix=ix.id).count() == 0

def assert_no_network_email(network):
    assert IXFImportEmail.objects.filter(net=network.id).count() == 0

def ticket_list():
    return [(t.id, t.subject) for t in DeskProTicket.objects.all().order_by("id")]


def ixf_member_data_list():
    return [
        (m.id, m.ipaddr4, m.ipaddr6, m.updated)
        for m in IXFMemberData.objects.all().order_by("id")
    ]


def netixlan_list():
    return [
        (n.id, n.status, n.ipaddr4, n.ipaddr6, n.updated)
        for n in NetworkIXLan.objects.all().order_by("id")
    ]


def assert_idempotent(importer, ixlan, data, save=True):

    """
    run the importer for ixlan against data and
    assert that there are

    - no changes made to netixlan
    - no changes made to deskpro ticket
    - no changes made to ixf member data
    """

    ixf_members = ixf_member_data_list()
    tickets = ticket_list()
    netixlans = netixlan_list()

    def assert_no_changes():
        assert ixf_members == ixf_member_data_list()
        assert tickets == ticket_list()
        assert netixlans == netixlan_list()

    # Test idempotent
    importer.update(ixlan, data=data, save=save)
    importer.notify_proposals()
    assert_no_changes()

    # Test idempotent when running against single
    # non-existing asn
    importer.update(ixlan, data=data, asn=12345, save=save)
    importer.notify_proposals()
    assert_no_changes()
