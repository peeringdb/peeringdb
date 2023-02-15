import io
from datetime import timedelta

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.db.transaction import commit
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import Facility, InternetExchange, Network, Organization

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
