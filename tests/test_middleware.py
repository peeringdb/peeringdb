import base64
from unittest.mock import patch

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import (
    Client,
    RequestFactory,
    SimpleTestCase,
    modify_settings,
    override_settings,
)
from django.urls.resolvers import ResolverMatch
from rest_framework.response import Response
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


class RedisNegativeCacheMiddlewareTest(APITestCase):
    """
    Test case for RedisNegativeCacheMiddleware class
    """

    def setUp(self):
        self.client = APIClient()

    def test_inactive_user(self):
        """
        Test negative caching for inactive user
        """
        # Create an inactive user
        user = User.objects.create(username="inactive_user", is_active=False)
        user.set_password("inactive_user")
        user.save()

        # Prepare the credentials for the inactive user
        credentials = base64.b64encode(b"inactive_user:inactive_user").decode("utf-8")
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")

        # Send an initial request
        response = self.client.get("/api/fac")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 401

        # Send the same request again
        response = self.client.get("/api/fac")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 401

    def test_invalid_user(self):
        """
        Test negative caching for invalid user
        """
        # Send an initial request with invalid credentials
        self.client.credentials(
            HTTP_AUTHORIZATION="Basic Ym9ndXM6Ym9ndXM="
        )  # bogus:bogus
        response = self.client.get("/api/fac")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 401

        # Send the same request again
        response = self.client.get("/api/fac")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 401

    def test_invalid_api_key(self):
        """
        Test negative caching for invalid API key
        """
        # Send an initial request with invalid API key
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key bogus")
        response = self.client.get("/api/fac")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 401

        # Send the same request again
        response = self.client.get("/api/fac")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 401

    def test_inactive_api_key(self):
        """
        Test negative caching for inactive API key
        """
        # Create a user
        user = User.objects.create(username="test_user")
        user.set_password("test_user")
        user.save()

        # Create an inactive API key for the user
        api_key, key = UserAPIKey.objects.create_key(
            name="test",
            user=user,
            readonly=False,
        )
        api_key.status = "inactive"
        api_key.save()

        # Send an initial request with inactive API key
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response = self.client.get("/api/fac")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 401

        # Send the same request again
        response = self.client.get("/api/fac")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 401

    @patch(
        "peeringdb_server.rest.FacilityViewSet.list",
        return_value=Response({}, status=401),
    )
    def test_401_response(self, mock_list):
        """
        Test negative caching for 401 response
        """
        # Send an initial request
        response = self.client.get("/api/fac?test=1")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 401

        # Send the same request again
        response = self.client.get("/api/fac?test=1")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 401

    @patch(
        "peeringdb_server.rest.FacilityViewSet.list",
        return_value=Response({}, status=403),
    )
    def test_403_response(self, mock_list):
        """
        Test negative caching for 403 response
        """
        # Send an initial request
        response = self.client.get("/api/fac?test=2")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 403

        # Send the same request again
        response = self.client.get("/api/fac?test=2")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 403

    @patch(
        "peeringdb_server.rest.FacilityViewSet.list",
        return_value=Response({}, status=429),
    )
    def test_429_response(self, mock_list):
        """
        Test negative caching for 429 response
        """
        # Send an initial request
        response = self.client.get("/api/fac?test=3")
        # Test that cache wasn't used
        self.assertIsNone(response.headers.get("X-Cached-Response"))
        assert response.status_code == 429

        # Send the same request again
        response = self.client.get("/api/fac?test=3")
        # Test that the cache was used
        self.assertEqual(response.headers.get("X-Cached-Response"), "True")
        assert response.status_code == 429


@pytest.mark.parametrize(
    "path,expected",
    (
        ("/", False),
        ("/account/login/", True),
        ("/register", True),
    ),
)
@pytest.mark.django_db
@override_settings(CSRF_USE_SESSIONS=True)
def test_pdb_session_middleware(path, expected):
    """
    test that new sessions only get established on certain paths
    """

    client = Client()
    client.get(path)

    # Get session key from client's cookies
    if expected:
        assert client.cookies.get(settings.SESSION_COOKIE_NAME) is not None
    else:
        assert client.cookies.get(settings.SESSION_COOKIE_NAME) is None


@pytest.mark.parametrize(
    "http_status_code,expected",
    (
        (200, False),
        (401, True),
        (403, True),
        (429, True),
    ),
)
@pytest.mark.django_db
@override_settings(CSRF_USE_SESSIONS=False)
@patch("django.urls.resolvers.URLResolver.resolve")
def test_pdb_negative_cache(mock_resolve, http_status_code, expected):
    """
    Tests negative caching outside of /api endpoints
    """

    client = Client()

    def mock_view_repsonse(request):
        return HttpResponse(f"Response {http_status_code}", status=http_status_code)

    mock_match = ResolverMatch(mock_view_repsonse, [], {}, "")
    mock_resolve.return_value = mock_match

    response = client.get(f"/?test_status={http_status_code}")

    assert response.status_code == http_status_code

    assert response.headers.get("X-Cached-Response") is None

    response = client.get(f"/?test_status={http_status_code}")

    # Get session key from client's cookies
    if expected:
        assert response.headers.get("X-Cached-Response") == "True"
    else:
        assert response.headers.get("X-Cached-Response") is None


@pytest.mark.parametrize(
    "http_status_code,expected",
    (
        (400, False),
        (401, True),
        (403, True),
    ),
)
@pytest.mark.django_db
@override_settings(CSRF_USE_SESSIONS=False, NEGATIVE_CACHE_REPEATED_RATE_LIMIT=3)
@patch("django.urls.resolvers.URLResolver.resolve")
def test_pdb_negative_cache_ratelimit(mock_resolve, http_status_code, expected):
    """
    Tests negative caching rate limiting
    """

    client = Client()
    num_requests = 8
    limit = 3

    def mock_view_repsonse(request):
        return HttpResponse(f"Response {http_status_code}", status=http_status_code)

    mock_match = ResolverMatch(mock_view_repsonse, [], {}, "")
    mock_resolve.return_value = mock_match

    for i in range(num_requests):
        response = client.get(f"/?test_status={http_status_code}")

        if i < limit + 1 or not expected:
            assert response.status_code == http_status_code
            assert response.headers.get("X-Throttled-Response") is None
        else:
            assert response.status_code == 429
            assert response.headers.get("X-Throttled-Response") == "True"
