import datetime
import io
import ipaddress
import json
import os
import time
from pprint import pprint

import jsonschema
import pytest
import requests
import reversion
from django.conf import settings
from django.test import override_settings

from peeringdb_server import ixf
from peeringdb_server.deskpro import FailingMockAPIClient
from peeringdb_server.models import (
    DataChangeNotificationQueue,
    DataChangeWatchedObject,
    DeskProTicket,
    InternetExchange,
    IXFImportEmail,
    IXFMemberData,
    IXLan,
    IXLanIXFMemberImportLog,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    User,
)

from .util import setup_test_data


@pytest.mark.django_db
def test_invalid_member_type(entities):
    data = setup_test_data("ixf.invalid.member.0")
    importer = ixf.Importer()
    ixlan = entities["ixlan"][0]
    importer.update(ixlan, data=data)
    for entry in importer.log["data"]:
        assert "Invalid member type:" in entry["reason"]


@pytest.mark.django_db
def test_add_deleted_netixlan(entities, use_ip, save):
    """
    Check that we can add back a netixlan if (asn, ip4, ip6) in the ixf member data
    matches a deleted netixlan. Check also that if speed, operational, or is_rs_peer
    values are different, they take on the new ixf member data values.
    """

    data = setup_test_data("ixf.member.speed.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    netixlan = NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=1,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        status="ok",
        is_rs_peer=True,
        operational=False,
    )

    netixlan.delete()

    assert NetworkIXLan.objects.filter(status="ok").count() == 0
    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    for email in IXFImportEmail.objects.all():
        print(email.message)

    assert_no_emails(network, ixlan.ix)

    netixlan = NetworkIXLan.objects.filter(status="ok").first()
    # Assert data values are updated
    assert netixlan.is_rs_peer == True
    assert netixlan.operational == True
    assert netixlan.speed == 0


@pytest.mark.django_db
def test_resolve_local_ixf(entities, use_ip, save):
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
            ipaddr4=use_ip(4, "195.69.147.250"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )

    # Create a local IXF that matches remote details
    IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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
    assert_no_emails(network, ixlan.ix)

    importer.update(ixlan, data=data)
    importer.notify_proposals()
    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_resolve_local_ixf_stale_netixlan(entities, use_ip, save):
    """
    Netixlan exists, remote data does not match the netixlan, and there is a local-ixf
    entry that also matches all the data.

    The local-ixf entry is past the allowed proposal age, so both it and the
    netixlan should be deleted.
    """
    data = setup_test_data("ixf.member.7")
    network = entities["net"]["UPDATE_DISABLED_2"]
    network_o = entities["net"]["UPDATE_ENABLED"]

    ixlan = entities["ixlan"][0]
    ixlan.ixf_ixp_import_enabled = True

    netixlan = NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=10000,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        status="ok",
        is_rs_peer=True,
        operational=True,
    )

    entities["netixlan"].append(netixlan)

    # Create a local IXF that matches remote details
    ixm = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data="{}",
        extra_notifications_net_num=0,
        extra_notifications_net_date=None,
    )

    assert IXFMemberData.objects.count() == 1

    ixm.created = ixm.created - datetime.timedelta(
        days=settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD + 1
    )
    ixm.save()

    assert ixm.action == "delete"

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    # first update should not remove the netixlan or IX-F entry
    # since the notification count requirement is not met

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1

    netixlan.refresh_from_db()
    assert netixlan.status == "ok"

    # ixf member data entry should have logged one notification
    # to the network.

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 1
    assert ixm.extra_notifications_net_date is not None

    if not network_o.ipv4_support or not network_o.ipv6_support:
        # this initial ixf import will send two additional emails (one to the net, one to the ix)
        # due to protocol mismatch which we need to account for here - this is due to the test
        # data which is not otherwise relevant to this test, but
        # needs to be there for the IX-F import to be valid
        #
        # then we also expect one re-notificaiton email about the stale network

        assert IXFImportEmail.objects.count() == 3
    else:
        # otherwise expect one re-notification email about the stale network

        assert IXFImportEmail.objects.count() == 1

    # now notification count rquirement is set to the required amount
    # stale netixlan and IX-F entry should be removed

    ixm.extra_notifications_net_num = settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT
    ixm.save()

    # reset emails...
    IXFImportEmail.objects.all().delete()

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert IXFImportEmail.objects.count() == 0

    netixlan.refresh_from_db()
    assert netixlan.status == "deleted"

    # Test idempotent

    importer.update(ixlan, data=data)
    importer.notify_proposals()
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_resolve_local_ixf_stale_netixlan_import_disabled(entities, use_ip, save):
    """
    Netixlan exists, remote data does not match the netixlan, and there is a local-ixf
    entry that also matches all the data.

    The local-ixf entry is past the allowed proposal age, but the exchange has disabled
    the importer, so nothing should happen.
    """
    data = setup_test_data("ixf.member.7")
    network = entities["net"]["UPDATE_DISABLED_2"]
    network_o = entities["net"]["UPDATE_ENABLED"]

    ixlan = entities["ixlan"][0]
    ixlan.ixf_ixp_import_enabled = True

    netixlan = NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=10000,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        status="ok",
        is_rs_peer=True,
        operational=True,
    )

    entities["netixlan"].append(netixlan)

    # Create a local IXF that matches remote details
    ixm = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data="{}",
        extra_notifications_net_num=0,
        extra_notifications_net_date=None,
    )

    assert IXFMemberData.objects.count() == 1

    ixm.created = ixm.created - datetime.timedelta(
        days=settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD + 1
    )
    ixm.save()

    assert ixm.action == "delete"

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    # first update should not remove the netixlan or IX-F entry
    # since the notification count requirement is not met

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1

    netixlan.refresh_from_db()
    assert netixlan.status == "ok"

    # ixf member data entry should have logged one notification
    # to the network.

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 1
    assert ixm.extra_notifications_net_date is not None

    if not network_o.ipv4_support or not network_o.ipv6_support:
        # this initial ixf import will send two additional emails (one to the net, one to the ix)
        # due to protocol mismatch which we need to account for here - this is due to the test
        # data which is not otherwise relevant to this test, but
        # needs to be there for the IX-F import to be valid
        #
        # then we also expect one re-notificaiton email about the stale network

        assert IXFImportEmail.objects.count() == 3
    else:
        # otherwise expect one re-notification email about the stale network

        assert IXFImportEmail.objects.count() == 1

    # now notification count rquirement is set to the required amount
    # however internet exchange has disabled import, so nothing should get deleted

    ixm.extra_notifications_net_num = settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT
    ixm.save()

    # reset emails...
    IXFImportEmail.objects.all().delete()

    # disable ixf import
    ixlan.ixf_ixp_import_enabled = False
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    assert IXFImportEmail.objects.count() == 0

    netixlan.refresh_from_db()
    assert netixlan.status == "ok"

    # Test idempotent

    importer.update(ixlan, data=data)
    importer.notify_proposals()
    assert_idempotent(importer, ixlan, data)


@override_settings(IXF_REMOVE_STALE_NETIXLAN=False)
@pytest.mark.django_db
def test_resolve_local_ixf_stale_netixlan_removal_disabled(entities, save):
    """
    Netixlan exists, remote data does not match the netixlan, and there is a local-ixf
    entry that also matches all the data.

    The local-ixf entry is past the allowed proposal age, but IXF_REMOVE_STALE_NETIXLAN
    is disabled, nothing should be deleted.
    """

    data = setup_test_data("ixf.member.7")
    network = entities["net"]["UPDATE_DISABLED_2"]
    network_o = entities["net"]["UPDATE_ENABLED"]

    ixlan = entities["ixlan"][0]
    ixlan.ixf_ixp_import_enabled = True

    netixlan = NetworkIXLan.objects.create(
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

    entities["netixlan"].append(netixlan)

    # Create a local IXF that matches remote details
    ixm = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",
        ipaddr6="2001:7f8:1::a500:2906:1",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data="{}",
        extra_notifications_net_num=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT,
    )

    assert IXFMemberData.objects.count() == 1

    ixm.created = ixm.created - datetime.timedelta(
        days=settings.IXF_REMOVE_STALE_NETIXLAN_PERIOD + 1
    )
    ixm.save()

    assert ixm.action == "delete"

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    # first update should not remove the netixlan or IX-F entry

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1

    netixlan.refresh_from_db()
    assert netixlan.status == "ok"


