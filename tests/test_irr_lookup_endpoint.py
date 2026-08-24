"""
Tests for the smart-editor IRR lookup endpoint GET /data/irr_lookup (#1973).

The endpoint is a convenience helper for the as-set editor; the save-path
validator is the actual enforcement. These tests mock the lookup service so no
network calls are made.

It sits under /data/ with the other editor JSON helpers rather than under /api/:
it is website-only and carries none of the API's conventions.
"""

import base64
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient

from peeringdb_server.irr import LookupResult
from peeringdb_server.models import User
from peeringdb_server.rest import IRRLookupView
from peeringdb_server.rest_throttles import IRRLookupThrottle


class IRRLookupEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            "editor", "editor@localhost", first_name="editor", last_name="editor"
        )
        self.url = reverse("data-irr-lookup")

    @mock.patch("peeringdb_server.irr.sources_for")
    def test_lookup_authenticated(self, sources_for):
        # deliberately unsorted to prove the view sorts the source list
        sources_for.return_value = LookupResult(["RIPE", "RADB"], True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"name": "AS-FOO"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # flat JSON, not the API's {"data": [...], "meta": {}} envelope
        self.assertEqual(
            data, {"name": "AS-FOO", "sources": ["RADB", "RIPE"], "ok": True}
        )
        self.assertNotIn("data", data)
        self.assertNotIn("meta", data)
        sources_for.assert_called_once_with("AS-FOO")

    @mock.patch("peeringdb_server.irr.sources_for")
    def test_lookup_requires_auth(self, sources_for):
        response = self.client.get(self.url, {"name": "AS-FOO"})

        self.assertIn(response.status_code, (401, 403))
        sources_for.assert_not_called()

    @mock.patch("peeringdb_server.irr.sources_for")
    def test_lookup_empty_name_short_circuits(self, sources_for):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"name": "", "sources": [], "ok": False})
        # no name -> the pool is never queried
        sources_for.assert_not_called()

    @mock.patch("peeringdb_server.irr.sources_for")
    def test_lookup_pool_unreachable_reports_not_ok(self, sources_for):
        # fail-open: pool could not answer -> ok=False so the editor can tell
        # "found nowhere" (ok, empty) apart from "unknown" (not ok)
        sources_for.return_value = LookupResult([], False)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"name": "AS-BAR"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"name": "AS-BAR", "sources": [], "ok": False}
        )

    @mock.patch("peeringdb_server.irr.sources_for")
    def test_lookup_strips_whitespace(self, sources_for):
        sources_for.return_value = LookupResult(["RADB"], True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"name": "  AS-FOO  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "AS-FOO")
        sources_for.assert_called_once_with("AS-FOO")

    def test_endpoint_is_not_on_the_api_path(self):
        # website-only helper, so it lives with the other editor JSON views under
        # /data/ and is absent from the API url namespace entirely
        self.assertTrue(self.url.startswith("/data/"))
        with self.assertRaises(NoReverseMatch):
            reverse("api:irr-lookup")

    def test_throttle_attached(self):
        # the endpoint must be rate-limited (not a free IRR query proxy)
        self.assertIn(IRRLookupThrottle, IRRLookupView.throttle_classes)

    def test_session_authentication_only(self):
        # website-only by design: leaving Basic auth on would make this reachable
        # with any confirmed account's credentials, not just the editor session
        self.assertEqual(IRRLookupView.authentication_classes, [SessionAuthentication])

    def test_basic_auth_is_rejected(self):
        credentials = base64.b64encode(b"editor:secret").decode()
        response = self.client.get(
            self.url,
            {"name": "AS-FOO"},
            HTTP_AUTHORIZATION=f"Basic {credentials}",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_throttle_rate_is_sized_for_the_widget(self):
        # a 750ms-debounced completion widget needs a fraction of what the
        # endpoint used to allow (60/min); the configured rate must stay low so
        # many accounts cannot add up to a usable bulk IRR query service
        requests, _period = settings.API_THROTTLE_IRR_LOOKUP.split("/")
        self.assertLessEqual(int(requests), 20)
