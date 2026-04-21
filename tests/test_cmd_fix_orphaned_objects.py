import io

import pytest
import reversion
from django.core.management import call_command

from peeringdb_server.models import (
    Carrier,
    CarrierFacility,
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    IXLan,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkFacility,
    NetworkIXLan,
    Organization,
)


def run_command(commit=False):
    out = io.StringIO()
    kwargs = {"stdout": out}
    if commit:
        kwargs["commit"] = True
    call_command("pdb_fix_orphaned_objects", **kwargs)
    return out.getvalue()


# helpers to create orphaned records by bypassing model.delete()


def make_orphaned_carrierfac_via_fac():
    """carrierfac status=ok, parent fac status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org CarrierFac", status="ok")
        fac = Facility.objects.create(
            name="Fac CarrierFac", org=org, status="ok", city="City", country="US"
        )
        carrier = Carrier.objects.create(name="Carrier CarrierFac", org=org, status="ok")
        carrierfac = CarrierFacility.objects.create(
            carrier=carrier, facility=fac, status="ok"
        )

    # bypass model.delete() to simulate missing cascade
    fac.status = "deleted"
    fac.save()

    return carrierfac, fac


def make_orphaned_carrier_via_org():
    """carrier status=ok, parent org status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org Carrier", status="ok")
        carrier = Carrier.objects.create(name="Carrier Org", org=org, status="ok")

    org.status = "deleted"
    org.save()

    return carrier, org


def make_orphaned_net_via_org():
    """net status=ok, parent org status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org Net", status="ok")
        net = Network.objects.create(name="Net Org", asn=64500, org=org, status="ok")

    org.status = "deleted"
    org.save()

    return net, org


def make_orphaned_netfac_via_fac():
    """netfac status=ok, parent fac status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org NetFac", status="ok")
        fac = Facility.objects.create(
            name="Fac NetFac", org=org, status="ok", city="City", country="US"
        )
        net = Network.objects.create(name="Net NetFac", asn=64501, org=org, status="ok")
        netfac = NetworkFacility.objects.create(network=net, facility=fac, status="ok")

    fac.status = "deleted"
    fac.save()

    return netfac, fac


def make_orphaned_ixpfx_via_ixlan():
    """ixpfx status=ok, parent ixlan status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org IXPfx", status="ok")
        ix = InternetExchange.objects.create(
            name="IX IXPfx", org=org, status="ok", tech_email="ix@test.com"
        )
        ixlan = ix.ixlan
        ixpfx = IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="198.51.100.0/24", protocol="IPv4"
        )

    ixlan.status = "deleted"
    ixlan.save()

    return ixpfx, ixlan


def make_orphaned_ixfac_via_fac():
    """ixfac status=ok, parent fac status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org IXFac", status="ok")
        ix = InternetExchange.objects.create(
            name="IX IXFac", org=org, status="ok", tech_email="ixfac@test.com"
        )
        fac = Facility.objects.create(
            name="Fac IXFac", org=org, status="ok", city="City", country="US"
        )
        ixfac = InternetExchangeFacility.objects.create(
            ix=ix, facility=fac, status="ok"
        )

    fac.status = "deleted"
    fac.save()

    return ixfac, fac