@override_settings(
    IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD=10,
    IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT=2,
    IXF_REMOVE_STALE_NETIXLAN=True,
)
@pytest.mark.django_db
def test_resolve_local_ixf_stale_netixlan_renotification(entities, save):
    """
    Netixlan exists, remote data does not match the netixlan, and there is a local-ixf
    entry that also matches all the data.

    Test the re-notification process to the network for its stale netixlan entries.
    """

    data = setup_test_data("ixf.member.7")
    network = entities["net"]["UPDATE_DISABLED_2"]
    ixlan = entities["ixlan"][0]
    ixlan.ixf_ixp_import_enabled = True

    netixlan = NetworkIXLan.objects.create(
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

    entities["netixlan"].append(netixlan)

    # Create a local IXF that matches remote details
    ixm = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",
        ipaddr6="2001:7f8:1::a500:2906:1",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data="{}",
    )

    assert IXFMemberData.objects.count() == 1

    importer = ixf.Importer()

    # first importer run, no re-notification
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 0

    # second importer run, firstre-notification after moving the date back

    ixm.created = ixm.created - datetime.timedelta(
        days=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD + 1
    )
    print("CREATED", ixm.created)
    ixm.save()

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 1

    # third importer run, no re-notification, not enough time has passed
    # between last re-notification and now

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 1

    # fourth importer run, set the notification date back to the past, causing
    # the next notification to be sent

    ixm.extra_notifications_net_date = (
        ixm.extra_notifications_net_date
        - datetime.timedelta(days=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD + 1)
    )
    ixm.save()

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 2

    # fifth importer run, set the notification date back to the past, but
    # since max notification limit has been reached, no notification is sent

    ixm.extra_notifications_net_date = (
        ixm.extra_notifications_net_date
        - datetime.timedelta(days=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD + 1)
    )
    ixm.save()

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 2


@override_settings(
    IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD=10,
    IXF_REMOVE_STALE_NETIXLAN_NOTIFY_COUNT=2,
    IXF_REMOVE_STALE_NETIXLAN=True,
)
@pytest.mark.django_db
def test_resolve_local_ixf_stale_netixlan_renotification_import_disabled(
    entities, save
):
    """
    Netixlan exists, remote data does not match the netixlan, and there is a local-ixf
    entry that also matches all the data.

    Exchange has currently disabled the importer, so no notifications should be sent
    #1360
    """

    data = setup_test_data("ixf.member.7")
    network = entities["net"]["UPDATE_DISABLED_2"]
    ixlan = entities["ixlan"][0]
    ixlan.ixf_ixp_import_enabled = False

    netixlan = NetworkIXLan.objects.create(
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

    entities["netixlan"].append(netixlan)

    # Create a local IXF that matches remote details
    ixm = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.250",
        ipaddr6="2001:7f8:1::a500:2906:1",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data="{}",
    )

    assert IXFMemberData.objects.count() == 1

    importer = ixf.Importer()

    # first importer run, no re-notification
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 0

    # second importer run, first re-notification after moving the date back
    # however import is disabled, so no notification should be sent

    ixm.created = ixm.created - datetime.timedelta(
        days=settings.IXF_REMOVE_STALE_NETIXLAN_NOTIFY_PERIOD + 1
    )
    ixm.save()

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 0

    # third importer run, no re-notification, not enough time has passed
    # between last re-notification and now

    IXFImportEmail.objects.all().delete()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixm.refresh_from_db()
    assert ixm.extra_notifications_net_num == 0


