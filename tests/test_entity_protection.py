import datetime

import pytest
from django.core.management import call_command

from peeringdb_server.models import (
    UTC,
    Network,
    NetworkContact,
    Organization,
    ProtectedAction,
    Sponsorship,
    SponsorshipOrganization,
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

    poc2 = NetworkContact.objects.create(status="ok", role=role, network=net)

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

    assert org.deletable == False
    assert "Organization is currently an active sponsor" in org.not_deletable_reason

    with pytest.raises(ProtectedAction):
        org.delete()

    sponsor.delete()

    org.delete()
