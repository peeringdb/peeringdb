"""
Caller identity in the uWSGI request log (#487).
"""

import base64
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils.timezone import make_aware
from oauth2_provider.models import AccessToken
from rest_framework.test import APITestCase

from peeringdb_server.middleware import (
    UwsgiLogVarsMiddleware,
    get_log_auth_id,
    get_log_invalid_key_id,
)
from peeringdb_server.models import Organization, OrganizationAPIKey, User, UserAPIKey

from .util import reset_group_ids

# the autouse cache cleanup fixture needs the database
pytestmark = pytest.mark.django_db


class FakeUwsgi:
    """
    Stands in for the uwsgi module, recording the request's log variables.
    """

    def __init__(self):
        self.logvars = {}

    def set_logvar(self, key, value):
        self.logvars[key] = value


@override_settings(
    API_CACHE_ENABLED=False,
    # once MFA enforcement is live basic auth is answered with a 403 before
    # the auth middleware sees it, so push both start dates out of the way
    MFA_FORCE_SOFT_START=make_aware(datetime(2099, 1, 1)),
    MFA_FORCE_HARD_START=make_aware(datetime(2099, 1, 1)),
)
class UwsgiLogVarsTest(APITestCase):
    def setUp(self):
        reset_group_ids()
        caches["negative"].clear()
        self.user = User.objects.create(username="log_auth_user")
        self.user.set_password("log_auth_pass")
        self.user.save()
        # the client loads its middleware on its first request
        self.uwsgi = FakeUwsgi()
        patcher = patch("peeringdb_server.middleware.uwsgi", self.uwsgi)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, path="/api/fac", method="get"):
        """
        Requests `path` and returns the response and its log variables.
        """
        self.uwsgi.logvars.clear()
        response = getattr(self.client, method)(path)
        return response, dict(self.uwsgi.logvars)

    def basic_auth(self, username, password):
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.client.credentials(HTTP_AUTHORIZATION=f"Basic {encoded}")

    def test_anonymous(self):
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {"auth_id": "anon", "auth_status": "unauthenticated"}

    def test_session_auth(self):
        self.client.force_login(self.user)
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_basic_auth(self):
        self.basic_auth("log_auth_user", "log_auth_pass")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_failed_basic_auth_never_logs_username(self):
        for username in ("log_auth_user", "no_such_log_user"):
            with self.subTest(username=username):
                caches["negative"].clear()
                self.basic_auth(username, "wrong-password")
                response, logvars = self.request()
                assert response.status_code == 401
                # the header keeps reporting the attempted username
                assert response.headers["X-Auth-ID"] == username
                assert logvars == {
                    "auth_id": "unverified",
                    "auth_status": "unauthenticated",
                }

    def test_user_api_key(self):
        api_key, key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars["auth_id"] == f"u{self.user.id}_apikey_{api_key.prefix}"
        # key auth doesn't set request.user, same as the header
        assert logvars["auth_status"] == "unauthenticated"

    def test_org_api_key(self):
        org = Organization.objects.create(name="Log Auth Org", status="ok")
        api_key, key = OrganizationAPIKey.objects.create_key(name="log", org=org)
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 200
        assert logvars["auth_id"] == f"o{org.id}_apikey_{api_key.prefix}"

    def test_denied_api_key_logs_full_identity(self):
        org = Organization.objects.create(name="Log Auth Org", status="ok")
        api_key, key = OrganizationAPIKey.objects.create_key(name="log", org=org)
        auth_id = f"o{org.id}_apikey_{api_key.prefix}"
        assert len(auth_id) > 16
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        # as-set is read-only, DRF answers a write with a 401
        response, logvars = self.request("/api/as_set", method="post")
        assert response.status_code == 401
        # the header keeps cutting the identity to 16 characters on a 401
        assert response.headers["X-Auth-ID"] == auth_id[:16]
        assert logvars["auth_id"] == auth_id

    def test_invalid_api_key_logs_prefix_only(self):
        api_key, real_key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        prefix, secret = real_key.split(".", 1)
        typo = "x" if secret[-1] != "x" else "y"
        key = f"{prefix}.{secret[:-1]}{typo}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 401
        # the header keeps reporting the first 16 characters
        assert response.headers["X-Auth-ID"] == f"apikey_{key[:16]}"
        assert logvars == {
            "auth_id": f"apikey_{prefix}",
            "auth_status": "unauthenticated",
        }

    def test_invalid_api_key_unexpected_shape(self):
        for key in (
            "bogus",
            "nodotbutverylongkey",
            "S3cr3tS3cr3tS3cr3tS3cr3tS3cr3t",
            "ghp_A1b2.C3d4E5f6G7h8",
            "short.secretpart",
        ):
            with self.subTest(key=key):
                caches["negative"].clear()
                self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
                response, logvars = self.request()
                assert response.status_code == 401
                assert logvars["auth_id"] == "apikey_invalid"

    def test_inactive_api_key(self):
        api_key, key = UserAPIKey.objects.create_key(
            name="log", user=self.user, readonly=True
        )
        api_key.status = "inactive"
        api_key.save()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        response, logvars = self.request()
        assert response.status_code == 401
        assert logvars["auth_id"] == "unverified"

    def test_negative_cache_response(self):
        self.basic_auth("no_such_log_user", "wrong-password")
        self.client.get("/api/fac")
        response, logvars = self.request()
        assert response.headers.get("X-Cached-Response") == "True"
        assert response.status_code == 401
        assert logvars == {"auth_id": "unverified", "auth_status": "unauthenticated"}

    def test_oauth_bearer(self):
        AccessToken.objects.create(
            user=self.user,
            token="log-auth-access-token",
            expires=make_aware(datetime.now() + timedelta(days=1)),
            scope="profile email",
        )
        for header in (
            "Bearer log-auth-access-token",
            "bearer  log-auth-access-token",
        ):
            with self.subTest(header=header):
                self.client.credentials(HTTP_AUTHORIZATION=header)
                response, logvars = self.request()
                assert response.status_code == 200
                assert "X-Auth-ID" not in response.headers
                assert logvars == {
                    "auth_id": f"u{self.user.id}_oauth",
                    "auth_status": "authenticated",
                }

    def test_view_exception(self):
        self.client.raise_request_exception = False
        self.basic_auth("log_auth_user", "log_auth_pass")
        with patch(
            "peeringdb_server.rest.FacilityViewSet.list",
            side_effect=RuntimeError("boom"),
        ):
            response, logvars = self.request()
        assert response.status_code == 500
        assert logvars == {
            "auth_id": f"u{self.user.id}",
            "auth_status": "authenticated",
        }

    def test_logvar_failure_does_not_change_response(self):
        with (
            patch.object(self.uwsgi, "set_logvar", side_effect=RuntimeError("boom")),
            # the django logger runs at ERROR outside DEBUG
            self.assertLogs("django", "ERROR") as logs,
        ):
            response = self.client.get("/api/fac")
        assert response.status_code == 200
        assert "setting uwsgi log variables failed" in "\n".join(logs.output)