@pytest.mark.django_db
def test_update_data_attributes(entities, use_ip, save):
    """
    The NetIXLan differs from the remote data, but allow_ixp_update is enabled
    so we update automatically.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]
    ix_updated = ixlan.ix.updated

    with reversion.create_revision():
        entities["netixlan"].append(
            NetworkIXLan.objects.create(
                network=network,
                ixlan=ixlan,
                asn=network.asn,
                speed=20000,
                ipaddr4=use_ip(4, "195.69.147.250"),
                ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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

    # assert that the exchange's `updated` field was not
    # altered by the import (#812)
    ixlan.ix.refresh_from_db()
    assert ixlan.ix.updated == ix_updated

    assert IXFMemberData.objects.count() == 0

    if (network.ipv4_support and not use_ip(4)) or (
        network.ipv6_support and not use_ip(6)
    ):
        # test (delete+add) consolidation (#770)

        assert len(importer.log["data"]) == 2
        log_delete = importer.log["data"][0]
        log_add = importer.log["data"][1]
        assert log_delete["action"] == "delete"
        assert log_add["action"] == "add"

    else:
        # test modify
        assert len(importer.log["data"]) == 1
        log = importer.log["data"][0]

        assert log["action"] == "modify"
        assert "operational" in log["reason"]

        # #793 we are currently ignoring is_rs_peer
        # and speed for modifies
        assert "is_rs_peer" not in log["reason"]
        assert "speed" not in log["reason"]

    netixlan = NetworkIXLan.objects.filter(status="ok").first()
    assert netixlan.operational == True

    # #793 we are currently ignoring is_rs_peer
    # and speed for modifies
    assert netixlan.is_rs_peer == False
    assert netixlan.speed == 20000

    # Assert idempotent
    assert_idempotent(importer, ixlan, data)

    # Assert no emails
    assert_no_emails(network, ixlan.ix)

    # test revision user
    version = reversion.models.Version.objects.get_for_object(netixlan)
    assert version.first().revision.user == importer.ticket_user

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    netixlan = NetworkIXLan.objects.filter(status="ok").first()
    assert netixlan.operational == False
    assert netixlan.is_rs_peer == False
    assert netixlan.speed == 20000
    assert netixlan.ipaddr4 == use_ip(4, "195.69.147.250")
    assert netixlan.ipaddr6 == use_ip(6, "2001:7f8:1::a500:2906:1")


@pytest.mark.django_db
def test_update_data_attributes_no_routeserver(entities, save):
    """
    The NetIXLan differs from the remote data, but allow_ixp_update is enabled
    so we update automatically.

    routeserver attribute is missing from remote, we ignore it
    """
    data = setup_test_data("ixf.member.4")
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
                is_rs_peer=True,
                operational=False,
            )
        )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0

    netixlan = entities["netixlan"][-1]
    netixlan.refresh_from_db()
    assert netixlan.is_rs_peer == True


@pytest.mark.django_db
def test_suggest_modify_local_ixf(entities, use_ip, save):
    """
    a) Netixlan is different from remote in terms of speed, operational, and is_rs_peer
    BUT there is already a local-ixf for the update.

    Automatic updates are disabled (so netixlan will not change).
    We do nothing and confirm the local-ixf stays the same.

    b) Netixlan is different from remote in terms of speed, operational, and is_rs_peer
    BUT there is already a local-ixf for the update, however IX-F data suggest
    to add one of the missing ip addresses (eg. signature changed)

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
            ipaddr4=use_ip(4, "195.69.147.250"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
            status="ok",
            is_rs_peer=False,
            operational=False,
        )
    )

    # Matches the json data, doesn't match the existing netixlan.
    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4=use_ip(4, "195.69.147.250"),
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data={"foo": "bar"},
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    for email in IXFImportEmail.objects.all():
        print(email.message)

    if (network.ipv4_support and not network.ipv6_support and not use_ip(4)) or (
        network.ipv6_support and not network.ipv4_support and not use_ip(6)
    ):
        # edge case where network has the one ip set that
        # its not supporting and the other ip nto set at all
        # (see #771 and #770) and the existing suggestion was for
        # a different combination protocols supported and signature
        #
        # this will generate a new proposal notification for the entry
        # and there is nothing we can do about it at this point
        #
        # should only happen very rarely

        email_info = [
            (
                "MODIFY",
                network.asn,
                use_ip(4, "195.69.147.250"),
                use_ip(6, "2001:7f8:1::a500:2906:1"),
            )
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

        assert IXFMemberData.objects.count() == 2
        ixf_member_data_delete = IXFMemberData.objects.all()[0]
        ixf_member_data_modify = IXFMemberData.objects.all()[1]
        assert ixf_member_data_modify.action == "modify"
        assert ixf_member_data_delete.action == "delete"

        assert ixf_member_data_delete.requirement_of == ixf_member_data_modify

    elif (network.ipv4_support and network.ipv6_support and not use_ip(4)) or (
        network.ipv6_support and network.ipv4_support and not use_ip(6)
    ):
        # network supports both protocols, old IX-F data only has one
        # of the ips set, suggest adding the other
        # #770 #771

        email_info = [
            (
                "MODIFY",
                network.asn,
                use_ip(4, "195.69.147.250"),
                use_ip(6, "2001:7f8:1::a500:2906:1"),
            )
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

        assert IXFMemberData.objects.count() == 2
        ixf_member_data_delete = IXFMemberData.objects.all()[0]
        ixf_member_data_modify = IXFMemberData.objects.all()[1]
        assert ixf_member_data_modify.action == "modify"
        assert ixf_member_data_delete.action == "delete"
        assert ixf_member_data_delete.requirement_of == ixf_member_data_modify

    else:
        assert_no_emails(network, ixlan.ix)
        assert IXFMemberData.objects.count() == 1
        assert preexisting_ixfmember_data == IXFMemberData.objects.first()

    # Assert idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_modify(entities, use_ip, save):
    """
    Netixlan is different from remote in terms of speed, operational, and is_rs_peer.
    There is no local-ixf existing.

    We need to send out notifications to net and ix
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
            ipaddr4=use_ip(4, "195.69.147.250"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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

    print(importer.log)

    # Create local ixf
    if (not network.ipv4_support and not use_ip(6)) or (
        not network.ipv6_support and not use_ip(4)
    ):
        # data changes and signature (ip) change with
        # partial ip protocol support
        # #770 and #771

        assert IXFMemberData.objects.count() == 2
    elif (network.ipv4_support and network.ipv6_support) and (
        not use_ip(6) or not use_ip(4)
    ):
        # data changes and signature (ip) change with
        # full ip protocol support
        # #770 and #771

        assert IXFMemberData.objects.count() == 2
    else:
        assert IXFMemberData.objects.count() == 1
    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]
    assert log["action"] == "suggest-modify"

    # NetIXLAN is unchanged
    assert NetworkIXLan.objects.first().speed == 20000
    assert NetworkIXLan.objects.first().is_rs_peer == False
    assert NetworkIXLan.objects.first().operational == False

    # Consolidated email is sent to the Network and the IX
    email_info = [
        (
            "MODIFY",
            network.asn,
            use_ip(4, "195.69.147.250"),
            use_ip(6, "2001:7f8:1::a500:2906:1"),
        )
    ]
    assert_ix_email(ixlan.ix, email_info)
    assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data, save=save)


@pytest.mark.django_db
def test_suggest_modify_no_routeserver(entities, save):
    """
    Netixlan is different from remote in terms of speed, operational, and is_rs_peer.
    There is no local-ixf existing.

    We need to send out notifications to net and ix

    Routerserver attribute missing from remote, we ignore it
    """
    data = setup_test_data("ixf.member.5")
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
            is_rs_peer=True,
            operational=False,
        )
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert NetworkIXLan.objects.last().is_rs_peer == True
    assert IXFMemberData.objects.first().is_rs_peer == None

    # Test idempotent
    assert_idempotent(importer, ixlan, data, save=save)


def assert_data_change_notification(objects):
    """
    asserts that a set of data change notifications has
    been created after automated updates to netixlans (#403)
    """

    qset = DataChangeNotificationQueue.objects

    assert qset.count() == len(objects)

    idx = 0

    dcns = [o for o in qset.all()]

    for ref_tag, action in objects:
        dcn = dcns[idx]

        assert action == dcn.action
        assert ref_tag == dcn.ref_tag

        idx += 1

        assert dcn.version_after
        assert dcn.watched_object.HandleRef.tag == "net"
        assert dcn.source == "ixf"
        assert dcn.object_id

    qset.all().delete()


def assert_no_data_change_notification():
    """
    asserts that no data change notifications have been
    generated (#403)
    """

    assert not DataChangeNotificationQueue.objects.count()


@pytest.mark.django_db
def test_add_netixlan(entities, use_ip, save):
    """
    No NetIXLan exists but remote IXF data has information
    to create one (without conflicts). Updates are enabled
    so we create the NetIXLan.
    """
    data = setup_test_data("ixf.member.0")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    ix_updated = ixlan.ix.updated

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # assert that the exchange's `updated` field was not
    # altered by the import (#812)
    ixlan.ix.refresh_from_db()
    assert ixlan.ix.updated == ix_updated

    log = importer.log["data"][0]
    assert log["action"] == "add"
    assert NetworkIXLan.objects.count() == 1

    assert_data_change_notification([("netixlan", "add")])

    # Test idempotent
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.count() == 1

    assert_no_emails(network, ixlan.ix)
    assert_no_data_change_notification()

    # test rollback
    import_log = IXLanIXFMemberImportLog.objects.first()
    import_log.rollback()
    assert NetworkIXLan.objects.first().status == "deleted"
    assert NetworkIXLan.objects.first().ipaddr4 == None
    assert NetworkIXLan.objects.first().ipaddr6 == None


@pytest.mark.django_db
def test_add_netixlan_no_routeserver(entities, use_ip, save):
    """
    No NetIXLan exists but remote IXF data has information
    to create one (without conflicts). Updates are enabled
    so we create the NetIXLan.

    routeserver attribute isnt present at remote ,we ignore it
    """
    data = setup_test_data("ixf.member.4")
    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert NetworkIXLan.objects.count() == 1
    assert NetworkIXLan.objects.first().is_rs_peer == False

    assert_data_change_notification([("netixlan", "add")])


@pytest.mark.django_db
def test_add_netixlan_conflict_local_ixf(entities, use_ip, save):
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

    if use_ip(4):
        ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv6").first()
        invalid_ip = 4
    else:
        ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv4").first()
        invalid_ip = 6
    ixpfx.ixlan = entities["ixlan"][1]
    ixpfx.save()

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        asn=network.asn,
        # Matches remote-ixf, but conflicts with IXLan
        ipaddr4=use_ip(4, "195.69.147.250"),
        # Matches remote-ixf, but conflicts with IXLan
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data=json.dumps({"foo": "bar"}),
        error=json.dumps(
            {"ipaddr4": ["IPv4 195.69.147.250 does not match any prefix on this ixlan"]}
        ),
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixfmemberdata = IXFMemberData.objects.first()

    for email in IXFImportEmail.objects.all():
        print(email.message)

    if (not network.ipv4_support and invalid_ip == 4) or (
        not network.ipv6_support and invalid_ip == 6
    ):
        # edge case, signature changed, and invalid ip
        # is on unsupported protocol, making the proposal
        # irrelevant

        assert IXFMemberData.objects.count() == 0
        assert_no_emails(network, ixlan.ix)
        assert_idempotent(importer, ixlan, data, save=save)

    elif (network.ipv4_support and not use_ip(4)) or (
        network.ipv6_support and not use_ip(6)
    ):
        # edge case, signature changed, and invalid and
        # conflicting ip changed causing a drop of the original
        # erorring proposal, and a creation of a new one
        # on the next one

        email_info = [
            (
                "CREATE",
                network.asn,
                "195.69.147.250",
                "2001:7f8:1::a500:2906:1",
            )
        ]
        assert_no_emails(network, ixlan.ix)

        assert IXFMemberData.objects.count() == 0
        assert NetworkIXLan.objects.count() == 0

        importer.update(ixlan, data=data)
        importer.notify_proposals()

        assert IXFMemberData.objects.count() == 1
        assert NetworkIXLan.objects.count() == 0

        assert_ix_email(ixlan.ix, email_info)
        assert_no_network_email(network)

        assert_idempotent(importer, ixlan, data, save=save)

    else:
        assert IXFMemberData.objects.count() == 1
        assert NetworkIXLan.objects.count() == 0

        assert_no_emails(network, ixlan.ix)
        assert_idempotent(importer, ixlan, data, save=save)


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

    if network.ipv6_support:
        ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv6").first()
    else:
        ixpfx = entities["ixlan"][0].ixpfx_set.filter(protocol="IPv4").first()

    ixpfx.ixlan = entities["ixlan"][1]
    ixpfx.save()

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    ixfmemberdata = IXFMemberData.objects.first()

    if network.ipv4_support and network.ipv6_support:
        assert IXFMemberData.objects.count() == 1
        email_info = [
            ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")
        ]
        assert_ix_email(ixlan.ix, email_info)
        assert_no_network_email(network)

        assert "does not match any prefix on this ixlan" in ixfmemberdata.error

        # Assert that message to IX also includes the error
        assert (
            "A validation error was raised when the IX-F importer attempted to process this change."
            in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message
        )

    else:
        # invalid ip is on unsupported protocol, so it was ignored
        # #771

        assert IXFMemberData.objects.count() == 0
        assert_no_emails(network, ixlan.ix)

    # Test idempotent
    assert_idempotent(importer, ixlan, data, save=save)


@pytest.mark.django_db
def test_suggest_add_local_ixf(entities, use_ip, save):
    """
    The netixlan described in the remote-ixf doesn't exist,
    but there is a relationship btw the network and ix (ie a different netixlan).
    The network does not have automatic updates.
    There's a local-ixf that matches the remote-ixf so we do nothing.
    """
    data = setup_test_data("ixf.member.3")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]
    ix_updated = ixlan.ix.updated

    # This appears in the remote-ixf data so should not
    # create a IXFMemberData instance

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4=use_ip(4, "195.69.147.251"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:3"),
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        # Matches remote-ixf data
        asn=1001,
        # Matches remote-ixf data
        ipaddr4=use_ip(4, "195.69.147.250"),
        # Matches remote-ixf data
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        data=json.dumps({"foo": "bar"}),
        status="ok",
    )

    importer = ixf.Importer()

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # assert that the exchange's `updated` field was not
    # altered by the import (#812)
    ixlan.ix.refresh_from_db()
    assert ixlan.ix.updated == ix_updated

    if (not network.ipv4_support and use_ip(4) and not use_ip(6)) or (
        not network.ipv6_support and use_ip(6) and not use_ip(4)
    ):
        # edge case, supported protocols changed
        # one of the ips on an unsupported protocol
        # effectively changing the signature, send
        # out create notifications for both

        assert IXFMemberData.objects.count() == 3
        assert NetworkIXLan.objects.count() == 1

        email_info = [
            (
                "CREATE",
                network.asn,
                use_ip(6, "195.69.147.251"),
                use_ip(4, "2001:7f8:1::a500:2906:3"),
            )
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    elif (network.ipv4_support and network.ipv6_support and not use_ip(4)) or (
        network.ipv4_support and network.ipv6_support and not use_ip(6)
    ):
        # edge case, supported protocols changed
        # effectively changing the signature, send
        # out modify to the existing netixlan and re-create
        # for the existing ixfmemberdata

        assert IXFMemberData.objects.count() == 3
        assert NetworkIXLan.objects.count() == 1

        email_info = [
            ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
            (
                "MODIFY",
                network.asn,
                use_ip(4, "195.69.147.251"),
                use_ip(6, "2001:7f8:1::a500:2906:3"),
            ),
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    else:
        assert IXFMemberData.objects.count() == 1
        assert NetworkIXLan.objects.count() == 1

        assert_no_emails(network, ixlan.ix)

    # Test idempotent
    assert_idempotent(importer, ixlan, data, save=save)


@pytest.mark.django_db
def test_suggest_add(entities, use_ip, save):
    """
    The netixlan described in the remote-ixf doesn't exist,
    but there is a relationship btw the network and ix (ie a different netixlan).
    The network does not have automatic updates.
    There isn't a local-ixf that matches the remote-ixf.
    We suggest adding the netixlan, create an admin ticket, and send emails to the
    network and IX.
    """

    data = setup_test_data("ixf.member.3")  # asn1001
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
            ipaddr4=use_ip(4, "195.69.147.251"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:3"),
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

    print(importer.log)

    if (not network.ipv4_support and use_ip(4) and not use_ip(6)) or (
        not network.ipv6_support and use_ip(6) and not use_ip(4)
    ):
        # edge case, supported protocols changed
        # one of the ips on an unsupported protocol
        # effectively changing the signature, send
        # out create with the apprp

        assert IXFMemberData.objects.count() == 3
        assert NetworkIXLan.objects.count() == 1

        email_info = [
            (
                "CREATE",
                network.asn,
                use_ip(6, "195.69.147.250"),
                use_ip(4, "2001:7f8:1::a500:2906:1"),
            )
        ]

        log_250 = importer.log["data"][0]
        log_251 = importer.log["data"][1]

        assert log_250["action"] == "suggest-add"
        assert log_251["action"] == "suggest-modify"

        if use_ip(4):
            assert log_250["peer"]["ipaddr4"] == ""
            assert log_251["peer"]["ipaddr4"] == ""
            assert log_250["peer"]["ipaddr6"] == "2001:7f8:1::a500:2906:1"
            assert log_251["peer"]["ipaddr6"] == "2001:7f8:1::a500:2906:3"
        elif use_ip(6):
            assert log_250["peer"]["ipaddr4"] == "195.69.147.250"
            assert log_251["peer"]["ipaddr4"] == "195.69.147.251"
            assert log_250["peer"]["ipaddr6"] == ""
            assert log_251["peer"]["ipaddr6"] == ""

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    elif (network.ipv4_support and network.ipv6_support and not use_ip(4)) or (
        network.ipv4_support and network.ipv6_support and not use_ip(6)
    ):
        # edge case, supported protocols changed
        # effectively changing the signature, send
        # out modify to the existing netixlan and re-create
        # for the existing ixfmemberdata

        assert IXFMemberData.objects.count() == 3
        assert NetworkIXLan.objects.count() == 1

        email_info = [
            ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
            (
                "MODIFY",
                network.asn,
                use_ip(4, "195.69.147.251"),
                use_ip(6, "2001:7f8:1::a500:2906:3"),
            ),
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    else:
        assert IXFMemberData.objects.count() == 1
        assert NetworkIXLan.objects.count() == 1

        log = importer.log["data"][0]
        assert log["action"] == "suggest-add"

        if network.ipv4_support and network.ipv6_support:
            email_info = [
                ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")
            ]
        elif network.ipv4_support:
            email_info = [("CREATE", network.asn, "195.69.147.250", None)]
        elif network.ipv6_support:
            email_info = [("CREATE", network.asn, None, "2001:7f8:1::a500:2906:1")]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add_delete(entities, use_ip_alt, save):
    """
    Tests suggesting a netixlan create and a deletion
    at the same time while one of the ips is nulled.

    This was observed in issue #832
    """

    data = setup_test_data("ixf.member.3")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
    ixlan = entities["ixlan"][0]

    # remove ip from IX-F data as per use_ip_alt fixture
    if not use_ip_alt(4):
        del data["member_list"][0]["connection_list"][0]["vlan_list"][0]["ipv4"]
    elif not use_ip_alt(6):
        del data["member_list"][0]["connection_list"][0]["vlan_list"][0]["ipv6"]

    # we don't want the extra IX-F entry for this test
    del data["member_list"][0]["connection_list"][1]

    # This appears in the remote-ixf data so should not
    # create a IXFMemberData instance
    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4=use_ip_alt(4, "195.69.147.252"),
            ipaddr6=use_ip_alt(6, "2001:7f8:1::a500:2906:2"),
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

    if (not network.ipv6_support and not use_ip_alt(4)) or (
        not network.ipv4_support and not use_ip_alt(6)
    ):
        # edge case: network not supporting the only provided ip
        # do nothing
        assert IXFMemberData.objects.all().count() == 0

        assert_no_emails(network, ixlan.ix)

    else:
        assert IXFMemberData.objects.all().count() == 2

        email_info = [
            (
                "REMOVE",
                network.asn,
                use_ip_alt(4, "195.69.147.252"),
                use_ip_alt(6, "2001:7f8:1::a500:2906:2"),
            ),
            (
                "CREATE",
                network.asn,
                use_ip_alt(4, "195.69.147.250"),
                use_ip_alt(6, "2001:7f8:1::a500:2906:1"),
            ),
        ]

        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

        assert (
            IXFMemberData.objects.get(
                ipaddr4=use_ip_alt(4, "195.69.147.252"),
                ipaddr6=use_ip_alt(6, "2001:7f8:1::a500:2906:2"),
            ).action
            == "delete"
        )

        assert (
            IXFMemberData.objects.get(
                ipaddr4=use_ip_alt(4, "195.69.147.250"),
                ipaddr6=use_ip_alt(6, "2001:7f8:1::a500:2906:1"),
            ).action
            == "add"
        )

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add_no_netixlan_local_ixf(entities, use_ip, save):
    """
    There isn't any netixlan between ix and network.
    Network does not have automatic updates.
    There is a local-ixf that matches the remote-ixf so we do nothing
    """
    data = setup_test_data("ixf.member.1")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
    ixlan = entities["ixlan"][0]

    preexisting_ixfmember_data = IXFMemberData.objects.create(
        # Matches remote-ixf data
        asn=1001,
        # Matches remote-ixf data
        ipaddr4=use_ip(4, "195.69.147.250"),
        # Matches remote-ixf data
        ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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

    if (not network.ipv4_support and use_ip(4) and not use_ip(6)) or (
        not network.ipv6_support and use_ip(6) and not use_ip(4)
    ):
        # edge case where the network has only one ip
        # set and its on an unsupported protocol
        # we re-create the ixfmemberdata and re notify the
        # network

        email_info = [
            (
                "CREATE",
                network.asn,
                use_ip(6, "195.69.147.250"),
                use_ip(4, "2001:7f8:1::a500:2906:1"),
            )
        ]

        assert_network_email(network, email_info)

    elif (network.ipv4_support and network.ipv6_support and not use_ip(4)) or (
        network.ipv4_support and network.ipv6_support and not use_ip(6)
    ):
        # edge case, supported protocols changed
        # effectively changing the signature, send
        # we re-create the ixfmemberdata and re notify the
        # network

        email_info = [
            ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
        ]

        assert_network_email(network, email_info)

    else:
        assert_no_emails(network, ixlan.ix)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_suggest_add_no_netixlan(entities, use_ip, save):
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

    if network.ipv4_support and network.ipv6_support:
        email_info = [
            ("CREATE", network.asn, "195.69.147.250", "2001:7f8:1::a500:2906:1")
        ]
    elif network.ipv4_support:
        email_info = [("CREATE", network.asn, "195.69.147.250", None)]
    elif network.ipv6_support:
        email_info = [("CREATE", network.asn, None, "2001:7f8:1::a500:2906:1")]

    assert_network_email(network, email_info)

    if network.ipv4_support and network.ipv6_support:
        assert_no_ix_email(ixlan.ix)
    else:
        assert_protocol_conflict_email(network, ix=ixlan.ix)

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

    if not network.ipv4_support or not network.ipv6_support:
        # edge case
        #
        # one protocol is turned off, in this case we actually
        # delete the  netixlan on the unsupported protocol and keep
        # and keep the one on the supported protocol (since we
        # cant update it with the unsupported ip either)

        assert len(importer.log["data"]) == 1
        assert importer.log["data"][0]["action"] == "delete"

        assert_data_change_notification([("netixlan", "delete")])
    else:
        assert len(importer.log["data"]) == 3

        assert NetworkIXLan.objects.filter(status="ok").count() == 1

        assert importer.log["data"][0]["action"] == "delete"
        assert importer.log["data"][1]["action"] == "delete"
        assert importer.log["data"][2]["action"] == "add"

        assert_data_change_notification(
            [("netixlan", "delete"), ("netixlan", "delete"), ("netixlan", "add")]
        )

    assert_no_emails(network, ixlan.ix)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_single_ipaddr_matches_no_auto_update(entities, use_ip, save):
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
            ipaddr4=use_ip(4, "195.69.147.250"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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

    if use_ip(4) and use_ip(6):
        assert_no_emails(network, ixlan.ix)
        assert IXFMemberData.objects.count() == 0
        assert NetworkIXLan.objects.count() == 1

    elif (
        (not network.ipv6_support or not network.ipv4_support)
        and not (network.ipv4_support and use_ip(6) and not use_ip(4))
        and not (network.ipv6_support and use_ip(4) and not use_ip(6))
    ):
        assert len(importer.log["data"]) == 0
        assert_no_emails(network, ixlan.ix)

    else:
        # Assert NetworkIXLan is unchanged
        assert NetworkIXLan.objects.filter(status="ok").count() == 1

        # We consolidate notifications into a single MODIFY
        assert len(importer.log["data"]) == 1
        assert importer.log["data"][0]["action"] == "suggest-modify"

        ixf_member_del = IXFMemberData.objects.filter(
            requirement_of__isnull=False
        ).first()
        ixf_member_add = IXFMemberData.objects.filter(
            requirement_of__isnull=True
        ).first()

        assert ixf_member_del.requirement_of == ixf_member_add
        assert ixf_member_add.action == "modify"

        netixlan = NetworkIXLan.objects.filter(status="ok").first()

        email_info = [("MODIFY", network.asn, netixlan.ipaddr4, netixlan.ipaddr6)]
        assert_ix_email(ixlan.ix, email_info)
        assert_network_email(network, email_info)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_816_edge_case(entities, use_ip, save):
    """
    Test that #770 protocol only triggers when the
    depending deletion is towards the same asn AND
    not already handled (dependency == noop)
    """

    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED_2"]
    ixlan = entities["ixlan"][0]

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4=use_ip(4, "195.69.147.250"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:1"),
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

    assert IXFMemberData.objects.count() == 2
    assert IXFMemberData.objects.get(asn=1001).action == "add"

    assert IXFImportEmail.objects.filter(
        net__asn=1001, message__contains="CREATE"
    ).exists()
    assert not IXFImportEmail.objects.filter(
        net__asn=1001, message__contains="MODIFY"
    ).exists()

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

    if not network.ipv4_support or not network.ipv6_support:
        # only one of the protocols is supported by the network
        # suggest deletion of the other ip address

        assert IXFMemberData.objects.count() == 1

        assert importer.log["data"][0]["action"] == "suggest-delete"

        if not network.ipv4_support:
            ipaddr4 = "195.69.147.250"
        else:
            ipaddr4 = None

        if not network.ipv6_support:
            ipaddr6 = "2001:7f8:1::a500:2906:1"
        else:
            ipaddr6 = None

        email_info = [("REMOVE", network.asn, ipaddr4, ipaddr6)]

        assert_network_email(network, email_info)
        assert_ix_email(ixlan.ix, email_info)

    else:
        # On the IXFMemberData side, we create instances
        # for two deletions and one addition.
        # The deletions will be the requirement of the addition.

        assert IXFMemberData.objects.count() == 3
        ixfmdata_d4 = IXFMemberData.objects.filter(
            ipaddr4="195.69.147.250", ipaddr6=None
        ).first()
        ixfmdata_d6 = IXFMemberData.objects.filter(
            ipaddr4=None, ipaddr6="2001:7f8:1::a500:2906:1"
        ).first()
        ixfmdata_m = IXFMemberData.objects.filter(
            ipaddr4="195.69.147.250", ipaddr6="2001:7f8:1::a500:2906:1"
        ).first()

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
    ix_updated = ixlan.ix.updated

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

    # assert that the exchange's `updated` field was not
    # altered by the import (#812)
    ixlan.ix.refresh_from_db()
    assert ixlan.ix.updated == ix_updated

    assert len(importer.log["data"]) == 1
    log = importer.log["data"][0]

    assert log["action"] == "delete"
    assert NetworkIXLan.objects.filter(status="ok").count() == 1
    assert_data_change_notification([("netixlan", "delete")])
    assert_no_emails(network, ixlan.ix)

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

    assert_no_emails(network, ixlan.ix)

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
            is_rs_peer=False,
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
        error=json.dumps({"speed": "Invalid speed value: this is not valid"}),
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
        error=json.dumps({"speed": "Invalid speed value: this is not valid"}),
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # #793 count should be 2 if we were not ignoring changes
    # to is_rs_peer and speed, but because we currently are
    # one of the pre-existing ixfmemberdata entries gets resolved
    assert IXFMemberData.objects.count() == 1

    assert_no_emails(network, ixlan.ix)

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
            is_rs_peer=False,
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
    assert IXFMemberData.objects.count() == 1

    # We email to say there is invalid data
    if network.ipv4_support and network.ipv6_support:
        email_info = [
            ("CREATE", network.asn, "195.69.147.100", "2001:7f8:1::a500:2906:4"),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]
    elif network.ipv4_support:
        email_info = [
            ("CREATE", network.asn, "195.69.147.100", None),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]
    elif network.ipv6_support:
        email_info = [
            ("CREATE", network.asn, None, "2001:7f8:1::a500:2906:4"),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]

    assert_ix_email(ixlan.ix, email_info)
    assert (
        "Invalid speed value: This is invalid"
        in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message
    )

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

    # this will get resolved since invalid speed means no changes
    # to the existing netixlan, thus it becomes noop (#792)

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
        error=json.dumps({"speed": "Invalid speed value: this is not valid"}),
    )

    # this suggests adding a new netixlan, and will be made
    # but with an error note attached that the speed could
    # not be parsed (#792)

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
        error=json.dumps({"speed": "Invalid speed value: this is not valid"}),
    )

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # for email in IXFImportEmail.objects.all():
    #   print(email.message)

    for ixf_member in IXFMemberData.objects.all():
        print(ixf_member, ixf_member.id)

    assert IXFMemberData.objects.count() == 1
    assert_no_emails(network, ixlan.ix)

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

    data = setup_test_data("ixf.member.invalid.2")
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

    assert IXFMemberData.objects.count() == 1

    # We send an email about the updates
    # But it also contains information about the invalid speed
    if network.ipv4_support and network.ipv6_support:
        email_info = [
            ("CREATE", network.asn, "195.69.147.100", "2001:7f8:1::a500:2906:4"),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]
    elif network.ipv4_support:
        email_info = [
            ("CREATE", network.asn, "195.69.147.100", None),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]
    elif network.ipv6_support:
        email_info = [
            ("CREATE", network.asn, None, "2001:7f8:1::a500:2906:4"),
            # #793 no modifies to speed or is_rs_peer for now
            # ("MODIFY", network.asn, "195.69.147.200", "2001:7f8:1::a500:2906:2"),
        ]

    assert_ix_email(ixlan.ix, email_info)

    assert (
        "Invalid speed value: This is invalid" in IXFImportEmail.objects.first().message
    )
    assert_no_network_email(network)

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


# The following test no longer would cause an error because of
# issue 882.

# @pytest.mark.django_db
# def test_remote_cannot_be_parsed(entities, save):
#     """
#     Remote cannot be parsed. We create a ticket, email the IX, and create a lock.
#     """
#     data = setup_test_data("ixf.member.unparsable")
#     ixlan = entities["ixlan"][0]
#     start = datetime.datetime.now(datetime.timezone.utc)
#     importer = ixf.Importer()
#     importer.sanitize(data)

#     if not save:
#         return assert_idempotent(importer, ixlan, data, save=False)

#     importer.update(ixlan, data=data)
#     importer.notify_proposals()

#     ERROR_MESSAGE = "No entries in any of the vlan_list lists, aborting"
#     assert importer.ixlan.ixf_ixp_import_error_notified > start  # This sets the lock
#     assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
#     assert (
#         ERROR_MESSAGE in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message
#     )

#     # Assert idempotent / lock
#     importer.sanitize(data)
#     importer.update(ixlan, data=data)

#     assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
#     assert IXFImportEmail.objects.filter(ix=ixlan.ix.id).count() == 1


@pytest.mark.django_db
def test_notify_duplicate_ip(entities, save):
    data = setup_test_data("ixf.member.dupe.ip")
    ixlan = entities["ixlan"][0]
    start = datetime.datetime.now(datetime.timezone.utc)

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    assert importer.update(ixlan, data=data) == False
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert IXFImportEmail.objects.count() == 1
    ERROR_MESSAGE = data.get("pdb_error")
    assert "assigned to more than one distinct connection" in ERROR_MESSAGE
    assert importer.ixlan.ixf_ixp_import_error_notified > start
    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
    assert (
        ERROR_MESSAGE in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message
    )

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_mark_invalid_multiple_vlans(entities, save):
    """
    The IX-F data contains multiple vlans for prefixes specified
    on our ixlan

    The import should fail and dispatch a notification to the ix
    """

    data = setup_test_data("ixf.member.invalid.vlan")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]
    start = datetime.datetime.now(datetime.timezone.utc)

    importer = ixf.Importer()
    data = importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    assert importer.update(ixlan, data=data) == False
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 0
    assert IXFImportEmail.objects.filter(ix=ixlan.ix.id).count() == 1
    ERROR_MESSAGE = "We found that your IX-F output contained multiple VLANs"
    assert importer.ixlan.ixf_ixp_import_error_notified > start  # This sets the lock
    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error
    assert (
        ERROR_MESSAGE in IXFImportEmail.objects.filter(ix=ixlan.ix.id).first().message
    )

    # Assert idempotent / lock
    importer.update(ixlan, data=data)

    assert ERROR_MESSAGE in importer.ixlan.ixf_ixp_import_error

    for email in IXFImportEmail.objects.filter(ix=ixlan.ix.id):
        print(email.message)

    assert IXFImportEmail.objects.filter(ix=ixlan.ix.id).count() == 1

    # Test idempotent
    assert_idempotent(importer, ixlan, data)


@pytest.mark.django_db
def test_vlan_null_ips(entities, save):
    """
    The IX-F data contains a vlan that has null values for ipv4 and ipv6
    Importer should treat them the same as if they werent set at all (#1244)
    """

    data = setup_test_data("ixf.member.null.ip.vlan")
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()
    importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)

    # Assert idempotent / lock
    importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)


@pytest.mark.django_db
def test_vlan_null_vlan_list_and_if_list(entities, save):
    """
    The IX-F data contains a vlan_list and if_list as null
    Importer should treat them the same as if they werent set at all (#1244)
    """

    data = setup_test_data("ixf.member.null.vlan_list_and_if_list")
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()
    importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)

    # Assert idempotent / lock
    importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)


