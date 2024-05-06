import datetime
import io
import time

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings

from peeringdb_server.models import (
    REFTAG_MAP,
    UTC,
    Campus,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    Network,
    NetworkFacility,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.stats import get_fac_stats, get_ix_stats, reset_stats, stats

from .util import ClientCase, Group, override_group_id

DATE_PAST = datetime.datetime(year=2019, month=11, day=1)


def setup_data():
    call_command("pdb_generate_test_data", limit=3, commit=True)

    date_past = DATE_PAST.replace(tzinfo=UTC())

    # one object of each type moved to the past

    for tag in ["fac", "net", "org", "ix", "carrier", "campus", "netixlan", "netfac"]:
        for obj in REFTAG_MAP[tag].objects.all():
            obj.created = obj.updated = date_past
            obj.save()
            break

    # add facilities to campus so its no longer pending

    campus = Campus.objects.filter(status="ok").first()

    for campus in Campus.objects.filter(status="pending"):
        Facility.objects.create(
            name=f"Campus Fac 1 {campus.id}",
            status="ok",
            campus=campus,
            latitude=31.0,
            longitude=30.0,
            org=campus.org,
        )
        Facility.objects.create(
            name=f"Campus Fac 2 {campus.id}",
            status="ok",
            campus=campus,
            latitude=31.0,
            longitude=30.0,
            org=campus.org,
        )
        campus.refresh_from_db()
        assert campus.status == "ok"

    # create users

    User = get_user_model()

    for i in range(1, 7):
        User.objects.create_user(f"user_{i}", f"user_{i}@localhost", "secret")

    # move users 4, 5, 6 to the past

    User.objects.filter(username__in=["user_4", "user_5", "user_6"]).update(
        created=date_past
    )

    # verify all users except 1 and 4

    user_group, _ = Group.objects.get_or_create(name="user")
    guest_group, _ = Group.objects.get_or_create(name="guest")

    settings.USER_GROUP_ID = user_group.id
    settings.GUEST_GROUP_ID = guest_group.id

    with override_group_id():
        for user in User.objects.exclude(username__in=["user_1", "user_4"]):
            user.set_verified()


@pytest.mark.django_db
def test_generate_for_past_date(db, data_stats_past):
    output = io.StringIO()
    setup_data()
    call_command("pdb_stats", date=DATE_PAST.strftime("%Y%m%d"), stdout=output)
    assert output.getvalue() == data_stats_past.txt


@pytest.mark.django_db
def test_generate_for_current_date(db, data_stats_current):
    output = io.StringIO()
    setup_data()
    call_command("pdb_stats", stdout=output)

    for user in get_user_model().objects.all():
        print(user.username)

    assert data_stats_current.txt in output.getvalue()


@pytest.mark.django_db
def test_global_stats(db, data_stats_global):
    setup_data()
    reset_stats()

    # test_automated_network_count shows that "automated networks" counts
    # networks w allow_ixp_update=True
    if data_stats_global.name == "test_automated_network_count":
        network = Network.objects.first()
        network.allow_ixp_update = False
        network.save()

    global_stats = stats()
    assert global_stats == data_stats_global.expected


@override_settings(GLOBAL_STATS_CACHE_DURATION=500)
@pytest.mark.django_db
def test_global_stats_cache(db, data_stats_global_cached):
    setup_data()
    reset_stats()

    # set testing state of 3 automated networks

    Network.objects.update(allow_ixp_update=False)
    for network in Network.objects.filter(status="ok")[:3]:
        network.allow_ixp_update = True
        network.save()

    # run global stats and cache (automated network = 3)

    global_stats = stats()

    org = Organization.objects.first()

    # create additional network (automated networks in db = 4)

    net = Network.objects.create(org=org, asn=63311, status="ok", name="20C")

    # run global stats using cached result (automated network = 3)

    global_stats = stats()
    assert global_stats == data_stats_global_cached.expected

    # expire cache

    reset_stats()

    # run global stats and cache (automated network = 4 and will no longer match)

    global_stats = stats()
    assert global_stats != data_stats_global_cached.expected


@pytest.mark.django_db
def test_ix_fac_stats(db, data_stats_global):
    setup_data()

    exchange = InternetExchange.objects.first()

    netixlan = (
        NetworkIXLan.handleref.undeleted()
        .select_related("network", "ixlan")
        .order_by("network__name")
        .filter(ixlan__ix=exchange)
    )

    ixlan = exchange.ixlan

    ix_stats = get_ix_stats(netixlan, ixlan)

    ipv6_percentage = 0

    total_speed = 0

    for n in netixlan.filter(status="ok", ixlan=ixlan):
        total_speed += n.speed

    try:
        ipv6_percentage = int(
            (
                netixlan.filter(status="ok", ixlan=ixlan, ipaddr6__isnull=False).count()
                / netixlan.filter(ixlan=ixlan, status="ok").count()
            )
            * 100
        )
    except ZeroDivisionError:
        pass

    assert (
        ix_stats["peer_count"]
        == netixlan.values("network").distinct().filter(status="ok").count()
    )
    assert (
        ix_stats["connection_count"]
        == netixlan.filter(ixlan=ixlan, status="ok").count()
    )
    assert ix_stats["open_peer_count"] == (
        netixlan.values("network")
        .distinct()
        .filter(network__policy_general="Open", status="ok")
        .count()
    )
    assert ix_stats["ipv6_percentage"] == ipv6_percentage
    assert ix_stats["total_speed"] == total_speed

    facility = Facility.objects.first()

    ixfac = (
        InternetExchangeFacility.handleref.undeleted()
        .filter(facility=facility)
        .select_related("ix")
        .order_by("ix__name")
        .all()
    )

    netfac = (
        NetworkFacility.handleref.undeleted()
        .filter(facility=facility)
        .select_related("network")
        .order_by("network__name")
    )

    fac_stats = get_fac_stats(netfac, ixfac)

    assert fac_stats["networks"] == netfac.filter(status="ok").count()
    assert fac_stats["ix"] == ixfac.filter(status="ok").count()
