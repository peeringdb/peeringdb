import json
import os
import re

import pytest
import reversion
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from peeringdb_server import ixf
from peeringdb_server.models import (
    Group,
    InternetExchange,
    IXFMemberData,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
    User,
)

from .util import override_group_id


@pytest.mark.django_db
def test_reset_ixf_proposals(admin_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    client = setup_client(admin_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id,))

    create_IXFMemberData(network, ixlan, ip_addresses, True)

    response = client.post(url)
    _ = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(dismissed=True).count() == 0


@pytest.mark.django_db
def test_dismiss_ixf_proposals(admin_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    ids = create_IXFMemberData(network, ixlan, ip_addresses, False)

    client = setup_client(admin_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, ids[-1]))

    response = client.post(url)
    _ = response.content.decode("utf-8")

    assert response.status_code == 200
    assert IXFMemberData.objects.filter(pk=ids[-1]).first().dismissed is True


@pytest.mark.django_db
def test_reset_ixf_proposals_no_perm(regular_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    client = setup_client(regular_user)
    url = reverse("net-reset-ixf-proposals", args=(network.id,))

    create_IXFMemberData(network, ixlan, ip_addresses, True)

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content


@pytest.mark.django_db
def test_dismiss_ixf_proposals_no_perm(regular_user, entities, ip_addresses):
    network = entities["network"]
    ixlan = entities["ixlan"][0]

    ids = create_IXFMemberData(network, ixlan, ip_addresses, False)

    client = setup_client(regular_user)
    url = reverse("net-dismiss-ixf-proposal", args=(network.id, ids[-1]))

    response = client.post(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 401
    assert "Permission denied" in content


@pytest.mark.django_db
def test_ix_order(admin_user, entities, ip_addresses, ip_addresses_other):
    """
    Test that multiple exchanges proposing changes appear
    sorted by exchange name
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]
    ixlan_b = entities["ixlan"][1]

    create_IXFMemberData(network, ixlan_a, ip_addresses, False)
    create_IXFMemberData(network, ixlan_b, ip_addresses_other, False)

    client = setup_client(admin_user)

    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200

    matches = re.findall('<a class="ix-name">([^<]+)</a>', content)
    assert matches == ["Test Exchange One", "Test Exchange Two"]


@pytest.mark.django_db
def test_ix_disabled_import_hides_proposals(
    admin_user, entities, ip_addresses, ip_addresses_other
):
    """
    Test that disabling the import hides proposals made by it
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]
    ixlan_b = entities["ixlan"][1]

    create_IXFMemberData(network, ixlan_a, ip_addresses, False)
    create_IXFMemberData(network, ixlan_b, ip_addresses_other, False)

    ixlan_a.ixf_ixp_import_enabled = False
    ixlan_a.save()

    client = setup_client(admin_user)

    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200

    matches = re.findall('<a class="ix-name">([^<]+)</a>', content)
    assert matches == ["Test Exchange Two"]


@pytest.mark.django_db
def test_ix_unset_ixf_url_hides_proposals(
    admin_user, entities, ip_addresses, ip_addresses_other
):
    """
    Test that disabling the import hides proposals made by it
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]
    ixlan_b = entities["ixlan"][1]

    create_IXFMemberData(network, ixlan_a, ip_addresses, False)
    create_IXFMemberData(network, ixlan_b, ip_addresses_other, False)

    ixlan_a.ixf_ixp_member_list_url = ""
    ixlan_a.save()

    client = setup_client(admin_user)

    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    content = response.content.decode("utf-8")

    assert response.status_code == 200

    matches = re.findall('<a class="ix-name">([^<]+)</a>', content)
    assert matches == ["Test Exchange Two"]


@pytest.mark.django_db
def test_ix_disabled_import_hides_dismissed(
    admin_user, entities, ip_addresses, ip_addresses_other
):
    """
    Test that disabling the import hides proposals made by it
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]

    create_IXFMemberData(network, ixlan_a, [ip_addresses[0]], True)

    client = setup_client(admin_user)
    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    content = response.content.decode("utf-8")

    # dismissed suggestion still relevant, confirm note is shown

    assert response.status_code == 200
    assert "You have dismissed some suggestions" in content

    ixlan_a.ixf_ixp_import_enabled = False
    ixlan_a.save()

    with override_group_id():
        response = client.get(url)

    content = response.content.decode("utf-8")

    # dismissed suggestion no longer relevant, confirm note is gibe

    assert response.status_code == 200
    assert "You have dismissed some suggestions" not in content