@pytest.mark.django_db
def test_vlan_list_empty(entities, save):
    """
    VLAN list is empty. Per issue 882, this shouldn't raise any errors.
    """
    data = setup_test_data("ixf.member.vlan_list_empty")
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()
    importer.sanitize(data)

    if not save:
        return assert_idempotent(importer, ixlan, data, save=False)

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)

    # Assert idempotent / lock
    importer.sanitize(data)
    importer.update(ixlan, data=data)

    assert importer.ixlan.ixf_ixp_import_error_notified is None
    assert importer.ixlan.ixf_ixp_import_error is None
    assert_no_emails(ix=ixlan.ix)


@pytest.mark.django_db
def test_validate_json_schema():
    schema_url_base = "https://raw.githubusercontent.com/euro-ix/json-schemas/master/versions/ixp-member-list-{}.schema.json"

    for v in ["0.4", "0.5", "0.6", "0.7", "1.0"]:
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


@pytest.mark.django_db
def test_create_deskpro_tickets_after_x_days(entities):
    data = setup_test_data("ixf.member.2")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # disable while #793 is active
    """
    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4="195.69.147.252",
            ipaddr6="2001:7f8:1::a500:2906:2",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )
    """

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4="195.69.147.240",
            ipaddr6="2001:7f8:1::a500:2905:1",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )
    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    for ixfmd in IXFMemberData.objects.all():
        # Edit so that they've been created two weeks ago
        ixfmd.created = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(days=14)
        ixfmd.save()
        print(ixfmd.ixf_id, ixfmd.action)

    importer.update(ixlan, data=data)

    # Assert IXFMemberData still the same
    assert IXFMemberData.objects.count() == 4

    """
    # Assert DeskProTickets are created
    assert DeskProTicket.objects.count() == 4

    # Assert emails go to IX and Network for each Ticket
    deskpro_refs = [dpt.deskpro_ref for dpt in DeskProTicket.objects.all()]
    for dpt in deskpro_refs:
        assert IXFImportEmail.objects.filter(
            subject__contains=dpt, ix=ixlan.ix.id
        ).exists()
        assert IXFImportEmail.objects.filter(
            subject__contains=dpt, net=network.id
        ).exists()
    """

    # Per issue #860, we no longer create the DeskProTickets
    # after x days
    assert DeskProTicket.objects.count() == 0


