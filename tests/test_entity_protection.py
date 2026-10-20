import datetime

import pytest
from django.core.management import call_command

from peeringdb_server.models import (
    UTC,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
    ProtectedAction,
    Sponsorship,
)


def assert_protected(entity):
    """
    helper function to test that an object is currently
    not deletable
    """
    with pytest.raises(ProtectedAction):
        entity.delete()


@pytest.mark.django_db
def test_protected_entities(db):
    """
    test that protected entities cannot be deleted
    if their protection conditions are met
    """

    call_command("pdb_generate_test_data", limit=2, commit=True)

    org = Organization.objects.first()

    # assert that the org as active objects under it

    assert org.ix_set_active.exists()
    assert org.fac_set_active.exists()
    assert org.net_set_active.exists()
    assert org.carrier_set_active.exists()
    # assert org.campus_set_active.exists()

    # org has ix, net and fac under it, and should not be
    # deletable

    assert_protected(org)

    # process the exchanges under the org for deletion
    # and checking their protected status as well

    for ix in org.ix_set.all():
        assert ix.ixlan.ixpfx_set.exists()
        assert ix.ixlan.netixlan_set.exists()
        assert ix.ixfac_set.exists()

        # exchange currently has netixlans and prefixes
        # under it that are active and should not be
        # deletable

        assert_protected(ix)

        # process the ixfac objects under the exchange
        for ixfac in ix.ixfac_set.all():
            ixfac.delete()

        # process the netixlans under the exchange and
        # delete them

        for netixlan in ix.ixlan.netixlan_set.all():
            netixlan.delete()

        # with netixlans gone the exchange can now be
        # deleted
        ix.delete()

    # org still has active fac and net under it
    # and should still be protected

    assert_protected(org)

    # process the facilities under the org for deletion
    # and checking their protected status as well

    for fac in org.fac_set.all():
        assert fac.ixfac_set.exists()
        assert fac.netfac_set.exists()

        # fac has active netfac and ixfac objects
        # under it and should not be deletable

        assert_protected(fac)

        # delete ixfacs

        for ixfac in fac.ixfac_set.all():
            ixfac.delete()

        # fac has active netfac under it and should
        # still not be deletable

        assert_protected(fac)

        # delete netfacs

        for netfac in fac.netfac_set.all():
            netfac.delete()

        # facility can now be deleted

        fac.delete()

    # org still has active net objects under it
    # and should not be deletable

    assert_protected(org)

    # delete carriers

    for carrier in org.carrier_set.all():
        carrier.delete()

    # org still has active net objects under it
    # and should not be deletable

    assert_protected(org)

    # delete campuses

    for campus in org.campus_set.all():
        campus.delete()

    # org still has active net objects under it
    # and should not be deletable

    assert_protected(org)

    # delete nets

    for net in org.net_set.all():
        net.delete()

    # org is now deletable

    org.delete()
    assert org.status == "deleted"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role,deletable",
    [
        ("Technical", False),
        ("Policy", False),
        ("NOC", False),
        ("Abuse", True),
        ("Maintenance", True),
        ("Public Relations", True),
        ("Sales", True),
    ],
)
def test_tech_poc_protection(role, deletable):
    """
    Test that the last technical contact
    cannot be deleted for a network that has
    active peers (#923)
    """

    call_command("pdb_generate_test_data", limit=2, commit=True)

    net = Network.objects.first()

    poc = NetworkContact.objects.create(status="ok", role=role, network=net)

    if not deletable:
        assert_protected(poc)
        for netixlan in net.netixlan_set_active.all():
            netixlan.delete()
        poc.delete()
    else:
        poc.delete()
        return

    NetworkContact.objects.create(status="ok", role=role, network=net)

    poc.delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        "Technical",
        "Policy",
        "NOC",
        "Abuse",
        "Maintenance",
        "Public Relations",
        "Sales",
    ],
)
def test_tech_poc_hard_delete_1013(role):
    """
    Test that already soft-deleted pocs dont raise
    a protected action error when hard-deleting (#1013)
    """

    call_command("pdb_generate_test_data", limit=2, commit=True)

    net = Network.objects.first()

    net.poc_set.all().delete()

    poc_a = NetworkContact.objects.create(status="ok", role="Technical", network=net)
    poc_b = NetworkContact.objects.create(status="deleted", role=role, network=net)
    poc_b.delete(hard=True)

    poc_a.delete(force=True)
    poc_a.delete(hard=True)


