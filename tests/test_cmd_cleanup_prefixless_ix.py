import io

import pytest
from django.core.management import call_command

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLanPrefix,
    Network,
    NetworkIXLan,
    Organization,
)


def run_command(commit=False):
    out = io.StringIO()
    kwargs = {"stdout": out}
    if commit:
        kwargs["commit"] = True
    call_command("pdb_cleanup_prefixless_ix", **kwargs)
    return out.getvalue()


def make_exchange(name, status="ok"):
    org = Organization.objects.create(name=f"Org {name}", status="ok")
    ix = InternetExchange.objects.create(
        name=name, org=org, status=status, tech_email="ix@localhost"
    )
    return org, ix


@pytest.mark.django_db
def test_dry_run_changes_nothing():
    """
    the command is a preview unless --commit is passed
    """

    org, ix = make_exchange("IX Prefixless Dry Run")

    output = run_command()

    ix.refresh_from_db()

    assert ix.status == "ok"
    assert "[pretend]" in output
    assert f"ix-{ix.id}" in output


@pytest.mark.django_db
def test_commit_deletes_prefixless_exchange():
    """
    a listed exchange with no prefix does not meet the listing criteria and
    is soft-deleted (#1717)
    """

    org, ix = make_exchange("IX Prefixless")

    run_command(commit=True)

    ix.refresh_from_db()

    assert ix.status == "deleted"
    assert ix.ixlan.status == "deleted"


@pytest.mark.django_db
def test_exchange_with_prefix_is_left_alone():
    """
    an exchange that still has an active or pending prefix is untouched
    """

    org, ix_active = make_exchange("IX Has Prefix")
    IXLanPrefix.objects.create(
        ixlan=ix_active.ixlan, prefix="198.51.120.0/24", protocol="IPv4", status="ok"
    )

    org2, ix_pending = make_exchange("IX Has Pending Prefix")
    IXLanPrefix.objects.create(
        ixlan=ix_pending.ixlan,
        prefix="198.51.121.0/24",
        protocol="IPv4",
        status="pending",
    )

    output = run_command(commit=True)

    ix_active.refresh_from_db()
    ix_pending.refresh_from_db()

    assert ix_active.status == "ok"
    assert ix_pending.status == "ok"
    assert f"ix-{ix_active.id}" not in output
    assert f"ix-{ix_pending.id}" not in output


@pytest.mark.django_db
def test_pending_exchange_is_left_alone():
    """
    a pending exchange is not listed yet, so it is left for the admin
    committee rather than deleted here
    """

    org, ix = make_exchange("IX Prefixless Pending", status="pending")

    run_command(commit=True)

    ix.refresh_from_db()

    assert ix.status == "pending"


@pytest.mark.django_db
def test_peers_and_facility_connections_go_with_the_exchange():
    """
    the delete is forced past the exchange's own guards, the same as a
    confirmed last-prefix delete, and the output names what goes with it
    """

    org, ix = make_exchange("IX Prefixless Attached")
    net = Network.objects.create(
        name="Net Prefixless Attached", asn=64530, org=org, status="ok"
    )
    netixlan = NetworkIXLan.objects.create(
        network=net, ixlan=ix.ixlan, asn=net.asn, speed=1000, status="ok"
    )
    fac = Facility.objects.create(
        name="Fac Prefixless Attached",
        org=org,
        status="ok",
        city="City",
        country="US",
    )
    ixfac = InternetExchangeFacility.objects.create(ix=ix, facility=fac, status="ok")

    # the exchange is not directly deletable while either of those exists
    assert ix.deletable is False

    output = run_command(commit=True)

    ix.refresh_from_db()
    netixlan.refresh_from_db()
    ixfac.refresh_from_db()

    assert ix.status == "deleted"
    assert netixlan.status == "deleted"
    assert ixfac.status == "deleted"
    assert "1 active peer(s)" in output
    assert "1 active facility connection(s)" in output


@pytest.mark.django_db
def test_no_prefixless_exchanges():
    """
    nothing to do is reported rather than silently succeeding
    """

    org, ix = make_exchange("IX Nothing To Do")
    IXLanPrefix.objects.create(
        ixlan=ix.ixlan, prefix="198.51.122.0/24", protocol="IPv4", status="ok"
    )

    output = run_command(commit=True)

    assert "No prefix-less exchanges found" in output