def make_orphaned_ixlan_via_ix():
    """ixlan status=ok, parent ix status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org IXLan", status="ok")
        ix = InternetExchange.objects.create(
            name="IX IXLan", org=org, status="ok", tech_email="ixlan@test.com"
        )
        ixlan = ix.ixlan

    ix.status = "deleted"
    ix.save()

    return ixlan, ix


def make_orphaned_ixlan_with_protected_ixpfx():
    """
    ixlan status=ok, parent ix status=deleted, with an ixpfx and a netixlan
    whose IP falls inside the prefix.

    Without forced_ixlan_deletion, ixpfx.deletable returns False (active
    netixlan in prefix) -> ProtectedAction blocks the cascade. The command
    must open the forced_ixlan_deletion context to proceed.
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Org IXLan Protected", status="ok")
        ix = InternetExchange.objects.create(
            name="IX IXLan Protected", org=org, status="ok", tech_email="ixlanp@test.com"
        )
        net = Network.objects.create(
            name="Net IXLan Protected", asn=64506, org=org, status="ok"
        )
        ixlan = ix.ixlan
        ixpfx = IXLanPrefix.objects.create(
            ixlan=ixlan, status="ok", prefix="203.0.113.0/24", protocol="IPv4"
        )
        netixlan = NetworkIXLan.objects.create(
            network=net,
            ixlan=ixlan,
            asn=64506,
            status="ok",
            speed=1000,
            ipaddr4="203.0.113.1",
        )

    # Use QuerySet.update() to bypass InternetExchange.save(), which would
    # otherwise call ixlan.delete() and trigger the cascade we're simulating
    # as missing (the orphaned condition we want to test).
    InternetExchange.objects.filter(pk=ix.pk).update(status="deleted")

    return ixlan, ixpfx, netixlan


def make_orphaned_netixlan_via_ixlan():
    """netixlan status=ok, parent ixlan status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org NetIXLan", status="ok")
        ix = InternetExchange.objects.create(
            name="IX NetIXLan", org=org, status="ok", tech_email="netixlan@test.com"
        )
        net = Network.objects.create(
            name="Net NetIXLan", asn=64503, org=org, status="ok"
        )
        ixlan = ix.ixlan
        netixlan = NetworkIXLan.objects.create(
            network=net, ixlan=ixlan, asn=64503, status="ok", speed=1000
        )

    ixlan.status = "deleted"
    ixlan.save()

    return netixlan, ixlan


def make_orphaned_netixlan_via_network():
    """netixlan status=ok, parent network status=deleted (alternate parent path)"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org NetIXLan Net", status="ok")
        ix = InternetExchange.objects.create(
            name="IX NetIXLan Net", org=org, status="ok", tech_email="netixlannet@test.com"
        )
        net = Network.objects.create(
            name="Net NetIXLan Net", asn=64504, org=org, status="ok"
        )
        ixlan = ix.ixlan
        netixlan = NetworkIXLan.objects.create(
            network=net, ixlan=ixlan, asn=64504, status="ok", speed=1000
        )

    net.status = "deleted"
    net.save()

    return netixlan, net


def make_orphaned_poc_via_network():
    """poc status=ok, parent network status=deleted"""
    with reversion.create_revision():
        org = Organization.objects.create(name="Org POC", status="ok")
        net = Network.objects.create(name="Net POC", asn=64505, org=org, status="ok")
        poc = NetworkContact.objects.create(
            network=net, status="ok", role="Policy", name="Test Contact", email="poc@test.com"
        )

    net.status = "deleted"
    net.save()

    return poc, net


# --- pretend mode tests ---


@pytest.mark.django_db
def test_pretend_mode_no_changes():
    """Running without --commit should not modify any records."""
    carrierfac, fac = make_orphaned_carrierfac_via_fac()

    output = run_command(commit=False)

    assert "[pretend]" in output
    carrierfac.refresh_from_db()
    assert carrierfac.status == "ok"


# --- commit mode tests ---


@pytest.mark.django_db
def test_fix_carrierfac_orphaned_by_deleted_fac():
    """carrierfac with deleted parent fac should be soft-deleted."""
    carrierfac, fac = make_orphaned_carrierfac_via_fac()

    run_command(commit=True)

    carrierfac.refresh_from_db()
    assert carrierfac.status == "deleted"


@pytest.mark.django_db
def test_fix_carrier_orphaned_by_deleted_org():
    """carrier with deleted parent org should be soft-deleted."""
    carrier, org = make_orphaned_carrier_via_org()

    run_command(commit=True)

    carrier.refresh_from_db()
    assert carrier.status == "deleted"


