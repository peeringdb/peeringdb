"""
The "Could not process IX-F Data" mail goes to the exchange's contacts and
the feed's schema_email, and only quotes feed values in a restricted form.
"""

import pytest
import reversion

from peeringdb_server import ixf
from peeringdb_server.models import (
    InternetExchange,
    IXFImportEmail,
    IXLanPrefix,
    Network,
    Organization,
    User,
)

pytestmark = pytest.mark.django_db

PAYLOAD = "PAYLOAD please call +1 555 0100 <b>now</b> to keep your peering"


@pytest.fixture
def ixlan():
    User.objects.get_or_create(
        username="ixf_importer", defaults={"email": "ixf_importer@localhost"}
    )
    with reversion.create_revision():
        org = Organization.objects.create(name="F4 IX Org", status="ok")
        ix = InternetExchange.objects.create(
            name="F4 Exchange", org=org, status="ok", tech_email="ix-tech@f4.example"
        )
        ixlan = ix.ixlan
        ixlan.ixf_ixp_member_list_url = "https://ixf.f4.example/feed.json"
        ixlan.save()
        IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="195.69.144.0/22", protocol="IPv4"
        )
        IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="2001:7f8:1::/64", protocol="IPv6"
        )
        Network.objects.create(
            name="F4 Network", org=org, asn=2906, status="ok", allow_ixp_update=False
        )
    return ixlan


def member(asn, ipv4, ipv6, vlan_id=0):
    return {
        "asnum": asn,
        "member_type": "peering",
        "name": f"AS{asn}",
        "connection_list": [
            {
                "ixp_id": 1,
                "state": "active",
                "if_list": [{"switch_id": 1, "if_speed": 10000}],
                "vlan_list": [
                    {
                        "vlan_id": vlan_id,
                        "ipv4": {"address": ipv4},
                        "ipv6": {"address": ipv6},
                    }
                ],
            }
        ],
    }


def feed(*members, schema_email="maintainer@f4.example"):
    return {
        "version": "1.0",
        "timestamp": "2026-11-05T00:00:00Z",
        "schema_email": schema_email,
        "member_list": list(members),
    }


def run(ixlan, data):
    importer = ixf.Importer()
    importer.update(ixlan, data=importer.sanitize(data))
    email = IXFImportEmail.objects.get(ix=ixlan.ix)
    ixlan.refresh_from_db()
    return email, ixlan.ixf_ixp_import_error


def test_error_mail_goes_to_exchange_and_schema_email(ixlan):
    data = feed(
        member(2906, PAYLOAD, "2001:7f8:1::a500:2906:1"),
        member(2906, PAYLOAD, "2001:7f8:1::a500:2906:2"),
    )
    email, _ = run(ixlan, data)

    assert email.recipients.split(",") == [
        "ix-tech@f4.example",
        "maintainer@f4.example",
    ]


@pytest.mark.parametrize(
    "schema_email",
    [None, "", "not an address", ["a@f4.example"], "IX-TECH@f4.example"],
)
def test_error_mail_ignores_unusable_schema_email(ixlan, schema_email):
    data = feed(
        member(2906, "195.69.147.250", "2001:7f8:1::a500:2906:1"),
        member(2906, "195.69.147.250", "2001:7f8:1::a500:2906:2"),
        schema_email=schema_email,
    )
    email, _ = run(ixlan, data)

    assert email.recipients == "ix-tech@f4.example"


def test_duplicate_address_is_quoted_not_copied(ixlan):
    data = feed(
        member(2906, PAYLOAD, "2001:7f8:1::a500:2906:1"),
        member(2906, PAYLOAD, "2001:7f8:1::a500:2906:2"),
    )
    email, error = run(ixlan, data)

    for text in (email.message, error):
        assert "please call" not in text
        assert "+1 555" not in text
        assert "<b>" not in text
        assert ixf.quote_feed_value(PAYLOAD) in text


def test_invalid_address_is_quoted_not_copied(ixlan):
    data = feed(member(2906, PAYLOAD, "2001:7f8:1::a500:2906:1"))
    email, error = run(ixlan, data)

    assert "Invalid IP address 'PAYLOAD?please" in error
    assert "please call" not in email.message


def test_multiple_vlans_error_has_no_vlan_dump(ixlan):
    vlan_extra = member(2906, "195.69.147.251", "2001:7f8:1::a500:2906:3", vlan_id=2)
    vlan_extra["connection_list"][0]["vlan_list"][0]["note"] = PAYLOAD
    data = feed(
        member(2906, "195.69.147.250", "2001:7f8:1::a500:2906:1", vlan_id=1),
        vlan_extra,
    )
    email, error = run(ixlan, data)

    # member order is not kept by sanitize, so either vlan can come first
    assert "multiple VLANs" in error
    assert {"First VLAN ID: '1'", "First VLAN ID: '2'"} & set(error.splitlines())
    assert {"Conflicting VLAN ID: '1'", "Conflicting VLAN ID: '2'"} & set(
        error.splitlines()
    )
    assert "Error occurred at data.member_list[" in email.message
    assert "PAYLOAD" not in email.message
    assert "Conflicting VLAN object" not in email.message


@pytest.mark.parametrize(
    "value,quoted",
    [
        ("195.69.147.250", "'195.69.147.250'"),
        ("2001:7f8:1::a500:2906:1", "'2001:7f8:1::a500:2906:1'"),
        (2906, "'2906'"),
        ("a\nb<script>", "'a?b?script?'"),
        ("x" * 60, "'" + "x" * 45 + "...'"),
    ],
)
def test_quote_feed_value(value, quoted):
    assert ixf.quote_feed_value(value) == quoted