@pytest.mark.django_db
def test_create_deskpro_tickets_no_contacts(entities):
    """
    For issue 883, we want to test that two consolidated emails
    are sent if we have two networks missing contacts.
    """
    data = setup_test_data("ixf.member.6")
    network = entities["net"]["UPDATE_DISABLED"]
    network2 = entities["net"]["UPDATE_DISABLED_2"]
    ixlan = entities["ixlan"][0]

    # Delete contacts
    for netcontact in entities["netcontact"]:
        netcontact.delete()

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4="195.69.147.251",
            ipaddr6="2001:7f8:1::a500:2906:2",
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
            ipaddr4="195.69.147.240",
            ipaddr6="2001:7f8:1::a500:2905:1",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )
    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network2,
            ixlan=ixlan,
            asn=network2.asn,
            speed=10000,
            ipaddr4="195.69.147.239",
            ipaddr6="2001:7f8:1::a500:2100:1",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Issue 883: Assert a single consolidated ticket is created
    assert DeskProTicket.objects.count() == 2
    for ticket in DeskProTicket.objects.all():
        assert ticket.cc_set.count() == 0

    assert DeskProTicket.objects.filter(subject__contains=str(network.asn)).exists()
    assert DeskProTicket.objects.filter(subject__contains=str(network2.asn)).exists()