@pytest.mark.django_db
def test_org_protection_sponsor(db):
    """
    test that organization cannot be deleted if it has
    an active sponsorship going
    """

    now = datetime.datetime.now().replace(tzinfo=UTC())

    org = Organization.objects.create(status="ok", name="SponsorOrg")
    sponsor = Sponsorship.objects.create(
        start_date=now - datetime.timedelta(days=1),
        end_date=now + datetime.timedelta(days=1),
    )
    sponsor.orgs.add(org)

    assert org.sponsorship.active

    assert org.deletable is False
    assert "Organization is currently an active sponsor" in org.not_deletable_reason

    with pytest.raises(ProtectedAction):
        org.delete()

    sponsor.delete()

    org.delete()


def make_exchange(name, asn=64510, status="ok"):
    """
    helper that builds an org + exchange (and its ixlan) for the
    last-prefix tests, along with a network to attach peers to
    """

    org = Organization.objects.create(name=f"Org {name}", status="ok")
    ix = InternetExchange.objects.create(
        name=name, org=org, status=status, tech_email="ix@localhost"
    )
    net = Network.objects.create(name=f"Net {name}", asn=asn, org=org, status="ok")
    return org, ix, net


def add_prefix(ixlan, prefix, status="ok", protocol="IPv4"):
    return IXLanPrefix.objects.create(
        ixlan=ixlan, prefix=prefix, protocol=protocol, status=status
    )


