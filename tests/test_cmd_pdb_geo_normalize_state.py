import copy

import reversion
from django.core.management import call_command

from peeringdb_server.models import Facility, Organization

from .util import ClientCase


class TestGeoNormalizeState(ClientCase):
    @classmethod
    def setUpTestData(self):
        super().setUpTestData()
        self.facilities = [
            {
                "name": "Facility 1",
                "city": "Ashburn",
                "state": "Virginia",
                "new_state": "VA",
                "country": "US",
            },
            {
                "name": "Facility 2",
                "city": "San Francisco",
                "state": "California",
                "new_state": "CA",
                "country": "US",
            },
            {
                "name": "Facility 3",
                "city": "Dallas",
                "state": "TX",
                "new_state": "TX",
                "country": "US",
            },
            {
                "name": "Facility 4",
                "city": "Toronto",
                "state": "Ontario",
                "new_state": "ON",
                "country": "CA",
            },
            {
                "name": "Facility 5",
                "city": "El Marques",
                "state": "Queretaro",
                "new_state": "Queretaro",
                "country": "MX",
            },
        ]
        with reversion.create_revision():
            self.org = Organization.objects.create(name="Test Org")
            facilities = copy.deepcopy(self.facilities)
            for facility in facilities:
                facility.pop("new_state")
                Facility.objects.create(**facility, status="ok", org=self.org)

    def test_run(self):
        call_command("pdb_geo_normalize_state", "fac", commit=True)
        for facility in self.facilities:
            assert Facility.objects.get(
                name=facility.get("name")
            ).state == facility.get("new_state")

    def test_run_without_reftag(self):
        with self.assertRaises(ValueError):
            call_command("pdb_geo_normalize_state")