@pytest.mark.django_db
def test_email_with_partial_contacts(entities):
    data = setup_test_data("ixf.member.2")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # Delete network contact but keep ix contact
    for netcontact in entities["netcontact"]:
        netcontact.delete()

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4="195.69.147.251",
            ipaddr6="2001:7f8:1::a500:2906:2",
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
            ipaddr4="195.69.147.240",
            ipaddr6="2001:7f8:1::a500:2905:1",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )
    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Issue 883: Assert a single consolidated ticket is created
    assert DeskProTicket.objects.count() == 1
    for ticket in DeskProTicket.objects.all():
        assert ticket.cc_set.count() == 0


@pytest.mark.django_db
def test_no_email_if_deskpro_fails(entities, use_ip, save):
    """
    Test setup based on test_create_deskpro_tickets_no_contacts.

    For issue #850, we would like to test that if the DeskPRO ticket creation
    fails, we aren't sending out individual conflict resolution emails.
    """

    data = setup_test_data("ixf.member.2")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    # Delete network contacts
    for netcontact in entities["netcontact"]:
        netcontact.delete()

    # Keep IX contacts. Ordinarily this would trigger an email to the IX
    # However since the deskPRO API response will fail,
    # no emails should get sent.

    entities["netixlan"].append(
        NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4="195.69.147.251",
            ipaddr6="2001:7f8:1::a500:2906:2",
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
            ipaddr4="195.69.147.240",
            ipaddr6="2001:7f8:1::a500:2905:1",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )
    importer = ixf.Importer()
    importer._deskpro_client = FailingMockAPIClient

    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Issue 883: Assert a single consolidated ticket is created
    assert DeskProTicket.objects.count() == 1
    for ticket in DeskProTicket.objects.all():
        assert ticket.cc_set.count() == 0

    # This is the single consolidated email
    assert IXFImportEmail.objects.count() == 1