@pytest.mark.django_db
def test_last_prefix_deletes_exchange():
    """
    removing the last active prefix of a listed exchange removes the
    exchange as well (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix")
    prefix = add_prefix(ix.ixlan, "198.51.100.0/24")

    assert prefix.is_last_prefix is True
    assert "remove the exchange from PeeringDB" in (
        prefix.deletion_confirmation_required()
    )

    prefix.delete()

    ix.refresh_from_db()
    prefix.refresh_from_db()

    assert prefix.status == "deleted"
    assert ix.status == "deleted"
    assert ix.ixlan.status == "deleted"


@pytest.mark.django_db
def test_last_prefix_confirmation_names_what_goes_with_the_exchange():
    """
    the exchange deletion is forced past the exchange's own guards, so the
    confirmation has to name the peers and facility connections that are
    taken down with it -- they belong to other organizations (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix Copy", asn=64524)
    fac = Facility.objects.create(
        name="Fac Last Prefix Copy", org=org, status="ok", city="City", country="US"
    )
    InternetExchangeFacility.objects.create(ix=ix, facility=fac, status="ok")
    NetworkIXLan.objects.create(
        network=net, ixlan=ix.ixlan, asn=net.asn, speed=1000, status="ok"
    )
    prefix = add_prefix(ix.ixlan, "198.51.118.0/24")

    message = prefix.deletion_confirmation_required()

    assert "1 active peer(s)" in message
    assert "1 active facility connection(s)" in message


@pytest.mark.django_db
def test_last_prefix_confirmation_omits_empty_counts():
    """
    an exchange with nothing else attached gets the plain message, with no
    empty "0 active peer(s)" clause (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix Plain", asn=64525)
    prefix = add_prefix(ix.ixlan, "198.51.119.0/24")

    message = prefix.deletion_confirmation_required()

    assert "remove the exchange from PeeringDB" in message
    assert "active peer(s)" not in message
    assert "active facility connection(s)" not in message


@pytest.mark.django_db
def test_last_prefix_deletes_exchange_with_facility_connection():
    """
    a facility connection normally blocks exchange deletion, but a
    prefix-less exchange should not stay listed regardless (#1717,
    design decision 2)
    """

    org, ix, net = make_exchange("IX Last Prefix Fac", asn=64511)
    fac = Facility.objects.create(
        name="Fac Last Prefix", org=org, status="ok", city="City", country="US"
    )
    ixfac = InternetExchangeFacility.objects.create(ix=ix, facility=fac, status="ok")
    prefix = add_prefix(ix.ixlan, "198.51.101.0/24")

    # the exchange is not directly deletable while the connection exists
    assert ix.deletable is False

    prefix.delete()

    ix.refresh_from_db()
    ixfac.refresh_from_db()

    assert ix.status == "deleted"
    assert ixfac.status == "deleted"


@pytest.mark.django_db
def test_last_prefix_deletes_exchange_with_addressless_peer():
    """
    an active peer with no ip addresses does not use the prefix, so it does
    not block the removal and is taken down with the exchange (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix Addressless", asn=64512)
    netixlan = NetworkIXLan.objects.create(
        network=net, ixlan=ix.ixlan, asn=net.asn, speed=1000, status="ok"
    )
    prefix = add_prefix(ix.ixlan, "198.51.102.0/24")

    prefix.delete()

    ix.refresh_from_db()
    netixlan.refresh_from_db()

    assert ix.status == "deleted"
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_last_prefix_deletes_exchange_with_peer_addressed_outside_prefix():
    """
    a peer whose address falls outside the prefix being deleted does not
    block it, so the exchange -- and that peer's connection -- go (#1717)

    this is the shape the prefix protection cannot see: it only rejects a
    peer addressed inside the prefix, of the prefix's own protocol. The
    exchange's own peer guard is bypassed deliberately, a prefix-less
    exchange does not meet the listing criteria regardless of what is still
    attached to it.
    """

    org, ix, net = make_exchange("IX Last Prefix Drifted", asn=64526)
    prefix = add_prefix(ix.ixlan, "2001:db8:126::/64", protocol="IPv6")
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr6="2001:db8:999::1",
    )

    # the prefix protection does not see this peer, but the exchange's own
    # guard does -- it is the force that gets past it
    assert prefix.deletable is True
    assert ix.deletable is False
    assert ix.not_deletable_reason == "Exchange has active peer(s)"
    assert "1 active peer(s)" in prefix.deletion_confirmation_required()

    prefix.delete()

    ix.refresh_from_db()
    netixlan.refresh_from_db()

    assert ix.status == "deleted"
    assert netixlan.status == "deleted"
    # the network itself is untouched, only its connection to the exchange
    net.refresh_from_db()
    assert net.status == "ok"


@pytest.mark.django_db
def test_last_prefix_deletes_exchange_with_wrong_family_peer():
    """
    same for a peer addressed in the other protocol entirely -- an IPv4
    address cannot be inside an IPv6 prefix, so nothing blocks the delete
    (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix Wrong Family", asn=64527)
    prefix = add_prefix(ix.ixlan, "2001:db8:127::/64", protocol="IPv6")
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="198.51.127.1",
    )

    assert prefix.deletable is True
    assert ix.deletable is False

    prefix.delete()

    ix.refresh_from_db()
    netixlan.refresh_from_db()

    assert ix.status == "deleted"
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_facility_survives_exchange_deletion():
    """
    the cascade takes the ixfac join row, not the facility itself (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix Fac Survives", asn=64528)
    fac = Facility.objects.create(
        name="Fac Survives", org=org, status="ok", city="City", country="US"
    )
    ixfac = InternetExchangeFacility.objects.create(ix=ix, facility=fac, status="ok")
    prefix = add_prefix(ix.ixlan, "198.51.128.0/24")

    prefix.delete()

    ix.refresh_from_db()
    ixfac.refresh_from_db()
    fac.refresh_from_db()

    assert ix.status == "deleted"
    assert ixfac.status == "deleted"
    assert fac.status == "ok"


@pytest.mark.django_db
def test_peer_using_prefix_still_blocks_deletion():
    """
    a peer with an ip inside the prefix blocks the prefix removal, so the
    exchange is never reached (#1717)
    """

    org, ix, net = make_exchange("IX Prefix In Use", asn=64513)
    prefix = add_prefix(ix.ixlan, "198.51.103.0/24")
    NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="198.51.103.1",
    )

    assert_protected(prefix)

    ix.refresh_from_db()
    prefix.refresh_from_db()

    assert prefix.status == "ok"
    assert ix.status == "ok"


@pytest.mark.django_db
def test_peer_using_last_prefix_asks_no_confirmation():
    """
    a prefix that cannot be deleted at all asks for no confirmation, so the
    operator gets the protection error naming the peer in the way instead of
    confirming a removal that is then refused (#1717)
    """

    org, ix, net = make_exchange("IX Last Prefix In Use", asn=64523)
    prefix = add_prefix(ix.ixlan, "198.51.117.0/24")
    NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        status="ok",
        ipaddr4="198.51.117.1",
    )

    # it is still the exchange's last prefix, it just is not removable
    assert prefix.is_last_prefix is True
    assert prefix.deletable is False
    assert prefix.deletion_confirmation_required() is None

    assert_protected(prefix)

    ix.refresh_from_db()
    prefix.refresh_from_db()

    assert prefix.status == "ok"
    assert ix.status == "ok"


