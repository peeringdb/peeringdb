import time
from datetime import datetime, timedelta, timezone

import pytest
import reversion
from django_grainy.models import Group

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
    User,
    UserOrgAffiliationRequest,
)


def now():
    return datetime.now(timezone.utc)


def two_weeks_ago():
    return datetime.now(timezone.utc) - timedelta(days=14)


def assert_same_time(time1, time2, eps=100):
    threshold = timedelta(milliseconds=eps)
    assert (time1 - time2) < threshold


@pytest.fixture()
def entities():
    with reversion.create_revision():
        org = Organization.objects.create(name="Netflix", status="ok")
        network = Network.objects.create(
            name="Network",
            asn=123,
            org=org,
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
        )

        ix = InternetExchange.objects.create(
            name="Test Exchange One",
            org=org,
            status="ok",
            tech_email="ix1@localhost",
        )

        facility = Facility.objects.create(
            name="Facility",
            status="ok",
            city="City",
            clli="CLLI",
            state="MD",
            country="US",
            zipcode=1,
            org=org,
        )

        netfac = NetworkFacility.objects.create(
            network=network,
            facility=facility,
            status="ok",
        )

        netixlan = NetworkIXLan.objects.create(
            network=network,
            ixlan=ix.ixlan,
            asn=network.asn,
            speed=1,
            ipaddr4="195.69.147.250",
            ipaddr6="2001:7f8:1::a500:2906:1",
            status="ok",
            is_rs_peer=True,
            operational=False,
        )

        poc = NetworkContact.objects.create(
            email="network1@localhost", network=network, status="ok", role="Policy"
        )

    return {
        "facility": facility,
        "org": org,
        "ix": ix,
        "network": network,
        "netfac": netfac,
        "netixlan": netixlan,
        "poc": poc,
    }


def null_network_update_fields(network):
    network._meta.get_field("updated").auto_now = False
    network.netixlan_updated = None
    network.netfac_updated = None
    network.poc_updated = None
    network.updated = two_weeks_ago()
    network.save()
    network._meta.get_field("updated").auto_now = True
    network.refresh_from_db()
    return network


def print_all(network):
    print(f"netixlan updated: {network.netixlan_updated}")
    print(f"Netfac updated: {network.netfac_updated}")
    print(f"poc updated: {network.poc_updated}")


@pytest.mark.django_db
def test_netixlan_update(entities):
    netixlan = NetworkIXLan.objects.first()
    network = Network.objects.first()
    network = null_network_update_fields(network)

    assert network.netixlan_updated is None
    assert network.netfac_updated is None
    assert network.poc_updated is None

    # update netixlan
    netixlan.speed = 2000
    with reversion.create_revision():
        netixlan.save()

    network.refresh_from_db()
    # Check that netixlan_updated reflects the netixlan change and is recent
    assert_same_time(network.netixlan_updated, netixlan.updated)
    assert network.netfac_updated is None
    assert network.poc_updated is None
    assert_same_time(network.updated, two_weeks_ago())


@pytest.mark.django_db
def test_netfac_update(entities):
    netfac = NetworkFacility.objects.first()
    network = Network.objects.first()
    network = null_network_update_fields(network)

    assert network.netixlan_updated is None
    assert network.netfac_updated is None
    assert network.poc_updated is None

    # update netfac
    netfac.status = "deleted"
    with reversion.create_revision():
        netfac.save()

    network.refresh_from_db()
    # Check that netixlan_updated reflects the netixlan change and is recent
    assert_same_time(network.netfac_updated, netfac.updated)
    assert network.netixlan_updated is None
    assert network.poc_updated is None
    assert_same_time(network.updated, two_weeks_ago())


@pytest.mark.django_db
def test_poc_update(entities):
    poc = NetworkContact.objects.first()
    network = Network.objects.first()
    network = null_network_update_fields(network)

    assert network.netixlan_updated is None
    assert network.netfac_updated is None
    assert network.poc_updated is None

    # update poc
    poc.phone = "555-555-5555"
    with reversion.create_revision():
        poc.save()

    network.refresh_from_db()

    # Check that netixlan_updated reflects the netixlan change and is recent
    assert_same_time(network.poc_updated, poc.updated)
    assert network.netixlan_updated is None
    assert network.netfac_updated is None
    assert_same_time(network.updated, two_weeks_ago())


@pytest.mark.django_db
def test_region_continent(entities):
    org = Organization.objects.first()
    fac = Facility.objects.first()

    fac.org = org
    fac.country.code = "US"

    with reversion.create_revision():
        fac.save()

    assert fac.region_continent == "North America"


@pytest.mark.django_db
def test_bulk_create_signal():
    org_list = [Organization(id=i, name=f"org-{i}") for i in range(1, 6)]
    Organization.objects.bulk_create(org_list)
    for i in range(1, 6):
        assert Group.objects.filter(name=f"org.{i}").exists() == True
        assert Group.objects.filter(name=f"org.{i}.admin").exists() == True


@pytest.mark.django_db
def test_uoar_creation():
    user = User.objects.create_user(
        username="user", password="user", email="user@localhost"
    )
    org = Organization.objects.create(name="Test Org")
    net = Network.objects.create(name="test network", org=org, asn=123, status="ok")
    uoar = UserOrgAffiliationRequest.objects.create(
        asn=net.asn, org=org, org_name=org.name, user=user
    )
    assert uoar.status == "pending"


@pytest.mark.django_db
def test_uoar_creation_network_deleted():
    user = User.objects.create_user(
        username="user", password="user", email="user@localhost"
    )
    org = Organization.objects.create(name="Test Org")
    net = Network.objects.create(
        name="test network", org=org, asn=123, status="deleted"
    )
    uoar = UserOrgAffiliationRequest.objects.create(
        asn=net.asn, org=org, org_name=org.name, user=user
    )
    assert uoar.status == "denied"