def test_middleware_not_used_without_uwsgi():
    with (
        patch("peeringdb_server.middleware.uwsgi", None),
        pytest.raises(MiddlewareNotUsed),
    ):
        UwsgiLogVarsMiddleware(lambda request: HttpResponse())


def test_log_auth_id_unevaluated_session_cookie():
    request = RequestFactory().get("/api/fac")
    request.COOKIES[settings.SESSION_COOKIE_NAME] = "some-session"
    assert get_log_auth_id(request) == "unverified"


def test_log_auth_id_rejected_session_cookie():
    request = RequestFactory().get("/api/fac")
    request.COOKIES[settings.SESSION_COOKIE_NAME] = "stale-session"
    request.user = AnonymousUser()
    assert get_log_auth_id(request) == "anon"


@pytest.mark.parametrize(
    "key,logged",
    [
        ("AbCd1234.secretsecretsecret", "apikey_AbCd1234"),
        ("AbCd1234.", "apikey_AbCd1234"),
        ("AbCd123.secret", "apikey_invalid"),
        ("AbCd12345.secret", "apikey_invalid"),
        ("AbCd-234.secret", "apikey_invalid"),
        ("nodotatall", "apikey_invalid"),
        ("", "apikey_invalid"),
    ],
)
def test_get_log_invalid_key_id(key, logged):
    assert get_log_invalid_key_id(key) == logged
