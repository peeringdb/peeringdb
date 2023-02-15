import io
from datetime import timedelta

import pytest
import reversion
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from reversion.models import Version

from peeringdb_server.models import Network, NetworkContact

from .util import ClientCase, Group


class TestRenumberLans(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with reversion.create_revision():
            call_command("pdb_generate_test_data", limit=1, commit=True)
            cls.net = Network.objects.first()

            cls.poc_del = NetworkContact.objects.create(
                status="ok",
                network=cls.net,
                phone="123467",
                email="test@localhost",
                name="John Smith",
                url="http://www.example.com",
            )

    def test_run(self):
        # get current total count of pocs so we can
        # check against it later

        count = NetworkContact.objects.count()

        # need to manually set the updated field, so
        # turn auto_now off

        updated = self.poc_del._meta.get_field("updated")
        updated.auto_now = False

        dt = timezone.now() - timedelta(days=settings.POC_DELETION_PERIOD)

        # set updated value to be old enough that the
        # delet command recognizes it should be hard deleted
        # and also soft-delete the poc

        with reversion.create_revision():
            self.poc_del.updated = dt
            self.poc_del.delete()
            self.poc_del.refresh_from_db()

        # get current total count of reversion versions so
        # we can check against it later

        reversion_count = Version.objects.count()

        # poc should have 2 Version objects attached to it

        assert Version.objects.get_for_object(self.poc_del).count() == 2

        # poc should be soft-deleted

        assert self.poc_del.status == "deleted"

        # poc should be marked as updated in the past

        assert self.poc_del.updated == dt

        # run command to delete all old pocs

        call_command("pdb_delete_pocs", commit=True)

        # check that the poc has been hard deleted

        with pytest.raises(NetworkContact.DoesNotExist):
            self.poc_del.refresh_from_db()

        # total poc count should have gone down by 1

        assert NetworkContact.objects.count() == (count - 1)

        # version objects for the poc should be gone as well

        assert Version.objects.get_for_object(self.poc_del).count() == 0

        # no other version objects should have been touched

        assert Version.objects.count() == (reversion_count - 2)

        # set updated field to auto now again (otherwise it breaks
        # other tests)

        updated.auto_now = True