@pytest.mark.django_db
def test_fix_net_orphaned_by_deleted_org():
    """net with deleted parent org should be soft-deleted."""
    net, org = make_orphaned_net_via_org()

    run_command(commit=True)

    net.refresh_from_db()
    assert net.status == "deleted"


@pytest.mark.django_db
def test_fix_netfac_orphaned_by_deleted_fac():
    """netfac with deleted parent fac should be soft-deleted."""
    netfac, fac = make_orphaned_netfac_via_fac()

    run_command(commit=True)

    netfac.refresh_from_db()
    assert netfac.status == "deleted"


@pytest.mark.django_db
def test_fix_ixlan_orphaned_by_deleted_ix():
    """ixlan with deleted parent ix should be soft-deleted."""
    ixlan, ix = make_orphaned_ixlan_via_ix()

    run_command(commit=True)

    ixlan.refresh_from_db()
    assert ixlan.status == "deleted"


@pytest.mark.django_db
def test_fix_ixlan_with_protected_ixpfx_uses_forced_context():
    """
    Orphaned IXLan with an ixpfx protected by an active netixlan (IP inside prefix)
    must be fully cascade-deleted by the command via forced_ixlan_deletion.

    Without the context bypass, ixpfx.deletable returns False and raises
    ProtectedAction, leaving the ixlan, ixpfx, and netixlan as orphans.
    """
    ixlan, ixpfx, netixlan = make_orphaned_ixlan_with_protected_ixpfx()

    run_command(commit=True)

    ixlan.refresh_from_db()
    ixpfx.refresh_from_db()
    netixlan.refresh_from_db()

    assert ixlan.status == "deleted"
    assert ixpfx.status == "deleted"
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_fix_ixpfx_orphaned_by_deleted_ixlan():
    """ixpfx with deleted parent ixlan should be soft-deleted."""
    ixpfx, ixlan = make_orphaned_ixpfx_via_ixlan()

    run_command(commit=True)

    ixpfx.refresh_from_db()
    assert ixpfx.status == "deleted"


@pytest.mark.django_db
def test_fix_ixfac_orphaned_by_deleted_fac():
    """ixfac with deleted parent fac should be soft-deleted."""
    ixfac, fac = make_orphaned_ixfac_via_fac()

    run_command(commit=True)

    ixfac.refresh_from_db()
    assert ixfac.status == "deleted"


@pytest.mark.django_db
def test_fix_netixlan_orphaned_by_deleted_ixlan():
    """netixlan with deleted parent ixlan should be soft-deleted."""
    netixlan, ixlan = make_orphaned_netixlan_via_ixlan()

    run_command(commit=True)

    netixlan.refresh_from_db()
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_fix_netixlan_orphaned_by_deleted_network():
    """netixlan with deleted parent network (alternate parent path) should be soft-deleted."""
    netixlan, net = make_orphaned_netixlan_via_network()

    run_command(commit=True)

    netixlan.refresh_from_db()
    assert netixlan.status == "deleted"


@pytest.mark.django_db
def test_fix_poc_orphaned_by_deleted_network():
    """poc with deleted parent network should be soft-deleted."""
    poc, net = make_orphaned_poc_via_network()

    run_command(commit=True)

    poc.refresh_from_db()
    assert poc.status == "deleted"


@pytest.mark.django_db
def test_clean_records_untouched():
    """Records with active parents should not be touched."""
    with reversion.create_revision():
        org = Organization.objects.create(name="Healthy Org", status="ok")
        fac = Facility.objects.create(
            name="Healthy Fac", org=org, status="ok", city="City", country="US"
        )
        carrier = Carrier.objects.create(name="Healthy Carrier", org=org, status="ok")
        carrierfac = CarrierFacility.objects.create(
            carrier=carrier, facility=fac, status="ok"
        )

    run_command(commit=True)

    carrierfac.refresh_from_db()
    fac.refresh_from_db()
    carrier.refresh_from_db()
    org.refresh_from_db()

    assert carrierfac.status == "ok"
    assert fac.status == "ok"
    assert carrier.status == "ok"
    assert org.status == "ok"