@pytest.mark.django_db
def test_non_last_prefix_leaves_exchange_listed():
    """
    removing a prefix while another one remains does not touch the
    exchange (#1717)
    """

    org, ix, net = make_exchange("IX Two Prefixes", asn=64514)
    prefix_v4 = add_prefix(ix.ixlan, "198.51.104.0/24")
    add_prefix(ix.ixlan, "2001:db8:104::/64", protocol="IPv6")

    assert prefix_v4.is_last_prefix is False
    assert prefix_v4.deletion_confirmation_required() is None

    prefix_v4.delete()

    ix.refresh_from_db()

    assert ix.status == "ok"
    assert ix.ixlan.ixpfx_set_active.count() == 1


@pytest.mark.django_db
def test_pending_prefix_keeps_exchange_listed():
    """
    a pending prefix counts as a remaining prefix, so removing the active
    one leaves the exchange listed (#1717)
    """

    org, ix, net = make_exchange("IX Pending Replacement", asn=64515)
    prefix = add_prefix(ix.ixlan, "198.51.105.0/24")
    add_prefix(ix.ixlan, "198.51.106.0/24", status="pending")

    assert prefix.is_last_prefix is False

    prefix.delete()

    ix.refresh_from_db()

    assert ix.status == "ok"


@pytest.mark.django_db
def test_pending_exchange_is_not_deleted():
    """
    a pending exchange is not listed yet and is left for the admin
    committee to resolve (#1717)
    """

    org, ix, net = make_exchange("IX Pending", asn=64516, status="pending")
    prefix = add_prefix(ix.ixlan, "198.51.107.0/24", status="pending")

    assert prefix.is_last_prefix is False

    prefix.delete()

    ix.refresh_from_db()

    assert ix.status == "pending"


@pytest.mark.django_db
def test_forced_last_prefix_delete_leaves_exchange():
    """
    force and hard deletes are administrative overrides used by internal
    cleanup, and must not depublish an exchange (#1717)
    """

    org, ix, net = make_exchange("IX Forced", asn=64517)
    prefix = add_prefix(ix.ixlan, "198.51.108.0/24")

    prefix.delete(force=True)

    ix.refresh_from_db()
    assert ix.status == "ok"

    prefix_hard = add_prefix(ix.ixlan, "198.51.109.0/24")
    prefix_hard.delete(hard=True)

    ix.refresh_from_db()
    assert ix.status == "ok"
    assert not IXLanPrefix.objects.filter(pk=prefix_hard.pk).exists()


