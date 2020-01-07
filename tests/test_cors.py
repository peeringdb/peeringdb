from django.test import TestCase, Client
from peeringdb_server.models import Organization, User
from .util import ClientCase
from corsheaders.middleware import (
    ACCESS_CONTROL_ALLOW_CREDENTIALS,
    ACCESS_CONTROL_ALLOW_HEADERS,
    ACCESS_CONTROL_ALLOW_METHODS,
    ACCESS_CONTROL_ALLOW_ORIGIN,
    ACCESS_CONTROL_EXPOSE_HEADERS,
    ACCESS_CONTROL_MAX_AGE,
)


class CorsTest(ClientCase):

    test_origin = "http://example.com"

    @classmethod
    def setUpTestData(cls):
        ClientCase.setUpTestData()
        cls.org = Organization.objects.create(name="Test", status="ok")

    def assert_cors_allowed(self, url, method):
        resp = Client().options(url, HTTP_ORIGIN=self.test_origin)
        self.assertIn(resp.status_code, [200, 301])
        self.assertIn(ACCESS_CONTROL_ALLOW_METHODS, resp)
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertIn(method.upper(), resp[ACCESS_CONTROL_ALLOW_METHODS].split(", "))
        self.assertIn("origin", resp[ACCESS_CONTROL_ALLOW_HEADERS].split(", "))
        self.assertEqual(resp[ACCESS_CONTROL_ALLOW_ORIGIN], self.test_origin)

    def assert_cors_denied(self, url, method):
        resp = Client().options(url, HTTP_ORIGIN=self.test_origin)
        self.assertIn(resp.status_code, [200, 301])

        if ACCESS_CONTROL_ALLOW_METHODS in resp:
            self.assertNotIn(
                method.upper(), resp[ACCESS_CONTROL_ALLOW_METHODS].split(", ")
            )

    def test_cors_GET(self):
        self.assert_cors_allowed("/api", method="get")
        self.assert_cors_allowed("/api/", method="get")
        self.assert_cors_allowed("/api/org/1", method="get")
        self.assert_cors_denied("/org/1", method="get")
        self.assert_cors_denied("/", method="get")

    def test_cors_POST(self):
        self.assert_cors_denied("/api", method="post")
        self.assert_cors_denied("/api/", method="post")
        self.assert_cors_denied("/api/org/1", method="post")
        self.assert_cors_denied("/org/1", method="post")
        self.assert_cors_denied("/", method="post")

    def test_cors_PUT(self):
        self.assert_cors_denied("/api", method="put")
        self.assert_cors_denied("/api/", method="put")
        self.assert_cors_denied("/api/org/1", method="put")
        self.assert_cors_denied("/org/1", method="put")
        self.assert_cors_denied("/", method="put")

    def test_cors_DELETE(self):
        self.assert_cors_denied("/api", method="delete")
        self.assert_cors_denied("/api/", method="delete")
        self.assert_cors_denied("/api/org/1", method="delete")
        self.assert_cors_denied("/org/1", method="delete")
        self.assert_cors_denied("/", method="delete")
