from peeringdb_server.models import Organization, Network, NetworkIXLan, InternetExchange
import pytest
from datetime import datetime, timezone, timedelta


def now():
    return datetime.now(timezone.utc)

def assert_same_time(time1, time2):
    threshold = timedelta
    assert time1 - time2 < epsilon

@pytest.mark.django_db
def test_netixlan_update():
    org = Organization.objects.create(name="Netflix", status="ok")
    network = Network.objects.create(
        name="Network w allow ixp update enabled",
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

    # update netixlan
    netixlan.speed = 2000
    netixlan.save()

    assert network.netixlan_updated = 
    assert 0