import time

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from peeringdb_server.models import (
    DataChangeEmail,
    DataChangeNotificationQueue,
    DataChangeWatchedObject,
    EmailAddress,
    Network,
    NetworkIXLan,
    User,
)

from .util import ClientCase


def save_netixlan(netixlan):
    with reversion.create_revision():
        netixlan.save()

    netixlan_versions = reversion.models.Version.objects.get_for_object(netixlan)
    return netixlan_versions.last()


@pytest.fixture
def datachange_objects():
    return _datachange_objects()


def _datachange_objects():
    call_command("pdb_generate_test_data", limit=1, commit=True)

    net = Network.objects.first()
    netixlan = net.netixlan_set.first()
    user = User.objects.create_user(
        username="watcher", email="watcher@localhost", password="watcher"
    )

    EmailAddress.objects.create(user=user, email="watcher@localhost")

    watched = DataChangeWatchedObject.objects.create(
        user=user, ref_tag="net", object_id=net.id
    )

    net.org.admin_usergroup.user_set.add(user)

    netixlan_versions = reversion.models.Version.objects.get_for_object(netixlan)
    netixlan_version = netixlan_versions.last()

    return {
        "net": net,
        "user": user,
        "netixlan": netixlan,
        "watched_object": watched,
        "version": netixlan_version,
    }


@pytest.mark.django_db
def test_notification_queue_push(datachange_objects):
    assert DataChangeNotificationQueue.push(
        "ixf",
        "add",
        datachange_objects["netixlan"],
        None,
        datachange_objects["version"],
    )


@pytest.mark.django_db
def test_notification_queue_push_no_watcher(datachange_objects):
    DataChangeWatchedObject.objects.all().delete()

    assert not DataChangeNotificationQueue.push(
        "ixf",
        "add",
        datachange_objects["netixlan"],
        None,
        datachange_objects["version"],
    )


@pytest.mark.django_db
def test_notification_queue_properties(datachange_objects):
    entry = DataChangeNotificationQueue.push(
        "ixf",
        "add",
        datachange_objects["netixlan"],
        None,
        datachange_objects["version"],
        reason="this is a test",
    )

    assert entry
    assert entry.watched_object == datachange_objects["net"]
    assert entry.target_object == datachange_objects["netixlan"]

    assert entry.title == "AS63312 206.223.116.101 2001:504:0:1::65"
    assert entry.action == "add"

    details = entry.details
    print(details)

    assert "this is a test" in details
    assert "Speed: 1G" in details
    assert "RS Peer: True" in details
    assert "Operational: True" in details
    assert "IX-F" in details

    entry = DataChangeNotificationQueue.push(
        "ixf",
        "delete",
        datachange_objects["netixlan"],
        None,
        datachange_objects["version"],
        reason="this is a test",
    )

    details = entry.details

    assert "this is a test" in details
    assert "Speed: 1G" not in details
    assert "RS Peer: True" not in details
    assert "Operational: True" not in details
    assert "IX-F" in details


@pytest.mark.django_db
def test_watched_object_cleanup_user_perms(datachange_objects):
    assert DataChangeWatchedObject.objects.count() == 1

    DataChangeWatchedObject.cleanup()

    assert DataChangeWatchedObject.objects.count() == 1

    net = datachange_objects["net"]
    user = datachange_objects["user"]
    org = net.org

    org.admin_usergroup.user_set.remove(user)

    DataChangeWatchedObject.cleanup()

    assert DataChangeWatchedObject.objects.count() == 0


@pytest.mark.django_db
def test_watched_object_cleanup_obj_deleted(datachange_objects):
    assert DataChangeWatchedObject.objects.count() == 1

    DataChangeWatchedObject.cleanup()

    assert DataChangeWatchedObject.objects.count() == 1

    net = datachange_objects["net"]

    net.delete()

    DataChangeWatchedObject.cleanup()

    assert DataChangeWatchedObject.objects.count() == 0


