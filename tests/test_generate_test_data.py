from django.core.management import call_command
from django.test import TestCase

from peeringdb_server.models import REFTAG_MAP


class TestGenerateTestData(TestCase):
    def test_run(self):
        call_command("pdb_generate_test_data", limit=2, commit=True)
        for reftag, cls in list(REFTAG_MAP.items()):
            self.assertGreater(cls.objects.count(), 0)
            for instance in cls.objects.all():
                if hasattr(instance, "rir_status"):
                    print("RIR STATUS", instance.rir_status, type(instance.rir_status))
                instance.full_clean()