@pytest.mark.django_db
def test_resolve_deskpro_ticket(entities):
    data = setup_test_data("ixf.member.1")
    network = entities["net"]["UPDATE_DISABLED"]
    ixlan = entities["ixlan"][0]

    importer = ixf.Importer()
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    assert IXFMemberData.objects.count() == 1
    ixf_member_data = IXFMemberData.objects.first()

    assert not ixf_member_data.deskpro_id
    assert not ixf_member_data.deskpro_ref

    # Edit so that they've been created two weeks ago
    ixf_member_data.created = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=14)
    ixf_member_data.save_without_update()

    # re run importer to create tickets
    importer.notifications = []
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # Per issue #860 we no longer create tickets for conflict resolution
    # just based on age
    assert DeskProTicket.objects.count() == 0

    # Commented out bc of issue #860
    """
    ticket = DeskProTicket.objects.first()
    assert ticket.deskpro_id
    assert ticket.deskpro_ref

    # 1 member data instance
    assert IXFMemberData.objects.count() == 1
    ixf_member_data = IXFMemberData.objects.first()
    assert ixf_member_data.deskpro_id == ticket.deskpro_id
    assert ixf_member_data.deskpro_ref == ticket.deskpro_ref

    # 4 emails total
    # 2 emails for initial consolidated notification
    # 2 emails for ticket
    if network.ipv4_support and network.ipv6_support:
        assert IXFImportEmail.objects.count() == 3
    else:
        assert IXFImportEmail.objects.count() == 4
    conflict_emails = IXFImportEmail.objects.filter(subject__icontains="conflict")
    assert conflict_emails.count() == 2
    """

    consolid_emails = IXFImportEmail.objects.exclude(subject__icontains="conflict")
    for email in consolid_emails:
        # if network is only supporting one ip protocol
        # since the ix is sending both it should be mentioned
        if not network.ipv4_support:
            assert "IX-F data provides IPv4 addresses" in email.message
        if not network.ipv6_support:
            assert "IX-F data provides IPv6 addresses" in email.message

    # for email in conflict_emails:
    #     assert ticket.deskpro_ref in email.subject

    # Resolve issue
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

    # Re run import to notify resolution
    importer.notifications = []
    importer.update(ixlan, data=data)
    importer.notify_proposals()

    # resolved
    assert IXFMemberData.objects.count() == 0

    # Commented out bc of issue #860
    """
    # assert DeskProTicket.objects.count() == 2

    ticket_r = DeskProTicket.objects.last()
    assert ticket_r.deskpro_id == ticket.deskpro_id
    assert ticket_r.deskpro_ref == ticket.deskpro_ref
    assert "resolved" in ticket_r.body


    conflict_emails = IXFImportEmail.objects.filter(subject__icontains="conflict")
    assert conflict_emails.count() == 4

    for email in conflict_emails.order_by("-id")[:2]:
        assert "resolved" in email.message
        assert ticket.deskpro_ref in email.subject
    """


@pytest.mark.django_db
def test_vlan_sanitize(data_ixf_vlan):
    """
    test that various vlan_list setups are sanitized correctly
    """
    importer = ixf.Importer()
    sanitized = importer.sanitize_vlans(json.loads(data_ixf_vlan.input)["vlan_list"])
    assert sanitized == data_ixf_vlan.expected["vlan_list"]


@pytest.mark.django_db
def test_chained_consolidate_add_del(entities):
    """
    Tests the edge cause of a consolidated-add-del operation
    being the requirement of a new consolidated-add-del operation
    which would cause the bug described in #889
    """

    data = setup_test_data("ixf.member.3")  # asn1001
    network = entities["net"]["UPDATE_DISABLED"]  # asn1001
    ixlan = entities["ixlan"][0]

    if not network.ipv4_support or not network.ipv6_support:
        return

    # create netixlan that will be suggested to be deleted
    # as part of consolidate-add-del operation

    NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=10000,
        ipaddr4="195.69.147.251",
        ipaddr6=None,
        status="ok",
        is_rs_peer=True,
        operational=True,
    )

    # create consolidated add suggestion for netixlan above

    ixf_member_data_field = {
        "ixp_id": 42,
        "state": "connected",
        "if_list": [{"switch_id": 1, "if_speed": 20000, "if_type": "LR4"}],
        "vlan_list": [
            {
                "vlan_id": 0,
                "ipv4": {
                    "address": "195.69.147.251",
                    "routeserver": True,
                    "as_macro": "AS-NFLX-V4",
                },
                "ipv6": {
                    "address": "2001:7f8:1::a500:2906:2",
                    "routeserver": True,
                    "as_macro": "AS-NFLX-V6",
                },
            }
        ],
    }

    ixf_member_add = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.251",
        ipaddr6="2001:7f8:1::a500:2906:2",
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
        data=json.dumps(ixf_member_data_field),
    )

    # create consolidated delete suggestion for netixlan above

    ixf_member_del = IXFMemberData.objects.create(
        asn=network.asn,
        ipaddr4="195.69.147.251",
        ipaddr6=None,
        ixlan=ixlan,
        speed=10000,
        fetched=datetime.datetime.now(datetime.timezone.utc),
        operational=True,
        is_rs_peer=True,
        status="ok",
    )

    ixf_member_add.set_requirement(ixf_member_del)

    assert ixf_member_add.action == "modify"
    assert ixf_member_add.primary_requirement == ixf_member_del

    # now run the import that will trigger a third consolidated-add-del
    # operation with the requirment of ixf_member_add as a deletion
    # causing a chain of requirements (#889)

    importer = ixf.Importer()
    importer.update(ixlan, data=data)


@override_settings(MAIL_DEBUG=False)
@pytest.mark.django_db
def test_send_email(entities, use_ip):
    # Setup is from test_suggest_add()
    print(f"Debug mode for mail: {settings.MAIL_DEBUG}")
    data = setup_test_data("ixf.member.3")  # asn1001
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
            ipaddr4=use_ip(4, "195.69.147.251"),
            ipaddr6=use_ip(6, "2001:7f8:1::a500:2906:3"),
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
    )

    importer = ixf.Importer()
    importer.update(ixlan, data=data)

    # This should actually send an email
    importer.notify_proposals()
    assert importer.emails == 2


@pytest.mark.django_db
def test_ixlan_add_netixlan_no_redundant_save_on_null_ip(entities):
    """
    Tests that if ixlan.add_netixlan receives a netixlan which
    has either ipaddr4 or ipaddr6 nulled will not cause redundant
    saves to already deleted netixlans that also have that same field
    nulled (#1019)
    """

    network = entities["net"]["UPDATE_ENABLED"]
    ixlan = entities["ixlan"][0]

    # create deleted netixlans

    with reversion.create_revision():
        NetworkIXLan.objects.create(
            ixlan=ixlan,
            network=network,
            asn=network.asn + 1,
            ipaddr4="195.69.147.253",
            ipaddr6="2001:7f8:1::a500:2906:10",
            speed=1000,
            status="deleted",
        )

        NetworkIXLan.objects.create(
            ixlan=ixlan,
            network=network,
            asn=network.asn + 1,
            ipaddr4="195.69.147.252",
            ipaddr6="2001:7f8:1::a500:2906:11",
            speed=1000,
            status="deleted",
        )

        netixlan6 = NetworkIXLan.objects.create(
            ixlan=ixlan,
            network=network,
            asn=network.asn + 1,
            ipaddr4=None,
            ipaddr6="2001:7f8:1::a500:2906:9",
            speed=1000,
            status="deleted",
        )

        netixlan4 = NetworkIXLan.objects.create(
            ixlan=ixlan,
            network=network,
            asn=network.asn + 1,
            ipaddr4="195.69.147.251",
            ipaddr6=None,
            speed=1000,
            status="deleted",
        )

    netixlan4.refresh_from_db()
    netixlan6.refresh_from_db()

    assert netixlan4.version == 1
    assert netixlan6.version == 1

    # create netixlans

    netixlan6_new = NetworkIXLan(
        ixlan=ixlan,
        network=network,
        asn=network.asn,
        ipaddr4=None,
        ipaddr6="2001:7f8:1::a500:2906:10",
        speed=1000,
        status="deleted",
    )

    netixlan4_new = NetworkIXLan(
        ixlan=ixlan,
        network=network,
        asn=network.asn,
        ipaddr4="195.69.147.252",
        ipaddr6=None,
        speed=1000,
        status="deleted",
    )

    with reversion.create_revision():
        netixlan6_new = ixlan.add_netixlan(netixlan6_new)
        netixlan4_new = ixlan.add_netixlan(netixlan4_new)

    netixlan4.refresh_from_db()
    netixlan6.refresh_from_db()

    # No further saves should have happened to the already
    # deleted netixlans

    assert not netixlan4.notes
    assert not netixlan6.notes

    assert netixlan4.version == 1
    assert netixlan6.version == 1