@pytest.mark.django_db
def test_watched_object_collect(datachange_objects):
    user = datachange_objects["user"]
    netixlan = datachange_objects["netixlan"]
    watched = datachange_objects["watched_object"]
    net = netixlan.network

    netixlan_2 = NetworkIXLan(
        status="ok",
        ixlan=netixlan.ixlan,
        network=netixlan.network,
        asn=netixlan.asn,
        ipaddr4="10.10.10.10",
        speed=1000,
    )
    version_netixlan_2 = save_netixlan(netixlan_2)

    entry_1 = DataChangeNotificationQueue.push(
        "ixf", "add", netixlan, None, datachange_objects["version"]
    )
    entry_2 = DataChangeNotificationQueue.push(
        "ixf", "add", netixlan_2, None, version_netixlan_2
    )

    netixlan.status = "deleted"
    version_netixlan_deleted = save_netixlan(netixlan)

    entry_3 = DataChangeNotificationQueue.push(
        "ixf",
        "delete",
        netixlan,
        datachange_objects["version"],
        version_netixlan_deleted,
    )

    users, collected = DataChangeWatchedObject.collect()

    assert users[user.id] == user
    assert collected[user.id] == {
        ("net", net.id): {
            "watched": watched,
            "entries": {
                ("netixlan", netixlan.id): [entry_1, entry_3],
                ("netixlan", netixlan_2.id): [entry_2],
            },
        }
    }

    now = timezone.now()

    watched.last_notified = now
    watched.save()

    users, collected = DataChangeWatchedObject.collect()

    assert not users
    assert not collected


@pytest.mark.django_db
@pytest.mark.parametrize("emails", [(True,), (False,)])
def test_command(datachange_objects, emails):
    settings.DATA_CHANGE_SEND_EMAILS = emails

    user = datachange_objects["user"]
    netixlan = datachange_objects["netixlan"]
    watched = datachange_objects["watched_object"]
    net = netixlan.network

    netixlan_2 = NetworkIXLan(
        status="ok",
        ixlan=netixlan.ixlan,
        network=netixlan.network,
        asn=netixlan.asn,
        ipaddr4="10.10.10.10",
        speed=1000,
    )
    version_netixlan_2 = save_netixlan(netixlan_2)

    entry_1 = DataChangeNotificationQueue.push(
        "ixf", "add", netixlan, None, datachange_objects["version"]
    )
    entry_2 = DataChangeNotificationQueue.push(
        "ixf", "add", netixlan_2, None, version_netixlan_2
    )

    netixlan.status = "deleted"
    version_netixlan_deleted = save_netixlan(netixlan)

    entry_3 = DataChangeNotificationQueue.push(
        "ixf",
        "delete",
        netixlan,
        datachange_objects["version"],
        version_netixlan_deleted,
    )

    # run non committal
    call_command("pdb_data_change_notify")

    assert DataChangeEmail.objects.count() == 0
    watched.refresh_from_db()
    assert watched.last_notified is None

    # run committal
    call_command("pdb_data_change_notify", commit=True)

    assert DataChangeEmail.objects.count() == 1
    email = DataChangeEmail.objects.first()
    if emails:
        assert email.sent
    else:
        assert not email.sent

    assert entry_1.title in email.content
    assert entry_2.title in email.content
    assert entry_3.title in email.content

    watched.refresh_from_db()

    if emails:
        assert watched.last_notified
    else:
        assert not watched.last_notified

    time.sleep(1)

    # run committal (no changes, no emails)
    call_command("pdb_data_change_notify", commit=True)
    assert DataChangeEmail.objects.count() == 1


class ViewTests(ClientCase):
    def test_view_watch_net(self):
        datachange_objects = _datachange_objects()
        DataChangeWatchedObject.objects.all().delete()

        user = datachange_objects["user"]
        net = datachange_objects["net"]

        self.user_group.user_set.add(user)

        assert not DataChangeWatchedObject.objects.filter(
            user=user, ref_tag="net", object_id=net.id
        ).exists()

        client = Client()
        client.force_login(user)

        resp = client.get(f"/net/{net.id}/watch")
        assert resp.status_code == 302

        assert DataChangeWatchedObject.objects.filter(
            user=user, ref_tag="net", object_id=net.id
        ).exists()

        resp = client.get(f"/net/{net.id}")
        assert "Disable notifications" in resp.content.decode("utf-8")

        resp = client.get(f"/net/{net.id}/unwatch")
        assert resp.status_code == 302

        assert not DataChangeWatchedObject.objects.filter(
            user=user, ref_tag="net", object_id=net.id
        ).exists()

        resp = client.get(f"/net/{net.id}")
        assert "Enable notifications" in resp.content.decode("utf-8")

        net.org.admin_usergroup.user_set.remove(user)

        client.force_login(User.objects.get(id=user.id))

        resp = client.get(f"/net/{net.id}/watch")
        assert resp.status_code == 403

        resp = client.get(f"/net/{net.id}")
        assert "Enable notifications" not in resp.content.decode("utf-8")
        assert "Disable notifications" not in resp.content.decode("utf-8")
