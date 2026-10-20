from unittest.mock import patch

import pytest
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError as RestValidationError

from peeringdb_server import serializers
from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.serializers import NetworkIXLanSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def ixlan():
    org = Organization.objects.create(name="Race Org", status="ok")
    ix = InternetExchange.objects.create(
        name="Race IX",
        org=org,
        status="ok",
        city="Chicago",
        country="US",
        region_continent="North America",
    )
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="192.0.2.0/24", status="ok"
    )
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv6", prefix="2001:db8::/64", status="ok"
    )
    return ix.ixlan


def network(org, asn):
    net = Network.objects.create(name=f"AS{asn}", status="ok", org=org, asn=asn)
    NetworkContact.objects.create(
        network=net,
        role="Technical",
        visible="Public",
        email=f"noc@as{asn}.example.com",
        status="ok",
    )
    return net


def create_payload(net, ixlan, **ips):
    return {
        "net_id": net.id,
        "ixlan_id": ixlan.id,
        "asn": net.asn,
        "speed": 1000,
        "ipaddr4": "",
        "ipaddr6": "",
        **ips,
    }


@pytest.mark.parametrize(
    "field,value,submitted",
    [
        ("ipaddr4", "192.0.2.10", "192.0.2.10"),
        ("ipaddr6", "2001:db8::10", "2001:db8::10"),
        # stored compressed, submitted in long form
        ("ipaddr6", "2001:db8::10", "2001:0db8:0000:0000:0000:0000:0000:0010"),
    ],
)
def test_create_lost_race_returns_validation_error(ixlan, field, value, submitted):
    first = network(ixlan.ix.org, 64500)
    second = network(ixlan.ix.org, 64501)
    NetworkIXLan.objects.create(
        network=first,
        ixlan=ixlan,
        asn=first.asn,
        speed=1000,
        status="ok",
        **{field: value},
    )

    serializer = NetworkIXLanSerializer(
        data=create_payload(second, ixlan, **{field: submitted})
    )
    # the competing insert lands after validation has passed (#485)
    with patch.object(NetworkIXLan, "ipaddress_conflict", return_value=(False, False)):
        assert serializer.is_valid(), serializer.errors

    with pytest.raises(RestValidationError) as exc:
        serializer.save()

    assert exc.value.detail == {field: ["IP already exists"]}
    assert exc.value.detail[field][0].code == "unique"
    assert NetworkIXLan.objects.filter(**{field: value}).count() == 1


def test_create_unrelated_integrity_error_is_raised(ixlan):
    net = network(ixlan.ix.org, 64500)
    serializer = NetworkIXLanSerializer(
        data=create_payload(net, ixlan, ipaddr4="192.0.2.20")
    )
    assert serializer.is_valid(), serializer.errors

    with patch.object(
        serializers.ModelSerializer,
        "create",
        side_effect=IntegrityError("unrelated constraint"),
    ):
        with pytest.raises(IntegrityError):
            serializer.save()
