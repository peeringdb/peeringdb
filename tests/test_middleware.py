import base64

from django.http import HttpResponse
from django.test import (
    RequestFactory,
    SimpleTestCase,
    modify_settings,
    override_settings,
)
from rest_framework.test import APIClient, APITestCase

from peeringdb_server.middleware import PDBCommonMiddleware
from peeringdb_server.models import Organization, OrganizationAPIKey, User, UserAPIKey
from .util import reset_group_ids


def get_response_empty(request):
    return HttpResponse()


@override_settings(ROOT_URLCONF="middleware.urls")
class PDBCommonMiddlewareTest(SimpleTestCase):

    rf = RequestFactory()

    @override_settings(PDB_PREPEND_WWW=True)
    def test_prepend_www(self):
        request = self.rf.get("/path/")
        r = PDBCommonMiddleware(get_response_empty).process_request(request)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.url, "http://www.testserver/path/")


@modify_settings(
    MIDDLEWARE={
        "append": "peeringdb_server.middleware.PDBPermissionMiddleware",
    }
)
class PDBPermissionMiddlewareTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.factory = RequestFactory()

    def test_bogus_apikey_auth_id_response(self):
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key bogus")
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("X-Auth-ID"), "apikey_bogus")

    def test_bogus_credentials_auth_id_response(self):
        self.client.credentials(HTTP_AUTHORIZATION="Basic Ym9ndXM6Ym9ndXM=")
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("X-Auth-ID"), "bogus")

    def test_auth_id_api_key(self):
        user = User.objects.create(username="test_user")
        user.set_password("test_user")
        user.save()

        # Create an API key for the user
        api_key, key = UserAPIKey.objects.create_key(
            name="test",
            user=user,
            readonly=False,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert (
            response.headers.get("X-Auth-ID") == f"u{user.id}_apikey_{api_key.prefix}"
        )

        # test that header gets cleared between requests
        other_client = APIClient()
        response = other_client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") is None

    def test_auth_id_org_api_key(self):
        reset_group_ids()

        org = Organization.objects.create(name="Test org", status="ok")

        # Create an API key for the user
        api_key, key = OrganizationAPIKey.objects.create_key(
            name="test",
            org=org,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") == f"o{org.id}_apikey_{api_key.prefix}"

        # test that header gets cleared between requests
        other_client = APIClient()
        response = other_client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") is None

    def test_auth_id_session_auth(self):
        user = User.objects.create(username="test_user")
        user.set_password("test_user")
        user.save()

        self.client.force_login(user)
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") == f"u{user.id}"

        # test that header gets cleared between requests
        other_client = APIClient()
        response = other_client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") is None

    def test_auth_id_basic_auth(self):
        user = User.objects.create(username="test_user")
        user.set_password("test_user")
        user.save()

        auth = base64.b64encode(b"test_user:test_user").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {auth}")

        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") == f"u{user.id}"

        # test that header gets cleared between requests
        other_client = APIClient()
        response = other_client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID") is None
