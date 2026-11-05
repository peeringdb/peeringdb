from datetime import timedelta

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from peeringdb_server.models import (
    Campus,
    Carrier,
    Facility,
    InternetExchange,
    Network,
    Organization,
)

from .util import ClientCase


class TestChildlessDeleteOrg(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with reversion.create_revision():
            call_command("pdb_generate_test_data", limit=1, commit=True)
            cls.org = Organization.objects.first()

    def test_cmd_delete_childless_org(self):
        dt = timezone.now() - timedelta(days=settings.ORG_CHILDLESS_DELETE_DURATION + 1)

        org = self.org

        # Set the date to days before the current date (based on settings.ORG_CHILDLESS_DELETE_DURATION)
        org.flagged_date = dt
        org.save()

        # delete child objects
        Network.objects.filter(org=org).delete()
        InternetExchange.objects.filter(org=org).delete()
        Facility.objects.filter(org=org).delete()
        Carrier.objects.filter(org=org).delete()
        Campus.objects.filter(org=org).delete()

        # Check if org is childless and can be deleted
        assert org.deletable

        call_command("pdb_delete_childless_org", commit=True)

        org = Organization.objects.filter(id=org.id).first()

        # Check if org was flagged and deleted
        assert org.flagged
        assert org.status == "deleted"


@pytest.mark.django_db
@pytest.mark.parametrize("model", (Carrier, Campus))
@pytest.mark.parametrize("status", ("ok", "pending"))
def test_cmd_delete_childless_org_keeps_carrier_and_campus_orgs(model, status):
    """
    An organization whose only object is a carrier or a campus is not
    childless (#525)
    """
    with reversion.create_revision():
        org = Organization.objects.create(name="Childless Org Test", status="ok")
        obj = model.objects.create(name="Childless Org Test Child", org=org)
    # a campus without facilities is reset to pending on save
    model.objects.filter(pk=obj.pk).update(status=status)
    Organization.objects.filter(pk=org.pk).update(
        created=timezone.now()
        - timedelta(days=settings.ORG_CHILDLESS_GRACE_DURATION + 1)
    )

    org.refresh_from_db()
    assert not org.is_empty
    if status == "ok":
        assert not org.deletable

    call_command("pdb_delete_childless_org", commit=True)
    org.refresh_from_db()
    assert not org.flagged

    # an organization flagged before the fix is unflagged, not deleted
    Organization.objects.filter(pk=org.pk).update(
        flagged=True,
        flagged_date=timezone.now()
        - timedelta(days=settings.ORG_CHILDLESS_DELETE_DURATION + 1),
    )
    call_command("pdb_delete_childless_org", commit=True)
    org.refresh_from_db()
    obj.refresh_from_db()
    assert org.status == "ok"
    assert not org.flagged
    assert obj.status == status
