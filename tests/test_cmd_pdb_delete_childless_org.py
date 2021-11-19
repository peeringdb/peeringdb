import io
from datetime import timedelta

from django.db.transaction import commit

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import Organization, Network, InternetExchange, Facility, Sponsorship

from .util import ClientCase, Group


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
        net = Network.objects.filter(org=org).delete()
        ix = InternetExchange.objects.filter(org=org).delete()
        fac = Facility.objects.filter(org=org).delete()

        # Check if org is childless and can be deleted
        assert org.deletable

        call_command("pdb_delete_childless_org", commit=True)

        org = Organization.objects.filter(id=org.id).first()

        # Check if org was flagged and deleted
        assert org.flagged
        assert org.status == "deleted"


    def test_cmd_delete_childless_org_ignore_sponsors(self):

        dt = timezone.now() - timedelta(days=settings.ORG_CHILDLESS_DELETE_DURATION + 1)

        org_current_sponsor = Organization.objects.create(
            name="Current sponsor", status="ok"
        )
        org_past_sponsor = Organization.objects.create(
            name="Past sponsor", status="ok"
        )
        org_future_sponsor = Organization.objects.create(
            name="Future sponsor", status="ok"
        )

        now = timezone.now()

        current_sponsor = Sponsorship.objects.create(
            start_date = now - timedelta(days=1),
            end_date = now + timedelta(days=1),
        )
        current_sponsor.orgs.add(org_current_sponsor)

        past_sponsor = Sponsorship.objects.create(
            start_date = now - timedelta(days=10),
            end_date = now - timedelta(days=5),
        )
        past_sponsor.orgs.add(org_past_sponsor)

        future_sponsor = Sponsorship.objects.create(
            start_date = now + timedelta(days=2),
            end_date = now + timedelta(days=5),
        )
        future_sponsor.orgs.add(org_future_sponsor)

        settings.ORG_CHILDLESS_GRACE_DURATION = 0

        call_command("pdb_delete_childless_org", commit=True)


        org_current_sponsor.refresh_from_db()
        org_past_sponsor.refresh_from_db()
        org_future_sponsor.refresh_from_db()

        assert not org_current_sponsor.flagged
        assert not org_past_sponsor.flagged
        assert not org_future_sponsor.flagged