# FIXTURES
@pytest.fixture(params=[True, False])
def save(request):
    return request.param


def entities_ipv4_only(_entities):
    """
    Same as entities, but network gets configured
    to only support IPv4
    """
    for net in _entities["net"].values():
        net.info_ipv6 = False
        net.info_unicast = True
        net.save()
    return _entities


def entities_ipv6_only(_entities):
    """
    Same as entities, but network gets configured
    to only support IPv6
    """
    for net in _entities["net"].values():
        net.info_unicast = False
        net.info_ipv6 = True
        net.save()
    return _entities


def entities_ipv4_ipv6_implied(_entities):
    """
    Same as entities, but network gets configured
    to imply support for both protocols by having
    neither set.
    """
    for net in _entities["net"].values():
        net.info_unicast = False
        net.info_ipv6 = False
        net.save()
    return _entities


def entities_ipv4_ipv6(_entities):
    for net in _entities["net"].values():
        net.info_unicast = True
        net.info_ipv6 = True
        net.save()
    return _entities


def entities_base():
    entities = {}
    with reversion.create_revision():
        entities["org"] = [Organization.objects.create(name="Netflix", status="ok")]

        # create exchange(s)
        entities["ix"] = [
            InternetExchange.objects.create(
                name="Test Exchange One",
                org=entities["org"][0],
                status="ok",
                tech_email="ix1@localhost",
            ),
            InternetExchange.objects.create(
                name="Test Exchange Two",
                org=entities["org"][0],
                status="ok",
                tech_email="ix2@localhost",
            ),
        ]

        # create ixlan(s)
        entities["ixlan"] = [ix.ixlan for ix in entities["ix"]]

        for ixlan in entities["ixlan"]:
            ixlan.ixf_ixp_import_enabled = True
            ixlan.ixf_ixp_member_list_url = "https://localhost/IX-F"
            ixlan.save()

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
                info_ipv6=True,
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
                info_ipv6=True,
            ),
            "UPDATE_DISABLED_2": Network.objects.create(
                name="Network w allow ixp update disabled (2)",
                org=entities["org"][0],
                asn=1101,
                allow_ixp_update=False,
                status="ok",
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://netflix.com/",
                policy_general="Open",
                policy_url="https://www.netflix.com/openconnect/",
                info_unicast=True,
                info_ipv6=True,
            ),
        }

        entities["netcontact"] = [
            NetworkContact.objects.create(
                email="network1@localhost",
                network=entities["net"]["UPDATE_ENABLED"],
                status="ok",
                role="Policy",
            ),
            NetworkContact.objects.create(
                email="network2@localhost",
                network=entities["net"]["UPDATE_DISABLED"],
                status="ok",
                role="Policy",
            ),
            NetworkContact.objects.create(
                email="network3@localhost",
                network=entities["net"]["UPDATE_DISABLED_2"],
                status="ok",
                role="Policy",
            ),
        ]
        entities["netixlan"] = []
        admin_user = User.objects.create_user("admin", "admin@localhost", "admin")
        ixf_importer_user = User.objects.create_user(
            "ixf_importer", "ixf_importer@localhost", "ixf_importer"
        )
        entities["org"][0].admin_usergroup.user_set.add(admin_user)

        # watch a network for automated changes so data change notifications (#403)
        # can be tested
        DataChangeWatchedObject.objects.create(
            ref_tag="net",
            user=admin_user,
            object_id=entities["net"]["UPDATE_ENABLED"].id,
        )

    return entities


@pytest.fixture(
    params=[
        entities_ipv4_ipv6,
        entities_ipv4_ipv6_implied,
        entities_ipv4_only,
        entities_ipv6_only,
    ]
)
def entities(request):
    _entities = entities_base()
    _func = request.param
    return _func(_entities)


class UseIPAddrWrapper:
    """
    To help test what happens when a network only
    sets either ip4 or ip6 address on their netixlan
    as well as both
    """

    def __init__(self, use_ipv4, use_ipv6):
        self.use_ipv4 = use_ipv4
        self.use_ipv6 = use_ipv6

    def __call__(self, ipv, value=True):
        if ipv == 4:
            if self.use_ipv4:
                return ipaddress.ip_address(value)
            return None
        elif ipv == 6:
            if self.use_ipv6:
                return ipaddress.ip_address(value)
            return None
        raise ValueError(ipv)


@pytest.fixture(params=[(True, True), (True, False), (False, True)])
def use_ip(request):
    """
    Fixture that gives back 3 instances of UseIpAddrWrapper

    1) use ip4, use ip6
    2) use ip4, dont use ip6
    3) dont use ip4, use ip6
    """

    use_ipv4, use_ipv6 = request.param

    return UseIPAddrWrapper(use_ipv4, use_ipv6)


@pytest.fixture(params=[(True, False), (False, True)])
def use_ip_alt(request):
    """
    Fixture that gives back 2 instances of UseIpAddrWrapper

    1) use ip4, dont use ip6
    2) dont use ip4, use ip6
    """

    use_ipv4, use_ipv6 = request.param

    return UseIPAddrWrapper(use_ipv4, use_ipv6)


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
    email = list(email)

    if not email[2]:
        email[2] = "IPv4 not set"
    if not email[3]:
        email[3] = "IPv6 not set"

    return "{} AS{} - {} - {}".format(*email)


def assert_no_ticket_exists():
    assert DeskProTicket.objects.count() == 0


def assert_no_emails(network=None, ix=None):
    if network and (not network.ipv4_support or not network.ipv6_support):
        assert_protocol_conflict_email(network, ix=ix, network=network)
    else:
        assert IXFImportEmail.objects.count() == 0


def assert_no_ix_email(ix):
    assert IXFImportEmail.objects.filter(ix=ix.id).count() == 0


def assert_protocol_conflict_email(protocols, ix=None, network=None, solo=True):
    """
    Here we assert that protocol conflict notifications go out

    protocols should be the network instance that defines the protocol
    support

    if ix is set we assert the notification exists for the ix
    if network is set we assert the notification exists for the network
    if solo is True we assert that this is the only notification that exists
    """

    if not protocols.ipv4_support:
        unsupported = 4
    elif not protocols.ipv6_support:
        unsupported = 6
    else:
        raise Exception("Both protocols appear supported")

    search = f"data provides IPv{unsupported} addresses for some "

    if network:
        qset = IXFImportEmail.objects.filter(net=network)
        if solo:
            assert qset.count() == 1
            assert qset.filter(message__contains=search).count() == 1
            assert not qset.filter(message__contains="CREATE").exists()
            assert not qset.filter(message__contains="MODIFY").exists()
            assert not qset.filter(message__contains="REMOVE").exists()
        else:
            assert qset.filter(message__contains=search).exists

    if ix:
        qset = IXFImportEmail.objects.filter(ix=ix)
        if solo:
            assert qset.count() == 1
            assert qset.filter(message__contains=search).count() == 1
            assert not qset.filter(message__contains="CREATE").exists()
            assert not qset.filter(message__contains="MODIFY").exists()
            assert not qset.filter(message__contains="REMOVE").exists()
        else:
            assert qset.filter(message__contains=search).exists


def assert_no_network_email(network):
    if network.ipv4_support and network.ipv6_support:
        assert IXFImportEmail.objects.filter(net=network.id).count() == 0
    else:
        assert_protocol_conflict_email(
            protocols=network,
            network=network,
        )


def ticket_list():
    return [(t.id, t.subject) for t in DeskProTicket.objects.all().order_by("id")]


def email_list():
    return [(t.id, t.subject) for t in IXFImportEmail.objects.all().order_by("id")]


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
    emails = email_list()

    def assert_no_changes():
        assert ixf_members == ixf_member_data_list()
        assert tickets == ticket_list()
        assert netixlans == netixlan_list()
        assert emails == email_list()

    # Test idempotent
    importer.notifications = []
    importer.update(ixlan, data=data, save=save)
    importer.notify_proposals()
    assert_no_changes()

    # Test idempotent when running against single
    # non-existing asn
    importer.update(ixlan, data=data, asn=12345, save=save)
    importer.notify_proposals()
    assert_no_changes()
