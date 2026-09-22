"""
#1742 moved operational-ness out of the `operational` boolean and into
netixlan `status`, so a connection that used to be status="ok" with
operational=False is now status="not-operational".

Every count and lookup that previously matched those rows through
status="ok" has to match them through live_statuses() instead, or the
migration silently drops them. It produces no error -- the failure mode is
a wrong number.
"""

import pytest
from django.core.management import call_command

from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
)
from peeringdb_server.signals import update_counts_for_netixlan

# the autouse cleanup fixture clears the geo DatabaseCache, which hits the db
# before this module's own fixture would enable access
pytestmark = pytest.mark.django_db


@pytest.fixture
def ix_with_non_operational_peer():
    org = Organization.objects.create(name="Live Status Org", status="ok")
    ix = InternetExchange.objects.create(name="Live Status IX", org=org, status="ok")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, protocol="IPv4", prefix="198.51.100.0/24", status="ok"
    )
    net = Network.objects.create(
        name="Live Status Net", asn=64600, org=org, status="ok"
    )
    netixlan = NetworkIXLan.objects.create(
        network=net,
        ixlan=ix.ixlan,
        asn=net.asn,
        speed=1000,
        ipaddr4="198.51.100.10",
        status="not-operational",
    )
    ix.refresh_from_db()
    return ix, net, netixlan


def test_derived_network_count_counts_non_operational_peers(
    ix_with_non_operational_peer,
):
    """
    `deletable` is gated on this count. Counting only status="ok" would let
    an exchange whose peers are all non-operational be deleted.
    """
    ix, _, _ = ix_with_non_operational_peer

    assert ix.derived_network_count == 1
    assert ix.deletable is False
    assert "active peer" in str(ix._not_deletable_reason)


def test_derived_count_agrees_with_the_maintained_net_count(
    ix_with_non_operational_peer,
):
    """
    The ad hoc count exists to cross-check the signal-maintained one, so the
    two predicates must match. Driven directly here: the counts are normally
    maintained on post_revision_commit, which a plain create() does not fire.
    """
    ix, _, netixlan = ix_with_non_operational_peer

    update_counts_for_netixlan(netixlan)

    ix.refresh_from_db()
    assert ix.net_count == 1
    assert ix.net_count == ix.derived_network_count


def test_fix_net_counts_does_not_rewrite_a_correct_count(
    ix_with_non_operational_peer, capsys
):
    """
    The reconciliation command must use the same predicate as the signal it
    reconciles against -- otherwise it "corrects" a right answer to a wrong
    one, and does so with --commit.
    """
    ix, _, netixlan = ix_with_non_operational_peer
    update_counts_for_netixlan(netixlan)
    ix.refresh_from_db()
    assert ix.net_count == 1

    call_command("pdb_fix_net_counts", commit=True)

    ix.refresh_from_db()
    assert ix.net_count == 1


def test_overlapping_asns_sees_a_non_operational_connection(
    ix_with_non_operational_peer,
):
    """
    "which exchanges do these ASNs share" -- a declared but not-yet-live
    connection was visible here before #1742, because it was status="ok"
    with operational=False.
    """
    ix, net, _ = ix_with_non_operational_peer

    other = Network.objects.create(
        name="Live Status Peer", asn=64601, org=ix.org, status="ok"
    )
    NetworkIXLan.objects.create(
        network=other,
        ixlan=ix.ixlan,
        asn=other.asn,
        speed=1000,
        ipaddr4="198.51.100.11",
        status="ok",
    )

    shared = InternetExchange.overlapping_asns([net.asn, other.asn])

    assert ix.id in set(shared.values_list("id", flat=True))
