import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from peeringdb_server.models import REFTAG_MAP, UTC

from .util import ClientCase, Group


class TestWipe(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.superuser = get_user_model().objects.create_user(
            "superuser", "superuser@localhost", "superuser", is_superuser=True
        )
        call_command("pdb_generate_test_data", limit=2, commit=True)

    def test_run(self):
        # double check that data is setup correctly before
        # running pdbwipe

        assert get_user_model().objects.all().count() == 2

        for reftag, cls in list(REFTAG_MAP.items()):
            assert cls.objects.all().count() > 1

        assert Group.objects.all().count() > 2

        # run pdb_wipe
        settings.TUTORIAL_MODE = True
        call_command("pdb_wipe", commit=True)
        settings.TUTORIAL_MODE = False

        # all entities should be gone
        for reftag, cls in list(REFTAG_MAP.items()):
            assert cls.objects.all().count() == 0

        # only the user and guest groups should be left
        assert Group.objects.all().count() == 2

        # only the superuser should be left
        assert get_user_model().objects.all().count() == 1
        assert get_user_model().objects.first().is_superuser == True

    @pytest.mark.django_db
    def test_run_with_sync(self):
        """
        Test running `pdb_wipe` and sync data from
        test.peeringdb.com
        """

        dates = {}

        for reftag, cls in REFTAG_MAP.items():
            assert cls.objects.all().count() > 1
            dates[reftag] = cls.objects.all().first().created.replace(tzinfo=UTC())

        settings.TUTORIAL_MODE = True
        call_command(
            "pdb_wipe",
            commit=True,
            load_data=True,
            load_data_url="https://test.peeringdb.com/api",
        )
        settings.TUTORIAL_MODE = False

        for reftag, cls in REFTAG_MAP.items():
            created = cls.objects.all().first().created.replace(tzinfo=UTC())
            assert created != dates[reftag]
            assert cls.objects.all().count() >= 1
