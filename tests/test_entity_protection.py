import datetime
import pytest

from django.core.management import call_command

from peeringdb_server.models import (
    Organization,
    Sponsorship,
    SponsorshipOrganization,
    ProtectedAction,
    UTC
)

@pytest.mark.djangodb
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

    def assert_protected(entity):
        """
        helper function to test that an object is currently
        not deletable
        """
        with pytest.raises(ProtectedAction):
            entity.delete()


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

        # process the prefixes under the exchange

        for ixpfx in ix.ixlan.ixpfx_set.all():

            # exchange has netixlans under it that fall
            # into the address space for the prefix so
            # the prefix is currently not deletable

            assert_protected(ixpfx)

        # process the netixlans under the exchange and
        # delete them

        for netixlan in ix.ixlan.netixlan_set.all():
            netixlan.delete()

        # with the netixlans gone, the prefixes can now
        # be deleted

        for ixpfx in ix.ixlan.ixpfx_set.all():
            ixpfx.delete()

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

    # delete nets

    for net in org.net_set.all():
        net.delete()

    # org is now deletable

    org.delete()
    assert org.status == "deleted"




@pytest.mark.django_db
def test_org_protection_sponsor(db):

    """
    test that organization cannot be deleted if it has
    an active sponsorship going
    """

    now = datetime.datetime.now().replace(tzinfo=UTC())

    org = Organization.objects.create(status="ok", name="SponsorOrg")
    sponsor = Sponsorship.objects.create(
        start_date = now - datetime.timedelta(days=1),
        end_date = now + datetime.timedelta(days=1)
    )
    sponsor.orgs.add(org)

    assert org.sponsorship.active

    assert org.deletable == False
    assert "Organization is currently an active sponsor" in org.not_deletable_reason

    with pytest.raises(ProtectedAction):
        org.delete()

    sponsor.delete()

    org.delete()

