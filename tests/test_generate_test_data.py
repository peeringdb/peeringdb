from django.test import TestCase

from django.core.management import call_command

from peeringdb_server.models import REFTAG_MAP


class TestGenerateTestData(TestCase):
    def test_run(self):
        call_command("pdb_generate_test_data", limit=2, commit=True)
        for reftag, cls in REFTAG_MAP.items():
            self.assertGreater(cls.objects.count(), 0)
            for instance in cls.objects.all():
                instance.full_clean()
