"""
Mixin for Elasticsearch-dependent API tests.

This mixin provides test methods that depend on Elasticsearch being available
and properly indexed. All tests are marked with @pytest.mark.xdist_group to
ensure they run sequentially and avoid index conflicts during parallel test runs.
"""

from unittest.mock import patch

import pytest

import peeringdb_server.models as models
from peeringdb_server.management.commands.pdb_api_test import SHARED


class ElasticsearchAPIMixin:
    """
    Mixin providing Elasticsearch-dependent test methods.

    Classes using this mixin must inherit from api_test.Command to have
    access to methods like make_data_fac(), reindex_for_search(), etc.
    """

    @pytest.mark.xdist_group(name="elasticsearch_tests")
    def test_user_001_GET_fac_spatial_search_with_name_search_requires_es(self):
        """Test facility API spatial search with name_search parameter that triggers ES lookup."""
        fac_data = self.make_data_fac(
            name="Chicago Data Center",
            city="Chicago",
            state="IL",
            country="US",
            latitude=41.8781,
            longitude=-87.6298,
        )
        facility = models.Facility.objects.create(status="ok", **fac_data)
        self.reindex_for_search()

        # Mock the Google geocoding API to return coordinates for Chicago
        with patch("peeringdb_server.models.geo.GoogleMaps") as mock_gmaps:
            mock_gmaps.return_value.geocode_address.return_value = {
                "lat": 41.8781,
                "lng": -87.6298,
            }

            response = self.db_user._request(
                f"fac?name_search={facility.name}&distance=50", method="GET"
            )
            self.assertEqual(response.status_code, 200)

            data = response.json()
            facility_names = [f["name"] for f in data["data"]]
            self.assertIn(facility.name, facility_names)

        facility.delete(hard=True)

    @pytest.mark.xdist_group(name="elasticsearch_tests")
    def test_guest_005_list_filter_ix_name_search(self):
        """Test IX name_search via Elasticsearch."""
        ix = models.InternetExchange.objects.create(
            status="ok",
            **self.make_data_ix(
                name="Specific Exchange", name_long="This is a very specific exchange"
            ),
        )

        self.reindex_for_search()

        data = self.db_guest.all("ix", name_search=ix.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], ix.id)

        data = self.db_guest.all("ix", name_search=ix.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], ix.id)

        ix.delete(hard=True)

    @pytest.mark.xdist_group(name="elasticsearch_tests")
    def test_guest_005_list_filter_fac_name_search(self):
        """Test facility name_search via Elasticsearch."""
        fac = models.Facility.objects.create(
            status="ok",
            **self.make_data_fac(
                name="Specific Facility", name_long="This is a very specific facility"
            ),
        )

        self.reindex_for_search()

        data = self.db_guest.all("fac", name_search=fac.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        data = self.db_guest.all("fac", name_search=fac.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        fac.delete(hard=True)

    @pytest.mark.xdist_group(name="elasticsearch_tests")
    def test_guest_005_list_filter_carrier_name_search(self):
        """Test carrier name_search via Elasticsearch."""

        carrier = models.Carrier.objects.create(
            status="ok",
            **self.make_data_carrier(
                name="Specific Carrier", name_long="This is a very specific carrier"
            ),
        )

        # Add facility to carrier using CarrierFacility
        models.CarrierFacility.objects.create(
            carrier=carrier, facility=SHARED["fac_r_ok"], status="ok"
        )

        self.reindex_for_search()

        data = self.db_guest.all("carrier", name_search=carrier.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], carrier.id)

        data = self.db_guest.all("carrier", name_search=carrier.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], carrier.id)

        carrier.delete(hard=True)

    @pytest.mark.xdist_group(name="elasticsearch_tests")
    def test_readonly_users_004_list_filter_fac_name_search(self):
        """Test facility name_search for readonly users via Elasticsearch."""
        fac = models.Facility.objects.create(
            status="ok",
            **self.make_data_fac(
                name="Specific Facility", name_long="This is a very specific facility"
            ),
        )

        self.reindex_for_search()

        data = self.db_guest.all("fac", name_search=fac.name)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        data = self.db_guest.all("fac", name_search=fac.name_long)
        self.assertEqual(len(data), 1)
        for row in data:
            self.assertEqual(row["id"], fac.id)

        fac.delete(hard=True)