@pytest.mark.django_db()
def test_dismissed_note(admin_user, entities, ip_addresses):
    """
    Test that dismissed hints that are no longer relevant (noop)
    don't show the "you have dimissed suggestions" notification (#809)
    """

    network = entities["network"]
    ixlan_a = entities["ixlan"][0]

    create_IXFMemberData(network, ixlan_a, [ip_addresses[0]], True)

    client = setup_client(admin_user)
    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    content = response.content.decode("utf-8")

    # dismissed suggestion still relevant, confirm note is shown

    assert response.status_code == 200
    assert "You have dismissed some suggestions" in content

    # create netixlan, causing the suggestion to become noop

    NetworkIXLan.objects.create(
        network=network,
        asn=network.asn,
        ixlan=ixlan_a,
        status="ok",
        speed=0,
        ipaddr4=ip_addresses[0][0],
        ipaddr6=ip_addresses[0][1],
    )

    with override_group_id():
        response = client.get(url)

    content = response.content.decode("utf-8")

    # dismissed suggestion no longer relevant, confirm note is gibe

    assert response.status_code == 200
    assert "You have dismissed some suggestions" not in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ipaddr4",
    [
        "195.69.144.0",  # test invalid network
        "195.69.147.255",  # test invalid broadcast
    ],
)
def test_invalid_ipaddr4(
    admin_user, ixf_importer_user, entities, ip_addresses, ipaddr4
):
    network = Network.objects.create(
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
        info_unicast=False,
        info_ipv6=False,
    )
    ixlan = entities["ixlan"][0]

    with pytest.raises(ValidationError):
        netixlan = NetworkIXLan.objects.create(
            network=network,
            ixlan=ixlan,
            asn=network.asn,
            speed=10000,
            ipaddr4=ipaddr4,
            ipaddr6="2001:7f8:1::a500:2906:3",
            status="ok",
            is_rs_peer=True,
            operational=True,
        )
        netixlan.validate_ipaddr4()


@pytest.mark.django_db
def test_check_ixf_proposals(admin_user, ixf_importer_user, entities, ip_addresses):
    network = Network.objects.create(
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
        info_unicast=False,
        info_ipv6=False,
    )
    ixlan = entities["ixlan"][0]

    # We create one Netixlan that matches the ASN and ipaddr6 of the import.json
    # Therefore, the hint will suggest we modify this netixlan
    netixlan = NetworkIXLan.objects.create(
        network=network,
        ixlan=ixlan,
        asn=network.asn,
        speed=10000,
        ipaddr4="195.69.147.251",
        ipaddr6="2001:7f8:1::a500:2906:3",
        status="ok",
        is_rs_peer=True,
        operational=True,
    )
    netixlan.validate_ipaddr4()
    with open(
        os.path.join(
            os.path.dirname(__file__),
            "data",
            "ixf",
            "views",
            "import.json",
        ),
    ) as fh:
        json_data = json.load(fh)

    importer = ixf.Importer()
    importer.update(ixlan, data=json_data)

    client = setup_client(admin_user)
    url = reverse("net-view", args=(network.id,))

    with override_group_id():
        response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    # Suggest add
    assert 'data-field="ipaddr4" value="195.69.147.250"' in content
    assert 'data-field="ipaddr6" value="2001:7f8:1::a500:2906:1"' in content

    # Suggest modify
    assert 'data-field="ipaddr4" data-value=""' in content
    assert 'data-field="ipaddr6" data-value="2001:7f8:1::a500:2906:3"' in content


# Functions and fixtures


def setup_client(user):
    client = Client()
    client.force_login(user)
    return client


def create_IXFMemberData(network, ixlan, ip_addresses, dismissed):
    """
    Creates IXFMember data. Returns the ids of the created instances.
    """
    ids = []
    for ip_address in ip_addresses:
        ixfmember = IXFMemberData.instantiate(
            network.asn, ip_address[0], ip_address[1], ixlan, data={"foo": "bar"}
        )
        ixfmember.save()
        ixfmember.dismissed = dismissed
        ixfmember.save()
        ids.append(ixfmember.id)
    return ids


@pytest.fixture
def ip_addresses():
    """
    Returns a list of tuples of ipaddr4 and ipaddr6
    """
    return [
        ("195.69.144.1", "2001:7f8:1::a500:2906:1"),
        ("195.69.144.2", "2001:7f8:1::a500:2906:2"),
        ("195.69.144.3", "2001:7f8:1::a500:2906:3"),
        ("195.69.144.4", "2001:7f8:1::a500:2906:4"),
        ("195.69.144.5", "2001:7f8:1::a500:2906:5"),
    ]


@pytest.fixture
def ip_addresses_other():
    """
    Returns a list of tuples of ipaddr4 and ipaddr6
    """
    return [
        ("195.70.144.1", "2001:7f8:2::a500:2906:1"),
        ("195.70.144.2", "2001:7f8:2::a500:2906:2"),
        ("195.70.144.3", "2001:7f8:2::a500:2906:3"),
        ("195.70.144.4", "2001:7f8:2::a500:2906:4"),
        ("195.70.144.5", "2001:7f8:2::a500:2906:5"),
    ]


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
                prefix="195.70.144.0/22",
                protocol="IPv4",
            ),
            IXLanPrefix.objects.create(
                ixlan=entities["ixlan"][1],
                status="ok",
                prefix="2001:7f8:2::/64",
                protocol="IPv6",
            ),
        ]

        # create network(s)
        entities["network"] = Network.objects.create(
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
        )

    return entities


@pytest.fixture
def admin_user():
    guest_group, _ = Group.objects.get_or_create(name="guest")
    user_group, _ = Group.objects.get_or_create(name="user")

    print(f"Guest: {guest_group} {guest_group.id} ")
    print(f"User: {user_group} {user_group.id} ")

    admin_user = User.objects.create_user(
        "admin", "admin@localhost", first_name="admin", last_name="admin"
    )
    admin_user.is_superuser = True
    admin_user.is_staff = True
    admin_user.save()
    admin_user.set_password("admin")
    admin_user.save()
    return admin_user


@pytest.fixture
def regular_user():
    user = User.objects.create_user(
        "user", "user@localhost", first_name="user", last_name="user"
    )
    user.set_password("user")
    user.save()
    return user
