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

@pytest.mark.django_db
def test_org_protection(db):

    """
    test that organization cannot be deleted if it
    has live entities under it
    """

    call_command("pdb_generate_test_data", limit=3, commit=True)
    org = Organization.objects.first()

    assert org.deletable == False
    assert org.not_deletable_reason == "Organization currently has one or more active objects under it."

    with pytest.raises(ProtectedAction):
        org.delete()

    for net in org.net_set_active.all():
        net.delete()

    for ix in org.ix_set_active.all():
        ix.delete()

    for fac in org.fac_set_active.all():
        fac.delete()

    org.delete()


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

