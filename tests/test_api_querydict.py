"""
Tests for immutable QueryDict handling in API PUT/POST requests.

When requests use form-encoded data (multipart) instead of JSON,
request.data is an immutable QueryDict. Serializers that modify
data in to_internal_value() or run_validation() must handle this.

Regression tests for: AttributeError: This QueryDict instance is immutable
"""

import json

from allauth.account.models import EmailAddress
from rest_framework.test import APIClient

from peeringdb_server.models import REFTAG_MAP, User

from .test_api import setup_module, teardown_module  # noqa
from .util import ClientCase


class TestQueryDictImmutability(ClientCase):
    """
    Test that API endpoints handle immutable QueryDict from form-encoded requests.

    When a PUT/POST is sent with multipart/form-data encoding (not JSON),
    Django's request.data is an immutable QueryDict. Serializers must not
    attempt to modify it in-place.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.superuser = User.objects.create_user(
            "su", "su@localhost", "su", is_superuser=True
        )
        EmailAddress.objects.create(
            user=cls.superuser, email="su@localhost", verified=True, primary=True
        )
        cls.org = REFTAG_MAP["org"].objects.create(name="Test Org", status="ok")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.superuser)

    def test_network_put_with_form_data(self):
        """
        PUT to /api/net/{id} with form-encoded data should not raise
        AttributeError on immutable QueryDict.

        NetworkSerializer.to_internal_value modifies data["asn"] which
        fails when data is an immutable QueryDict.
        """
        # Create network directly in DB to avoid RDAP validation during setup
        net = REFTAG_MAP["net"].objects.create(
            name="Test Network",
            asn=9000000,
            org=self.org,
            status="ok",
        )

        # PUT with form-encoded data (multipart) — this triggers the bug
        # because request.data will be an immutable QueryDict.
        # May fail for RDAP validation reasons, but must not raise
        # AttributeError (500) from QueryDict immutability.
        r = self.client.put(
            f"/api/net/{net.id}",
            {
                "org_id": self.org.id,
                "name": "Updated Network",
                "asn": 9000000,
                "website": "https://www.example.com",
            },
            format="multipart",
        )
        assert (
            r.status_code != 500
        ), f"PUT with form data caused server error: {r.content}"

    def test_network_post_with_form_data(self):
        """
        POST to /api/net with form-encoded data should not raise
        AttributeError on immutable QueryDict.

        NetworkSerializer.to_internal_value modifies data["asn"] which
        fails when data is an immutable QueryDict.
        """
        # May fail for RDAP validation reasons, but must not raise
        # AttributeError (500) from QueryDict immutability.
        r = self.client.post(
            "/api/net",
            {
                "org_id": self.org.id,
                "name": "Test Network Form",
                "asn": 9000001,
                "website": "https://www.example.com",
            },
            format="multipart",
        )
        assert (
            r.status_code != 500
        ), f"POST with form data caused server error: {r.content}"

    def test_facility_post_with_form_data_suggest(self):
        """
        POST to /api/fac with form-encoded data and 'suggest' keyword should
        not raise AttributeError on immutable QueryDict.

        FacilitySerializer.to_internal_value modifies data["org_id"] when
        'suggest' is present, which fails with an immutable QueryDict.
        """
        r = self.client.post(
            "/api/fac",
            {
                "org_id": self.org.id,
                "name": "Test Facility",
                "website": "https://www.example.com",
                "address1": "123 Test St",
                "city": "Testville",
                "country": "US",
                "state": "CA",
                "zipcode": "90210",
                "suggest": "1",
            },
            format="multipart",
        )
        # Should not raise AttributeError
        assert (
            r.status_code != 500
        ), f"POST suggest with form data caused server error: {r.content}"

    def test_network_post_with_form_data_suggest(self):
        """
        POST to /api/net with form-encoded data and 'suggest' keyword should
        not raise AttributeError on immutable QueryDict.

        NetworkSerializer.to_internal_value modifies data["org_id"] when
        'suggest' is present, which fails with an immutable QueryDict.
        """
        r = self.client.post(
            "/api/net",
            {
                "org_id": self.org.id,
                "name": "Test Network Suggest",
                "asn": 9000002,
                "website": "https://www.example.com",
                "suggest": "1",
            },
            format="multipart",
        )
        # Should not raise AttributeError
        assert (
            r.status_code != 500
        ), f"POST suggest with form data caused server error: {r.content}"