@pytest.mark.django_db
def test_exchange_delete_cascade_does_not_recurse():
    """
    deleting the exchange cascades into its prefixes, and the last-prefix
    trigger must not re-enter the exchange delete (#1717)
    """

    org, ix, net = make_exchange("IX Cascade", asn=64518)
    prefix = add_prefix(ix.ixlan, "198.51.110.0/24")
    pending = add_prefix(ix.ixlan, "198.51.111.0/24", status="pending")

    ix.delete()

    ix.refresh_from_db()
    prefix.refresh_from_db()
    pending.refresh_from_db()

    assert ix.status == "deleted"
    assert prefix.status == "deleted"
    assert pending.status == "deleted"


@pytest.mark.django_db
def test_ixlan_delete_cascade_does_not_delete_exchange():
    """
    deleting the ixlan cascades into its prefixes, which is a cascade rather
    than an operator removing a prefix, and must leave the exchange (#1717)
    """

    org, ix, net = make_exchange("IX IXLan Cascade", asn=64522)
    prefix_v4 = add_prefix(ix.ixlan, "198.51.116.0/24")
    prefix_v6 = add_prefix(ix.ixlan, "2001:db8:116::/64", protocol="IPv6")

    ix.ixlan.delete()

    ix.refresh_from_db()
    prefix_v4.refresh_from_db()
    prefix_v6.refresh_from_db()

    assert prefix_v4.status == "deleted"
    assert prefix_v6.status == "deleted"
    assert ix.status == "ok"


@pytest.mark.django_db
def test_org_delete_cascade_does_not_recurse():
    """
    the same holds for an organization delete cascading down to the
    prefixes (#1717)
    """

    org, ix, net = make_exchange("IX Org Cascade", asn=64519)
    prefix = add_prefix(ix.ixlan, "198.51.112.0/24")
    net.delete()

    # an org with an active exchange under it is only deletable by an
    # administrative override, which is how this cascade is reached
    org.delete(force=True)

    org.refresh_from_db()
    ix.refresh_from_db()
    prefix.refresh_from_db()

    assert org.status == "deleted"
    assert ix.status == "deleted"
    assert prefix.status == "deleted"


@pytest.mark.django_db
def test_renumbering_keeps_exchange_listed():
    """
    pdb_renumber_lans activates the replacement prefix before deleting the
    old one, so the exchange never looks prefix-less (#1717)
    """

    org, ix, net = make_exchange("IX Renumber", asn=64520)
    old = add_prefix(ix.ixlan, "198.51.113.0/24")
    # the command only takes its delete-and-reassign branch when the target
    # prefix already exists in a soft-deleted state
    add_prefix(ix.ixlan, "198.51.114.0/24", status="deleted")

    call_command(
        "pdb_renumber_lans",
        str(ix.id),
        "198.51.113.0/24",
        "198.51.114.0/24",
        "--commit",
    )

    ix.refresh_from_db()
    old.refresh_from_db()

    assert old.status == "deleted"
    assert ix.status == "ok"
    assert ix.ixlan.ixpfx_set_active.count() == 1


@pytest.mark.django_db
def test_already_deleted_prefix_is_not_a_last_prefix():
    """
    re-deleting an already deleted prefix is a no-op for the exchange
    (#1717)
    """

    org, ix, net = make_exchange("IX Redelete", asn=64521)
    prefix = add_prefix(ix.ixlan, "198.51.115.0/24", status="deleted")

    assert prefix.is_last_prefix is False

    prefix.delete()

    ix.refresh_from_db()
    assert ix.status == "ok"
