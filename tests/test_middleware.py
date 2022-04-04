from django.http import HttpResponse
from django.test import (
    RequestFactory,
    SimpleTestCase,
    override_settings,
    modify_settings,
)

from peeringdb_server.middleware import PDBCommonMiddleware
from peeringdb_server.models import User, UserAPIKey
from rest_framework.test import APITestCase
from rest_framework.test import APIClient


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

    client = APIClient()

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

    def test_auth_id_response(self):
        user = User.objects.create(username="bogus")
        user.set_password("bogus")
        user.save()

        # Create an API key for the user
        api_key, key = UserAPIKey.objects.create_key(
            name="test",
            user=user,
            readonly=False,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Api-Key %s" % key)
        response = self.client.get("/api/fac")
        self.assertEqual(response.status_code, 200)
        assert response.headers.get("X-Auth-ID").startswith("apikey_")
